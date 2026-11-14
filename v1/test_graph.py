#!/usr/bin/env python3
"""B7 offline checks — the graph's shape, with a scripted fake model.
No API calls: these grade the frame (routing, brakes, checkpoints),
not the brain. The brain is graded by the live regression runs.

Run with the LangGraph venv python:
    ~/workspace/agent-engineering/.venv-b7/bin/python v1/test_graph.py
"""

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import graph_agent as ga
from langgraph.checkpoint.sqlite import SqliteSaver

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"PASS {name}")
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


STORE = ga.ROOT / "tools" / "store.json"
base_store = STORE.read_text(encoding="utf-8")

real_call_model = ga.agent.call_model


def reply(content, i=100, o=20):
    return {"content": content, "usage": {"input_tokens": i, "output_tokens": o}}


def tool_use(name, args, tid="t1"):
    return {"type": "tool_use", "id": tid, "name": name, "input": args}


def scripted_fake(script):
    calls = {"n": 0}

    def fake(messages, system=None, tools=None):
        if tools is None:  # the reflection pass wears no tools
            return reply([{"type": "text", "text": "PASS"}])
        step = script[min(calls["n"], len(script) - 1)]
        calls["n"] += 1
        return step

    return fake


try:
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "ckpt.sqlite")

        # 1. Ticket mode: agent -> tools -> agent -> tools -> agent -> reflect.
        ga.agent.call_model = scripted_fake([
            reply([tool_use("get_order_status", {"order_id": "ORD-1042"})]),
            reply([tool_use("create_draft_reply",
                            {"ticket_ref": "ticket about ORD-1042",
                             "draft_text": "Your earbuds are delayed in Chicago."}, "t2")]),
            reply([{"type": "text", "text": "Done - draft saved."}]),
        ])
        with SqliteSaver.from_conn_string(db) as saver:
            graph = ga.build_graph(checkpointer=saver)
            cfg = {"configurable": {"thread_id": "test-1"}, "recursion_limit": 40}
            final = graph.invoke(
                {"messages": [{"role": "user", "content": "Ticket:\nWhere is ORD-1042?"}],
                 "ticket": "Where is ORD-1042?", "mode": "ticket",
                 "job": ga.agent.new_job(), "steps": 0, "tokens": 0}, cfg)
            check("ticket run finishes with a reply", final.get("reply") == "Done - draft saved.")
            check("draft id reached state", bool(final.get("draft_id")), str(final.get("draft_id")))
            check("job state absorbed the order",
                  "ORD-1042" in (final.get("job") or {}).get("orders", {}))
            saved_steps, saved_draft = final.get("steps"), final.get("draft_id")

            # 2. A NEW graph instance over the same checkpoint file sees
            #    the same state — the object-level shape of a resume.
            graph2 = ga.build_graph(checkpointer=saver)
            snap = graph2.get_state(cfg)
            check("checkpoint persists across graph instances",
                  snap.values.get("draft_id") == saved_draft
                  and snap.values.get("steps") == saved_steps)

        # 3. The step brake fires in the graph, not in the model: a fake
        #    that asks for the same tool forever is stopped by the node.
        ga.agent.call_model = scripted_fake([
            reply([tool_use("get_order_status", {"order_id": "ORD-1042"})]),
        ])
        with SqliteSaver.from_conn_string(db) as saver:
            graph = ga.build_graph(checkpointer=saver)
            cfg = {"configurable": {"thread_id": "test-brake"}, "recursion_limit": 60}
            final = graph.invoke(
                {"messages": [{"role": "user", "content": "Ticket:\nWhere is ORD-1042?"}],
                 "ticket": "Where is ORD-1042?", "mode": "ticket",
                 "job": ga.agent.new_job(), "steps": 0, "tokens": 0}, cfg)
            check("step brake escalates", bool(final.get("escalated")), str(final.get("escalated")))
            check("brake stopped at the budget", final.get("steps") == ga.MAX_STEPS,
                  str(final.get("steps")))

        # 4. Turn mode ends on the model's text reply — no reflection.
        ga.agent.call_model = scripted_fake([
            reply([{"type": "text", "text": "It is delayed in Chicago."}]),
        ])
        with SqliteSaver.from_conn_string(db) as saver:
            graph = ga.build_graph(checkpointer=saver)
            cfg = {"configurable": {"thread_id": "test-turn"}, "recursion_limit": 40}
            final = graph.invoke(
                {"messages": [{"role": "user", "content": "Customer: where is ORD-1042?"}],
                 "ticket": "where is ORD-1042?", "mode": "turn",
                 "job": ga.agent.new_job(), "steps": 0, "tokens": 0}, cfg)
            check("turn mode returns the reply", final.get("reply") == "It is delayed in Chicago.")
finally:
    ga.agent.call_model = real_call_model
    STORE.write_text(base_store, encoding="utf-8")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
