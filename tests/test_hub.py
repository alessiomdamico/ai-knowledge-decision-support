import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from hub import app as hub
from hub.engine import chunks


class TestHub(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db = patch.object(hub, "DB", Path(temp.name) / "test.sqlite")
        db.start()
        self.addCleanup(db.stop)
        self.embed = patch.object(hub.engine, "encode", side_effect=lambda texts, **kw: [[1, 0] for _ in texts])
        self.embed.start()
        self.addCleanup(self.embed.stop)
        rank = patch.object(hub.engine, "rank", side_effect=lambda question, candidates: list(range(len(candidates))))
        rank.start()
        self.addCleanup(rank.stop)

    def create(self, title="Backup policy"):
        return hub.ingest(hub.Document(slug="backup", title=title, locale="en",
                                       text=f"{title}: backups are retained for 30 days."))

    def publish(self, record):
        hub.review(record["id"], hub.Review(status="published"))

    def test_chunk_overlap_and_tail(self):
        self.assertEqual(chunks("a b c d e f g", size=4, overlap=1), ["a b c d", "d e f g"])

    def test_draft_does_not_retrieve_and_publish_archives_previous(self):
        first = self.create()
        self.assertEqual(hub.retrieve("backup"), [])
        self.publish(first)
        self.assertEqual(hub.retrieve("backup")[0]["version"], 1)
        second = self.create("Updated backup policy")
        self.assertEqual(second["version"], 2)
        self.publish(second)
        self.assertEqual(hub.document(first["id"])["status"], "archived")
        self.assertEqual([c["version"] for c in hub.retrieve("backup")], [2])
        with self.assertRaises(HTTPException):
            self.publish(first)

    def test_cross_language_question_maps_citation_to_exact_chunk(self):
        self.publish(self.create())
        with patch.object(hub.engine, "answer", return_value=("30 días [S1].", {"prompt_tokens": 23})) as answer:
            result = hub.ask(hub.Question(question="¿Cuántos días?", locale="es"))
        self.assertEqual(result["mode"], "llm")
        self.assertEqual(result["sources"][0]["citation"], "S1")
        self.assertEqual(result["sources"][0]["locale"], "en")
        self.assertEqual(answer.call_args.args[1], "es")

    def test_unknown_or_missing_citations_abstain(self):
        self.publish(self.create())
        for text in ("Incorrect [S8]", "Incorrect [S1] [X]", "No citation"):
            with patch.object(hub.engine, "answer", return_value=(text, {})):
                self.assertEqual(hub.ask(hub.Question(question="backup"))["mode"], "insufficient")

    def test_citation_only_output_shows_evidence_instead_of_answer(self):
        self.publish(self.create())
        with patch.object(hub.engine, "answer", return_value=("[S1].", {})):
            result = hub.ask(hub.Question(question="backup"))
        self.assertEqual(result["mode"], "evidence")
        self.assertEqual(result["sources"][0]["citation"], "S1")
        self.assertIn("without an answer", result["answer"])

    def test_search_only_returns_published_sources_without_generation(self):
        published = self.create()
        self.publish(published)
        self.create("Draft version")
        with patch.object(hub.engine, "answer") as answer:
            result = hub.search(hub.Question(question="backup"))
        self.assertEqual([s["id"] for s in result["sources"]], [published["id"]])
        answer.assert_not_called()

    def test_low_similarity_skips_generation(self):
        self.publish(self.create())
        with patch.object(hub.engine, "encode", return_value=[[0, 1]]), patch.object(hub.engine, "answer") as answer:
            self.assertEqual(hub.ask(hub.Question(question="backup"))["mode"], "insufficient")
            answer.assert_not_called()

    def test_irrelevant_reranker_score_skips_generation(self):
        self.publish(self.create())
        with patch.object(hub.engine, "rank", return_value=[-3]), patch.object(hub.engine, "answer") as answer:
            self.assertEqual(hub.ask(hub.Question(question="backup"))["mode"], "insufficient")
            answer.assert_not_called()

    def test_missing_model_returns_503(self):
        with patch.object(hub.engine, "encode", side_effect=OSError("missing")):
            with self.assertRaises(HTTPException) as ctx:
                self.create()
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(hub.sources(), [])
