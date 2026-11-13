"""Document ingestion, review, vector retrieval and local grounded generation."""
from contextlib import closing
from io import BytesIO
from math import isfinite
from pathlib import Path
import json
import os
import re
import sqlite3
import time
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from pypdf import PdfReader
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from hub.engine import EMBEDDER, GENERATOR, RERANKER, Engine, chunks

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("HUB_DB", ROOT / "data" / "hub.sqlite3"))
MIN_SIM = float(os.environ.get("HUB_MIN_SIM", "0.72"))
MIN_RERANK = float(os.environ.get("HUB_MIN_RERANK", "0"))
engine = Engine()
app = FastAPI(title="AI Knowledge & Decision Support Platform", version="0.2.0")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS documents (
      id INTEGER PRIMARY KEY, slug TEXT NOT NULL, version INTEGER NOT NULL,
      title TEXT NOT NULL, locale TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
      UNIQUE(slug,version)
    );
    CREATE TABLE IF NOT EXISTS chunks (
      document INTEGER REFERENCES documents(id), ordinal INTEGER, text TEXT NOT NULL,
      vector TEXT NOT NULL, embedding_model TEXT NOT NULL, PRIMARY KEY(document,ordinal)
    );
    """)
    migrations = (("documents", "filename", "TEXT"), ("chunks", "page", "INTEGER"))
    if any(column not in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
           for table, column, _ in migrations):
        with db:
            db.execute("BEGIN IMMEDIATE")
            for table, column, kind in migrations:
                if column not in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    return db


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Locale = Literal["en", "es", "fr"]


class Metadata(Input):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,59}$")
    title: str = Field(min_length=1, max_length=120)
    locale: Locale


class Document(Metadata):
    text: str = Field(min_length=20, max_length=24000)


class Review(Input):
    status: Literal["published", "archived"]


class Question(Input):
    question: str = Field(min_length=4, max_length=500)
    locale: Locale = "en"


def model_error(exc):
    raise HTTPException(503, "Local model unavailable. See setup and model cache instructions.") from exc


@app.get("/api/health")
def health():
    return {"status": "ok", "embedding": EMBEDDER, "reranker": RERANKER, "generator": GENERATOR,
            "device": engine.device, "models_loaded": list(engine.models)}


@app.get("/api/sources")
def sources():
    with closing(connect()) as db:
        return [dict(row) for row in db.execute("SELECT * FROM documents ORDER BY slug, version DESC")]


@app.post("/api/documents", status_code=201)
def ingest(doc: Document):
    return save_draft(doc, [(None, p) for p in chunks(doc.text)])


PDF_BYTES = 5 * 1024 * 1024
PDF_PAGES = 50
PDF_TEXT = 120_000


@app.middleware("http")
async def limit_pdf_request(request: Request, call_next):
    if request.method == "POST" and request.url.path.rstrip("/") == "/api/documents/pdf":
        length = request.headers.get("content-length", "")
        if not length.isascii() or not length.isdecimal() or len(length) > 12:
            return JSONResponse({"detail": "PDF uploads require a valid Content-Length"}, status_code=411)
        if int(length) > PDF_BYTES + 65536:
            return JSONResponse({"detail": "PDF upload exceeds the request limit"}, status_code=413)
    return await call_next(request)


@app.post("/api/documents/pdf", status_code=201)
def ingest_pdf(
    slug: str = Form(pattern=r"^[a-z0-9][a-z0-9-]{0,59}$"),
    title: str = Form(min_length=1, max_length=120, pattern=r"\S"),
    locale: Locale = Form(),
    file: UploadFile = File(),
):
    raw = file.file.read(PDF_BYTES + 1)
    if len(raw) > PDF_BYTES:
        raise HTTPException(413, "PDF exceeds the 5 MiB upload limit")
    if not raw.startswith(b"%PDF-"):
        raise HTTPException(422, "Upload a valid PDF file")
    passages = []
    total = 0
    try:
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted:
            raise HTTPException(422, "Encrypted PDFs are not supported")
        if len(reader.pages) > PDF_PAGES:
            raise HTTPException(413, "PDF exceeds the 50-page limit")
        for page, sheet in enumerate(reader.pages, 1):
            extracted = sheet.extract_text() or ""
            total += len(extracted)
            if total > PDF_TEXT:
                raise HTTPException(413, "PDF exceeds the extracted text limit")
            passages.extend((page, p) for p in chunks(extracted))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, "PDF could not be read") from exc
    if not passages:
        raise HTTPException(422, "No selectable text found. Scanned PDFs need OCR first.")
    filename = (file.filename or "document.pdf").replace(chr(92), "/").rsplit("/", 1)[-1][:255] or "document.pdf"
    return save_draft(Metadata(slug=slug, title=title, locale=locale), passages, filename)


def save_draft(doc, passages, filename=None):
    try:
        vectors = engine.encode([text for _, text in passages])
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        model_error(exc)
    with closing(connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM documents WHERE slug=?", (doc.slug,)).fetchone()[0]
        cursor = db.execute("INSERT INTO documents(slug,version,title,locale,filename) VALUES(?,?,?,?,?)",
                            (doc.slug, version, doc.title, doc.locale, filename))
        doc_id = cursor.lastrowid
        db.executemany("INSERT INTO chunks(document,ordinal,text,vector,embedding_model,page) VALUES(?,?,?,?,?,?)",
                       [(doc_id, i, text, json.dumps(v), EMBEDDER, page)
                        for i, ((page, text), v) in enumerate(zip(passages, vectors, strict=True), 1)])
    return {"id": doc_id, "version": version, "status": "draft", "chunks": len(passages)}


@app.get("/api/documents/{doc_id}")
def document(doc_id: int):
    with closing(connect()) as db:
        row = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Document not found")
        return {**dict(row), "chunks": [dict(c) for c in db.execute(
            "SELECT ordinal,text,page FROM chunks WHERE document=? ORDER BY ordinal", (doc_id,))]}


@app.patch("/api/documents/{doc_id}")
def review(doc_id: int, action: Review):
    with closing(connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Document not found")
        if action.status == "published":
            if row["status"] != "draft":
                raise HTTPException(409, "Only draft versions can be published")
            db.execute("UPDATE documents SET status='archived' WHERE slug=? AND status='published'", (row["slug"],))
        db.execute("UPDATE documents SET status=? WHERE id=?", (action.status, doc_id))
    return {"id": doc_id, "status": action.status}


def retrieve(question):
    with closing(connect()) as db:
        records = db.execute("""
            SELECT d.id,d.slug,d.title,d.locale,d.version,d.filename,c.ordinal,c.text,c.vector,c.page
            FROM chunks c JOIN documents d ON d.id=c.document
            WHERE d.status='published' AND c.embedding_model=?
        """, (EMBEDDER,)).fetchall()
    if not records:
        return []
    query = engine.encode([question], query=True)[0]
    candidates = []
    for record in records:
        item = dict(record)
        vector = json.loads(item.pop("vector"))
        score = sum(a*b for a,b in zip(vector, query, strict=True))
        if isfinite(score) and score >= MIN_SIM:
            candidates.append({**item, "similarity": score})
    candidates.sort(key=lambda c: (-c["similarity"], c["id"], c["ordinal"]))
    candidates = candidates[:8]
    if not candidates:
        return []
    scores = engine.rank(question, candidates)
    ranked = [{**c, "rerank_score": s} for c, s in zip(candidates, scores, strict=True) if isfinite(s) and s >= MIN_RERANK]
    return sorted(ranked, key=lambda c: -c["rerank_score"])[:4]


ABSTAIN = {"en": "The published documents do not provide enough evidence.",
           "es": "Los documentos publicados no aportan evidencia suficiente.",
           "fr": "Les documents publiés ne fournissent pas assez de preuves."}


@app.post("/api/search")
def search(q: Question):
    start = time.perf_counter()
    try:
        evidence = retrieve(q.question)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        model_error(exc)
    return {"sources": evidence, "retrieval_ms": round((time.perf_counter() - start) * 1000)}


@app.post("/api/ask")
def ask(q: Question):
    start = time.perf_counter()
    metrics = {}
    try:
        evidence = retrieve(q.question)
        metrics["retrieval_ms"] = round((time.perf_counter() - start) * 1000)
        if evidence:
            answer, generation = engine.answer(q.question, q.locale, evidence)
            metrics.update(generation)
        else:
            answer = ""
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        model_error(exc)
    metrics["total_ms"] = round((time.perf_counter() - start) * 1000)
    ids = set(re.findall(r"\[(S\d+)\]", answer))
    allowed = {f"S{i}" for i in range(1, len(evidence)+1)}
    bracketed = set(re.findall(r"\[([^\[\]]+)\]", answer))
    if not ids or bracketed != ids or not ids <= allowed or answer.startswith("INSUFFICIENT"):
        return {"mode": "insufficient", "answer": ABSTAIN[q.locale], "sources": [], "metrics": metrics}
    if not any(char.isalnum() for char in re.sub(r"\[S\d+\]", "", answer)):
        message = {
            "en": "Qwen returned citations without an answer. Check the passages below.",
            "es": "Qwen devolvió citas sin una respuesta. Consulta los pasajes de abajo.",
            "fr": "Qwen a fourni des citations sans réponse. Consultez les passages ci-dessous.",
        }
        return {"mode": "evidence", "answer": message[q.locale], "metrics": metrics,
                "sources": [{**c, "citation": f"S{i}"} for i, c in enumerate(evidence, 1) if f"S{i}" in ids]}
    return {"mode": "llm", "model": GENERATOR, "answer": answer, "metrics": metrics,
            "sources": [{**c, "citation": f"S{i}"} for i, c in enumerate(evidence, 1) if f"S{i}" in ids]}


if (ROOT / "dist/index.html").exists():
    app.mount("/", StaticFiles(directory=ROOT / "dist", html=True), name="web")
