"""Run with python -m evaluation.run; uses a temporary DB and real models."""
import json
import resource
import sys
import tempfile
from pathlib import Path

from hub import app as hub


def main():
    fixture = json.loads(Path(__file__).with_name("cases.json").read_text(encoding="utf-8"))
    previous = hub.DB
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        hub.DB = Path(tmp) / "eval.sqlite3"
        try:
            for item in fixture["documents"]:
                created = hub.ingest(hub.Document(**item))
                hub.review(created["id"], hub.Review(status="published"))
            for case in fixture["questions"]:
                result = hub.ask(hub.Question(question=case["question"], locale=case["locale"]))
                slugs = [s["slug"] for s in hub.retrieve(case["question"])]
                cited = [s["slug"] for s in result["sources"]]
                text = result["answer"].casefold()
                if case["source"] is None:
                    passed = result["mode"] == "insufficient"
                else:
                    passed = (case["source"] in cited and case["expected"].casefold() in text
                              and case.get("forbidden", "unlikely-forbidden-marker").casefold() not in text)
                rows.append({"id": case["id"], "expected_source": case["source"],
                             "retrieved": slugs, "cited": cited, "passed": passed, **result["metrics"],
                             "answer": result["answer"]})
        finally:
            hub.DB = previous
    targets = [r for r in rows if r["expected_source"]]
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(json.dumps({"retrieval_recall_at_4": sum(r["expected_source"] in r["retrieved"] for r in targets)/len(targets),
                      "answer_checks_passed": sum(r["passed"] for r in rows),
                      "peak_process_rss_mib": round(rss / (1024**2 if sys.platform == "darwin" else 1024), 1),
                      "cases": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
