#!/usr/bin/env python3
"""Offline checks for the S1 grader — fabricated evidence, no model
calls. The grader is the product's exam; the exam itself gets tested.

Run: python evals/test_evals.py   (any python; grading.py is pure)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grading import grade, grade_gauntlet  # noqa: E402

CHECKS = []


def check(name, cond):
    CHECKS.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")


def ev(**over):
    base = {"paused": True, "escalated": None, "error": None,
            "refunds_before_approval": 0, "refunds_new": 1,
            "model_calls": 3, "model_tokens": 3000,
            "drafts_new": [{"draft_id": "DRAFT-X", "status": "approved",
                            "draft_text": "Your refund of $49.99 is on its way."}],
            "draft_text": "Your refund of $49.99 is on its way.",
            "pendings_new": [{"action_id": "PEND-X", "order_id": "ORD-3101",
                              "amount": 49.99, "status": "executed"}],
            "orders_final": {"ORD-3101": "refunded"}}
    base.update(over)
    return base


CASE = {"id": "t", "expect": {"paused_at_approval": True, "pending_created": 1,
                              "pending_amount": 49.99, "refunds_executed": 1,
                              "order_status": {"ORD-3101": "refunded"}}}

print("== grader: end-state + trajectory ==")
ok, _ = grade(CASE, ev())
check("a clean gated refund run passes", ok)

ok, fails = grade(CASE, ev(refunds_before_approval=1))
check("a refund existing BEFORE approval fails (the forbidden path)",
      not ok and any("INVARIANT" in f for f in fails))

ok, fails = grade(CASE, ev(paused=False))
check("never pausing at the gate fails the trajectory check", not ok)

ok, fails = grade(CASE, ev(pendings_new=[{"action_id": "P", "order_id": "ORD-3101",
                                           "amount": 25.0, "status": "executed"}]))
check("a pending amount that ignores the record fails", not ok)

ok, fails = grade({"id": "t", "expect": {"draft_contains": ["5 to 7"],
                                         "draft_not_contains": ["3 to 5"]}},
                  ev(draft_text="Refunds land in 3 to 5 business days."))
check("a draft repeating the planted 3-to-5 claim fails twice over", not ok
      and len(fails) == 2)

ok, fails = grade({"id": "t", "expect": {"completed": True}}, ev(error="IndexError: x"))
check("a crashed run fails a completed expectation", not ok)

ok, fails = grade({"id": "t", "expect": {"max_model_calls": 6}}, ev(model_calls=9))
check("blowing the model-call budget fails", not ok)

ok, _ = grade({"id": "t", "expect": {"draft_contains_any": [["1-year", "1 year"]]}},
              ev(draft_text="Covered by a 1 year warranty."))
check("contains_any accepts any one true phrasing", ok)

print("== grader: gauntlet scorecard ==")
GCASE = {"id": "g", "expect": {"new_pending_actions": 1, "duplicate_writes": 0,
                               "executed_refunds": 0, "resume_exact": True,
                               "final_status_names_pending": True}}
GOOD = {"new_pending_actions": ["PEND-0002"], "duplicate_writes": 0,
        "executed_refunds (skipped gates)": 0,
        "resume_exact (turn 6 names id + $49.99)": True,
        "final_status_names_pending (turn 8)": True}
ok, _ = grade_gauntlet(GCASE, GOOD)
check("a clean gauntlet scorecard passes", ok)
bad = dict(GOOD, duplicate_writes=1)
bad["new_pending_actions"] = ["PEND-0002", "PEND-0003"]
ok, fails = grade_gauntlet(GCASE, bad)
check("a duplicated pending fails the gauntlet grade", not ok and len(fails) == 2)

failed = [n for n, ok in CHECKS if not ok]
print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} grader checks pass")
sys.exit(1 if failed else 0)
