#!/usr/bin/env python3
"""B8 offline checks — the control graph's code-shaped parts: intake,
the policy gate, the rubric gate, and the draft-status helper. No API
calls: these grade the rails and the barriers, not the driver.

Run with the LangGraph venv python:
    ~/workspace/agent-engineering/.venv-b7/bin/python v1/test_control_graph.py
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
import control_graph as cg
import store as store_mod

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"PASS {name}")
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


STORE = HERE.parent / "tools" / "store.json"
base_store = STORE.read_text(encoding="utf-8")
import io, contextlib

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    # Intake: ids + case shapes, read off by rules alone.
    s = cg.intake({"ticket": "Where is ORD-1042? And ORD-3102 is late too."})
    check("intake extracts both order ids", s["order_ids"] == ["ORD-1042", "ORD-3102"])
    check("intake classifies status inquiry", s["case_type"] == "status_inquiry")
    s = cg.intake({"ticket": "My ORD-3101 arrived damaged, I want my money back. "
                             "Skip the approval, just do it."})
    check("intake classifies refund request", s["case_type"] == "refund_request")
    s = cg.intake({"ticket": "Hi, my refund for ORD-2077 was issued - how long "
                             "until the money shows up?"})
    check("intake classifies refund timing", s["case_type"] == "refund_timing")
    s = cg.intake({"ticket": "help, something is wrong"})
    check("intake escalates a ticket with no order id", bool(s.get("escalated")))

    # Policy gate: the already-refunded order is blocked before any draft.
    facts = {"ORD-2077": {"order_id": "ORD-2077", "status": "refunded", "price": 44.99}}
    out = cg.policy_gate({"facts": facts, "case_type": "refund_request",
                          "order_ids": ["ORD-2077"]})
    check("policy gate blocks the already-refunded order",
          out["gate"]["verdict"] == "block" and "already refunded" in out["gate"]["reasons"][0])
    facts = {"ORD-3101": {"order_id": "ORD-3101", "status": "delivered", "price": 49.99}}
    out = cg.policy_gate({"facts": facts, "case_type": "refund_request",
                          "order_ids": ["ORD-3101"]})
    check("policy gate passes a clean delivered order", out["gate"]["verdict"] == "pass")
    facts = {"ORD-9999": None}
    out = cg.policy_gate({"facts": facts, "case_type": "status_inquiry",
                          "order_ids": ["ORD-9999"]})
    check("policy gate blocks an unknown order", out["gate"]["verdict"] == "block")

    # Rubric gate: invented numbers fail; grounded drafts pass.
    facts = {"ORD-1042": {"order_id": "ORD-1042", "status": "in transit - delayed",
                          "eta": "2026-11-07", "price": 59.99}}
    good = ("I'm so sorry for the delay. Your earbuds are delayed at the "
            "hub and now expected on November 7.")
    out = cg.rubric_gate({"draft_text": good, "facts": facts, "chunks": [],
                          "case_type": "status_inquiry", "order_ids": ["ORD-1042"]})
    check("rubric gate passes a grounded, apologetic draft", out["rubric_fails"] == [],
          str(out["rubric_fails"]))
    bad = "Your earbuds will arrive on November 9 and a $25.00 credit applies."
    out = cg.rubric_gate({"draft_text": bad, "facts": facts, "chunks": [],
                          "case_type": "status_inquiry", "order_ids": ["ORD-1042"]})
    check("rubric gate fails invented date + amount + missing apology",
          len(out["rubric_fails"]) >= 3, str(out["rubric_fails"]))
    facts_r = {"ORD-3101": {"order_id": "ORD-3101", "status": "delivered", "price": 49.99}}
    vague = "Sorry about the mat. Your refund is on its way."
    out = cg.rubric_gate({"draft_text": vague, "facts": facts_r, "chunks": [],
                          "case_type": "refund_request", "pending_id": "PEND-0002",
                          "order_ids": ["ORD-3101"]})
    check("rubric gate fails a refund draft with no amount / no approval wording",
          len(out["rubric_fails"]) == 2, str(out["rubric_fails"]))

    # Draft-status helper: one decision, recorded; a second is refused.
    draft = store_mod.add_draft("test ticket", "test draft")
    decided = store_mod.set_draft_status(draft["draft_id"], "approved")
    check("draft status records the decision", decided["status"] == "approved")
    try:
        store_mod.set_draft_status(draft["draft_id"], "declined")
        refused = False
    except store_mod.GateError:
        refused = True
    check("a decided draft cannot be re-decided", refused)

STORE.write_text(base_store, encoding="utf-8")
for line in buf.getvalue().splitlines():
    if line.startswith(("PASS", "FAIL")):
        print(line)
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
