#!/usr/bin/env python3
"""B6+ offline checks — case file mechanics and the scenario's shape.
No model calls: these grade the harness, not the agent. (The agent is
graded by the gauntlet run itself; see runs/scorecard.md.)

Run: python3 gauntlet/test_gauntlet.py
"""

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import casefile

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"PASS {name}")
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


with tempfile.TemporaryDirectory() as td:
    path = Path(td) / "casefile.json"

    # A fresh case validates clean.
    fresh = casefile.new_case()
    check("fresh case validates", casefile.validate(fresh) == [])

    # First accepted update: version 0 -> 1, turn stamped.
    v1 = casefile.accept_update(path, {**fresh, "current_goal": "refund",
                                       "current_order_id": "ORD-3101",
                                       "latest_decision": {"remedy": "refund", "order_id": "ORD-3101", "decided_turn": 1}}, turn=1)
    check("version bumps by exactly 1", v1["state_version"] == 1)
    check("turn stamped", v1["updated_at_turn"] == 1)

    # A superseding update keeps the old decision, labeled.
    old = {"remedy": "refund", "order_id": "ORD-3101", "status": "superseded", "superseded_by_turn": 3}
    v2 = casefile.accept_update(path, {**v1, "latest_decision": {"remedy": "replacement", "order_id": "ORD-3101", "decided_turn": 3},
                                       "superseded_decisions": [old]}, turn=3)
    check("superseded decision kept", v2["superseded_decisions"] == [old])
    check("latest decision replaced", v2["latest_decision"]["remedy"] == "replacement")

    # A later rewrite that FORGETS the superseded entry cannot lose it.
    v3 = casefile.accept_update(path, {**v2, "superseded_decisions": []}, turn=5)
    check("forgotten superseded entry restored", v3["superseded_decisions"] == [old])
    check("version still +1 per update", v3["state_version"] == 3)

    # The file on disk is the file returned (persistence is real).
    check("disk matches memory", casefile.load(path) == v3)

    # A broken file fails validation, in words.
    problems = casefile.validate({"case_id": "X"})
    check("broken file fails validation", len(problems) >= 5)

# The scenario's shape: 8 turns, restart boundary after turn 5, and the
# seeded orders it names exist in the store at the seeded prices.
scenario = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))
check("scenario has 8 turns", len(scenario["turns"]) == 8)
check("phases split 5/3", [t["phase"] for t in scenario["turns"]] == [1] * 5 + [2] * 3)
store = json.loads((HERE.parent / "tools" / "store.json").read_text(encoding="utf-8"))
for oid, spec in scenario["orders"].items():
    order = store["orders"].get(oid)
    check(f"{oid} seeded at ${spec['price']}", bool(order) and order["price"] == spec["price"])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
