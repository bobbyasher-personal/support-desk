#!/usr/bin/env python3
"""S2 proof runs — the control graph with the flight recorder on.

Runs the three B8 cases (cg1 regression, cg2 pressure test, cg3 trap)
against a store snapshot with tracing enabled, approves as "bobby" at
the gate exactly like the B8 proof, restores the store, and then READS
EACH TRACE BACK from the store (traces/) and verifies it: the case id
is stamped on every span, every parent resolves, the model spans'
token total equals the run's own MODEL_CALLS counter, and the
governance spans (gates, approval, receipt) carry their verdicts.

The read-back is the receipt (F4): this script trusts nothing the run
printed about itself.

    ~/workspace/agent-engineering/.venv-b7/bin/python v1/traced_run.py
"""

import json
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
import control_graph as cg
import tracing
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

STORE = HERE.parent / "tools" / "store.json"


def run_traced(name):
    base = STORE.read_text(encoding="utf-8")
    cg.MODEL_CALLS.update({"n": 0, "tokens": 0})
    tracer = tracing.Tracer(case_id=name, run_name=f"control graph {name}")
    cg.TRACER = tracer
    started = time.time()
    result, paused = {}, False
    try:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ckpt.sqlite"
            with SqliteSaver.from_conn_string(str(db)) as saver:
                graph = cg.build_control_graph(checkpointer=saver)
                cfg = {"configurable": {"thread_id": f"traced-{name}"},
                       "recursion_limit": 40}
                result = graph.invoke({"ticket": cg.CASES[name]}, cfg)
                paused = "__interrupt__" in result
                if paused:
                    result = graph.invoke(
                        Command(resume={"approved": True, "approver": "bobby"}), cfg)
    finally:
        cg.TRACER = None
        STORE.write_text(base, encoding="utf-8")
    if result.get("receipt"):
        outcome = "approved"
    elif result.get("escalated"):
        outcome = "escalated"
    else:
        outcome = "completed"
    path = tracer.finish(outcome=outcome)
    return path, outcome, round(time.time() - started, 1)


def verify(path, name, expect):
    t = tracing.read_trace(path)
    spans = t["spans"]
    by_id = {s["span_id"]: s for s in spans}
    checks = {}
    checks["case id on every span"] = all(
        s["attributes"].get("supportdesk.case_id") == name for s in spans)
    checks["every parent resolves"] = all(
        s["parent_span_id"] is None or s["parent_span_id"] in by_id for s in spans)
    checks["root outcome recorded"] = t["outcome"] == expect["outcome"]
    model_tokens = sum(s["attributes"].get("gen_ai.usage.input_tokens", 0)
                       + s["attributes"].get("gen_ai.usage.output_tokens", 0)
                       for s in spans if s["kind"] == "gen_ai.chat")
    checks["model tokens reconcile with the run counter"] = \
        model_tokens == expect["model_tokens"]
    gates = {s["attributes"].get("supportdesk.gate.name"): s for s in spans
             if s["kind"] == "supportdesk.gate"}
    checks["policy gate span carries its verdict"] = \
        gates.get("policy_gate", {}).get("attributes", {}).get(
            "supportdesk.gate.verdict") == expect["policy"]
    if expect.get("rubric"):
        checks["rubric gate span present"] = "rubric_gate" in gates
    if expect.get("approval"):
        appr = [s for s in spans if s["kind"] == "supportdesk.human"
                and s["attributes"].get("supportdesk.approval.approved") is True]
        checks["approval span records the human decision"] = bool(appr)
        fin = [s for s in spans if s["name"] == "finalize"]
        checks["finalize span carries the read-back receipt"] = bool(
            fin and fin[0]["attributes"].get("supportdesk.receipt"))
    return t, checks


def main():
    expectations = {
        "cg1": {"outcome": "approved", "policy": "pass", "rubric": True,
                "approval": True},
        "cg2": {"outcome": "approved", "policy": "pass", "rubric": True,
                "approval": True},
        "cg3": {"outcome": "escalated", "policy": "block", "rubric": False,
                "approval": False},
    }
    all_ok = True
    for name in ("cg1", "cg2", "cg3"):
        cg.TRACE.clear()
        path, outcome, secs = run_traced(name)
        exp = dict(expectations[name])
        exp["model_tokens"] = cg.MODEL_CALLS["tokens"]
        t, checks = verify(path, name, exp)
        ok = all(checks.values())
        all_ok = all_ok and ok
        print(f"\n===== TRACED {name} -> {path.relative_to(tracing.ROOT)} "
              f"({secs}s, outcome {outcome}) =====")
        print(f"  spans: {t['totals']['spans']}  model calls: "
              f"{t['totals']['model_calls']}  tokens: "
              f"{t['totals']['input_tokens'] + t['totals']['output_tokens']}  "
              f"tool calls: {t['totals']['tool_calls']}")
        for label, passed in checks.items():
            print(f"  {'PASS' if passed else 'FAIL'}  {label}")
    print("\nS2 RECORDER: " + ("VERIFIED — traces read back and reconciled."
                               if all_ok else "FAILED — see checks above."))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
