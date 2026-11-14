"""B6+ — the case file: persisted, versioned working state for one case.

The conversation is an input stream; this file is the working state the
system has *accepted*; the store stays the truth about the world. The
harness (run_gauntlet.py) owns the mechanics here — version increments,
the turn stamp, lenient repair of a model-written file — so the rules in
case_file_schema.md hold even when the model writes an imperfect file:
a superseded decision is never silently dropped by a rewrite (the
harness re-attaches any prior superseded entries the new file forgot),
and the version only ever moves by +1 per accepted update.
"""

import json
from pathlib import Path

REQUIRED_KEYS = [
    "case_id", "state_version", "customer_ref", "current_goal",
    "current_order_id", "live_order_ids", "facts", "latest_decision",
    "superseded_decisions", "completed_actions", "pending_approval",
    "open_question", "updated_at_turn",
]


def new_case(case_id="CASE-0001", customer_ref="sandbox customer"):
    return {
        "case_id": case_id,
        "state_version": 0,
        "customer_ref": customer_ref,
        "current_goal": None,
        "current_order_id": None,
        "live_order_ids": [],
        "facts": [],
        "latest_decision": None,
        "superseded_decisions": [],
        "completed_actions": [],
        "pending_approval": None,
        "open_question": None,
        "updated_at_turn": 0,
    }


def validate(case):
    """Strict shape check (used by the tests). Returns a list of problems;
    an empty list means the file is schema-clean."""
    problems = []
    if not isinstance(case, dict):
        return ["case file is not a JSON object"]
    for key in REQUIRED_KEYS:
        if key not in case:
            problems.append(f"missing key: {key}")
    if isinstance(case.get("state_version"), int) and case["state_version"] < 0:
        problems.append("state_version is negative")
    if not isinstance(case.get("live_order_ids", []), list):
        problems.append("live_order_ids is not a list")
    if not isinstance(case.get("superseded_decisions", []), list):
        problems.append("superseded_decisions is not a list")
    if not isinstance(case.get("completed_actions", []), list):
        problems.append("completed_actions is not a list")
    return problems


def load(path):
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def accept_update(path, proposed, turn):
    """Write an accepted update: fill any keys the writer forgot from the
    previous file (or a fresh case), protect the superseded history from
    silent loss, bump the version by exactly 1, stamp the turn. Returns
    the file as written."""
    previous = load(path) or new_case()
    merged = new_case(case_id=previous.get("case_id", "CASE-0001"),
                      customer_ref=previous.get("customer_ref", "sandbox customer"))
    merged.update(previous)
    if isinstance(proposed, dict):
        for key, value in proposed.items():
            if key in REQUIRED_KEYS and key != "state_version":
                merged[key] = value
    # A rewrite may not quietly drop superseded decisions (B6+ Q2): any
    # prior superseded entry the new file forgot comes back.
    seen = {json.dumps(d, sort_keys=True) for d in merged.get("superseded_decisions", [])}
    for old in previous.get("superseded_decisions", []):
        if json.dumps(old, sort_keys=True) not in seen:
            merged["superseded_decisions"].append(old)
    merged["state_version"] = int(previous.get("state_version", 0)) + 1
    merged["updated_at_turn"] = turn
    Path(path).write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return merged
