#!/usr/bin/env python3
"""S2 offline checks — the flight recorder itself: span shape, parenting,
the case id on every span, retries as separate spans, errors recorded
(not swallowed), token totals, and the control-graph hook (recorder off
= zero behavior change; recorder on = spans appear).

No API calls. Run with the LangGraph venv python:
    ~/workspace/agent-engineering/.venv-b7/bin/python v1/test_tracing.py
"""

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
import tracing
import control_graph as cg

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"PASS {name}")
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


with tempfile.TemporaryDirectory() as tmp:
    store = Path(tmp)
    tr = tracing.Tracer(case_id="case-42", run_name="unit run", store_dir=store)
    with tr.span("intake", "agent.operation"):
        pass
    with tr.span("draft", "agent.operation"):
        with tr.span("model call", "gen_ai.chat",
                     {"gen_ai.request.model": "fake",
                      "gen_ai.usage.input_tokens": 100,
                      "gen_ai.usage.output_tokens": 23}):
            pass
    # a retry is a second span, not a rewrite of the first
    with tr.span("draft", "agent.operation"):
        with tr.span("model call", "gen_ai.chat",
                     {"gen_ai.usage.input_tokens": 50,
                      "gen_ai.usage.output_tokens": 10}):
            pass
    try:
        with tr.span("boom", "agent.operation"):
            raise ValueError("recorded, not swallowed")
    except ValueError:
        pass
    path = tr.finish(outcome="approved")

    t = tracing.read_trace(path)
    spans = t["spans"]
    by_id = {s["span_id"]: s for s in spans}
    check("trace reads back with its case id", t["case_id"] == "case-42")
    check("root span carries the outcome", t["outcome"] == "approved")
    check("case id stamped on EVERY span",
          all(s["attributes"].get("supportdesk.case_id") == "case-42" for s in spans))
    check("every parent resolves",
          all(s["parent_span_id"] is None or s["parent_span_id"] in by_id
              for s in spans))
    model_spans = [s for s in spans if s["kind"] == "gen_ai.chat"]
    check("model spans are children of their draft span",
          all(by_id[s["parent_span_id"]]["name"] == "draft" for s in model_spans))
    check("retry recorded as a separate span",
          sum(1 for s in spans if s["name"] == "draft") == 2)
    err = [s for s in spans if s["name"] == "boom"]
    check("an exception is recorded as an error span, not swallowed",
          err and err[0]["status"] == "error"
          and err[0]["attributes"].get("error.type") == "ValueError")
    check("token totals add up from the spans",
          t["totals"]["input_tokens"] == 150 and t["totals"]["output_tokens"] == 33)
    check("every span has a duration",
          all("duration_ms" in s for s in spans))

    # The control-graph hook: off = nothing recorded, on = spans appear.
    files_before = set(store.glob("*.jsonl"))
    out = cg._traced("intake", cg.intake)(
        {"ticket": "Where is ORD-1042?"})
    check("recorder off: node behaves exactly as before",
          out["order_ids"] == ["ORD-1042"] and cg.TRACER is None)
    tr2 = tracing.Tracer(case_id="hook", run_name="hook run", store_dir=store)
    cg.TRACER = tr2
    try:
        out = cg._traced("intake", cg.intake)(
            {"ticket": "Where is ORD-1042?"})
    finally:
        cg.TRACER = None
    path2 = tr2.finish(outcome="completed")
    t2 = tracing.read_trace(path2)
    intake_spans = [s for s in t2["spans"] if s["name"] == "intake"]
    check("recorder on: the node leaves a span with its governance attrs",
          len(intake_spans) == 1
          and intake_spans[0]["attributes"].get("supportdesk.case_type")
          == "status_inquiry")
    check("no stray trace files from the off state",
          set(store.glob("*.jsonl")) == files_before | {path, path2})

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
