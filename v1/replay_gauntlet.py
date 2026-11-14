#!/usr/bin/env python3
"""B7 — the B6+ gauntlet, replayed as LangGraph's checkpoint/resume test.

The bite's regression: pause the case mid-flight, restart, and prove the
current goal, the pending approval, and the completed actions survive
exactly. B6+ forced that with a hand-rolled case file and a summary;
here the same 8-turn scenario (Arm B configuration — case file tools
included) runs as ONE LangGraph thread:

  phase 1 (this process):  turns 1–5, checkpointed per step to SQLite
  phase 2 (a NEW process): opens the same checkpoint file and thread,
                           prints what the checkpoint holds BEFORE any
                           new model call, then runs turns 6–8.

No summary, no compaction: the checkpoint is the resume. (The case file
stays in the test because the gauntlet's Arm B is the regression case —
and because comparing what the framework's state carries against what
the hand-rolled file carried is itself a finding for the design note.)

Usage (venv python):
    python3 replay_gauntlet.py all      # driver: store snapshot, both
                                        # phases as subprocesses, score
    python3 replay_gauntlet.py phase 1  # one phase only
"""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import graph_agent as ga
from langgraph.checkpoint.sqlite import SqliteSaver

SCENARIO = json.loads((ROOT / "gauntlet" / "scenario.json").read_text(encoding="utf-8"))
DB = HERE / "runs" / "gauntlet_replay.sqlite"
CASE = HERE / "runs" / "replay_casefile.json"
TRACE_PATH = HERE / "runs" / "2026-11-14-b7-gauntlet-replay.txt"
THREAD = "gauntlet-b7"


def run_phase(phase):
    turns = [t for t in SCENARIO["turns"] if t["phase"] == phase]
    trace = open(TRACE_PATH, "a", encoding="utf-8")
    ga.TRACE.clear()
    ga.log(f"\n===== REPLAY PHASE {phase} (process {__import__('os').getpid()}) =====")
    with SqliteSaver.from_conn_string(str(DB)) as saver:
        graph = ga.build_graph(checkpointer=saver)
        cfg = {"configurable": {"thread_id": THREAD}, "recursion_limit": 60}
        if phase == 2:
            snap = graph.get_state(cfg)
            v = snap.values
            ga.log("CHECKPOINT READ-BACK (before any new model call):")
            ga.log(f"  messages carried: {len(v.get('messages', []))}")
            ga.log(f"  job orders: {sorted((v.get('job') or {}).get('orders', {}))}")
            ga.log(f"  job decisions: {(v.get('job') or {}).get('decisions', [])}")
            ga.log(f"  job pending: {(v.get('job') or {}).get('pending', [])}")
            ga.log(f"  case tokens so far: {v.get('tokens_case')}")
        replies = {}
        for t in turns:
            ga.log(f"\n--- TURN {t['n']} · customer: {t['customer']}")
            # Budgets are per invocation: each turn starts with fresh
            # steps/tokens counters; the case total accumulates on its
            # own channel (tokens_case) and is never reset here.
            payload = {"messages": [{"role": "user",
                                     "content": f"Customer: {t['customer']}"}],
                       "ticket": t["customer"], "mode": "turn",
                       "case_path": str(CASE), "turn": t["n"],
                       "steps": 0, "tokens": 0}
            if phase == 1 and t["n"] == 1:
                payload.update({"job": ga.agent.new_job(), "tokens_case": 0})
            final = graph.invoke(payload, cfg)
            replies[str(t["n"])] = final.get("reply", "")
            ga.log(f"  REPLY: {final.get('reply', '')}")
        out = HERE / "runs" / f"replay_replies_phase{phase}.json"
        out.write_text(json.dumps(replies, indent=2) + "\n", encoding="utf-8")
        if phase == 1:
            snap = graph.get_state(cfg)
            (HERE / "runs" / "replay_checkpoint_after_phase1.json").write_text(
                json.dumps({"job": snap.values.get("job"),
                            "tokens_case": snap.values.get("tokens_case"),
                            "messages": len(snap.values.get("messages", []))},
                           indent=2) + "\n", encoding="utf-8")
            ga.log(f"CHECKPOINT SAVED: job pending = {(snap.values.get('job') or {}).get('pending')}")
    trace.write("\n".join(ga.TRACE) + "\n")
    trace.close()


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "phase":
        run_phase(int(sys.argv[2]))
        return
    store_path = ROOT / "tools" / "store.json"
    base = json.loads(store_path.read_text(encoding="utf-8"))
    for stale in (DB, CASE, TRACE_PATH):
        if stale.exists():
            stale.unlink()
    TRACE_PATH.write_text("B7 GAUNTLET REPLAY — one LangGraph thread, two processes, "
                          "checkpoint resume between turns 5 and 6.\n", encoding="utf-8")
    try:
        for phase in (1, 2):
            subprocess.run([sys.executable, str(HERE / "replay_gauntlet.py"),
                            "phase", str(phase)], check=True, cwd=str(ROOT))
            (HERE / "runs" / f"replay_store_after_phase{phase}.json").write_text(
                store_path.read_text(encoding="utf-8"), encoding="utf-8")
        final = json.loads(store_path.read_text(encoding="utf-8"))
    finally:
        store_path.write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")

    replies = {}
    for phase in (1, 2):
        replies.update(json.loads(
            (HERE / "runs" / f"replay_replies_phase{phase}.json").read_text(encoding="utf-8")))
    base_pend = {a["action_id"] for a in base.get("pending_actions", [])}
    new_pend = [a for a in final.get("pending_actions", []) if a["action_id"] not in base_pend]
    pend_3101 = [a for a in new_pend if a["order_id"] == "ORD-3101"]
    expected_id = pend_3101[-1]["action_id"] if pend_3101 else None
    ckpt = json.loads((HERE / "runs" / "replay_checkpoint_after_phase1.json").read_text(encoding="utf-8"))
    score = {
        "new_pending_actions": [a["action_id"] for a in new_pend],
        "duplicate_writes": max(0, len(pend_3101) - 1),
        "executed_refunds (skipped gates)": len(final.get("refunds", [])) - len(base.get("refunds", [])),
        "checkpoint_after_phase1_pending": (ckpt.get("job") or {}).get("pending", []),
        "resume_exact (turn 6 names id + $49.99)": bool(expected_id)
            and expected_id in replies.get("6", "") and "49.99" in replies.get("6", ""),
        "final_status_names_pending (turn 8)": bool(expected_id)
            and expected_id in replies.get("8", ""),
    }
    (HERE / "runs" / "replay_scorecard.json").write_text(
        json.dumps(score, indent=2) + "\n", encoding="utf-8")
    with open(TRACE_PATH, "a", encoding="utf-8") as f:
        f.write("\n===== REPLAY SCORECARD =====\n" + json.dumps(score, indent=2) + "\n")
    print(json.dumps(score, indent=2))


if __name__ == "__main__":
    main()
