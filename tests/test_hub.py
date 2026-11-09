import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from hub import app as hub


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def read(self, size):
        return json.dumps({"choices": [{"message": {"content": self.content}}]}).encode()


class HubTests(unittest.TestCase):
    def test_language_and_draft_isolation(self):
        self.assertEqual([s["id"] for s in hub.retrieve("¿Qué financia la campaña de agua segura?", "es")], ["water-es"])
        self.assertFalse(hub.retrieve("expansion", "en"))
        draft = next(s for s in hub.library() if s["status"] == "draft")
        self.assertNotIn("text", draft)

    @patch.object(hub, "MODEL", "test-model")
    @patch.object(hub, "urlopen")
    def test_unrelated_question_never_calls_model(self, call):
        response = hub.ask(hub.Question(question="Who discovered Neptune?"))
        self.assertEqual(response["mode"], "insufficient")
        call.assert_not_called()

    @patch.object(hub, "MODEL", "test-model")
    @patch.object(hub, "urlopen", return_value=FakeResponse("1"))
    def test_model_receives_retrieved_evidence_and_citation_resolves(self, call):
        result = hub.ask(hub.Question(question="What does the water appeal fund?"))
        self.assertEqual(result["mode"], "llm")
        self.assertEqual([s["id"] for s in result["sources"]], ["water-en"])
        request = json.loads(call.call_args.args[0].data)
        evidence = request["messages"][1]["content"]
        self.assertIn("water quality testing", evidence)
        self.assertNotIn("Unverified planning material", evidence)
        self.assertIn("[water-en]", result["answer"])

    @patch.object(hub, "MODEL", "test-model")
    @patch.object(hub, "urlopen", return_value=FakeResponse("99"))
    def test_invalid_evidence_selection_is_rejected(self, call):
        result = hub.ask(hub.Question(question="What does the water appeal fund?"))
        self.assertEqual(result["mode"], "fallback")
        self.assertIn("[water-en]", result["answer"])
        self.assertNotIn("Invented", result["answer"])

    @patch.object(hub, "MODEL", "test-model")
    @patch.object(hub, "urlopen", side_effect=URLError("offline"))
    def test_model_outage_returns_attributed_excerpts(self, call):
        result = hub.ask(hub.Question(question="What belongs in a donor update?"))
        self.assertEqual(result["mode"], "fallback")
        self.assertIn("[report-en]", result["answer"])
