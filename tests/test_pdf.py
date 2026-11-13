from io import BytesIO
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from hub import app as hub


def upload(texts, password=None):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=300, height=300)
        if text:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                     NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 10 200 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    if password:
        writer.encrypt(password)
    data = BytesIO()
    writer.write(data)
    data.seek(0)
    return UploadFile(file=data, filename="policy.pdf")


class PDFTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "test.sqlite"
        self.enterContext(patch.object(hub, "DB", self.db))

    def test_page_metadata_survives_review_and_citation(self):
        self.enterContext(patch.object(hub.engine, "encode", side_effect=lambda texts, **_: [[1, 0] for _ in texts]))
        self.enterContext(patch.object(hub.engine, "rank", return_value=[1, 2]))
        self.enterContext(patch.object(hub.engine, "answer", return_value=("Keep records for 30 days [S1].", {})))
        doc = hub.ingest_pdf("backup", "Backup policy", "en",
                             upload(["Backups are encrypted.", "", "Retain backups for 30 days."]))
        self.assertEqual(hub.retrieve("retention"), [])
        stored = hub.document(doc["id"])
        self.assertEqual(stored["filename"], "policy.pdf")
        self.assertEqual([c["page"] for c in stored["chunks"]], [1, 3])
        hub.review(doc["id"], hub.Review(status="published"))
        result = hub.ask(hub.Question(question="How long is backup retention?"))
        self.assertEqual(result["mode"], "llm")
        self.assertEqual(result["sources"][0]["page"], 3)
        self.assertEqual(result["sources"][0]["filename"], "policy.pdf")

    def test_invalid_pdf_uploads_are_rejected(self):
        cases = [
            (UploadFile(file=BytesIO(b"not a PDF")), 422),
            (UploadFile(file=BytesIO(b"%PDF-1.7\ninvalid")), 422),
            (UploadFile(file=BytesIO(b"x" * (hub.PDF_BYTES + 1))), 413),
            (upload([""], password="test"), 422),
            (upload([""]), 422),
            (upload([""] * (hub.PDF_PAGES + 1)), 413),
        ]
        with patch.object(hub.engine, "encode") as encode:
            for file, code in cases:
                with self.subTest(code=code), self.assertRaises(HTTPException) as exc:
                    hub.ingest_pdf("backup", "Backup policy", "en", file)
                self.assertEqual(exc.exception.status_code, code)
            encode.assert_not_called()
        self.assertEqual(hub.sources(), [])

    def test_existing_plain_text_database_migrates(self):
        with sqlite3.connect(self.db) as db:
            db.executescript("""
                CREATE TABLE documents (id INTEGER PRIMARY KEY, slug TEXT, version INTEGER,
                                        title TEXT, locale TEXT, status TEXT);
                CREATE TABLE chunks (document INTEGER, ordinal INTEGER, text TEXT,
                                     vector TEXT, embedding_model TEXT);
                INSERT INTO documents VALUES (1,'backup',1,'Backup','en','published');
                INSERT INTO chunks VALUES (1,1,'Original text','[]','legacy');
            """)
        row = hub.document(1)
        self.assertIsNone(row["filename"])
        self.assertIsNone(row["chunks"][0]["page"])
        self.assertEqual(row["chunks"][0]["text"], "Original text")
