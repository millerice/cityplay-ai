"""Live core validation from a previously reviewed private model intent.

Usage: PYTHONPATH=src python3 scripts/validate_stage2.py --source <private-run.json>
Fetches fresh Qloo data once, then reuses the same private in-memory cache to
validate hard constraints and explicit feedback without extra API requests.
"""
import argparse
import json
from dataclasses import asdict
from pathlib import Path
from cityplay.__main__ import save_private
from cityplay.config import ROOT, Settings
from cityplay.engine import DiscoveryEngine
from cityplay.intent import Intent, Area
from cityplay.transport import QlooClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.source.read_text())
    original = dict(source["intent"])
    original.pop("parser", None)
    area = Area(**source["area"])
    settings = Settings.load()
    client = QlooClient(settings.qloo_key)
    engine = DiscoveryEngine(client)
    positive = engine.run(Intent.from_dict(original), area)
    calls = client.calls
    constrained = Intent.from_dict({**original, "max_budget": {"amount": 50, "currency": "USD"},
                                   "available_minutes": 180, "open_now": True})
    negative = engine.run(constrained, area)
    shown_ids = [card["entity_id"] for card in positive["cards"]]
    feedback = engine.run(Intent.from_dict(original), area, seen_ids=shown_ids)
    checks = {"positive_has_real_cards": bool(positive["cards"]),
              "unknown_operational_constraints_blocked": negative["status"] == "empty" and not negative["cards"],
              "shown_candidates_excluded": not set(shown_ids) & {card["entity_id"] for card in feedback["cards"]},
              "bounded_cache_reused": client.calls == calls,
              "cached_results_labeled": negative["source"] == "cached_qloo" and feedback["source"] == "cached_qloo",
              "query_parameters_traced": all("query" in item for item in client.trace)}
    for name, result in [("positive", positive), ("hard_constraints", negative), ("feedback", feedback)]:
        result["validation_scenario"] = name
        result["parsed_intent_source_run"] = source["run_id"]
        save_private(ROOT / ".qloo-private" / "stage2" / (result["run_id"] + ".json"), result, settings)
    summary = {"status": "pass" if all(checks.values()) else "fail", "checks": checks,
               "qloo_network_attempts": client.calls, "positive_cards": len(positive["cards"]),
               "feedback_cards": len(feedback["cards"])}
    print(json.dumps(summary))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
