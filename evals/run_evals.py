#!/usr/bin/env python3
"""S1 — golden set v2 runner.

Runs every case in cases.jsonl against the B8 control graph (the
multi-turn case runs the B7 gauntlet replay), on a SEEDED SNAPSHOT of
the store, and grades from read-backs only:

- end state: the store file after the run (new drafts / pendings /
  refunds, order statuses) — never the run's own summary;
- trajectory: did the run pause at the approval gate, what existed in
  the store at the moment of the pause (a refund already executed
  there is the forbidden path), model calls and tokens against budget.

The live store is restored byte-for-byte after every case, pass or
fail. pass^k: a case passes only if ALL k runs pass (S1's law — 4 of
5 is reliability data, not a pass).

Usage (repo venv python):
  python evals/run_evals.py [--k 1] [--only gs-01,gs-03]
Outputs: evals/runs/score-<stamp>-k<K>.json + .md (category slices).
Exit code: 0 only if every selected case passes.
"""

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "v1"))
sys.path.insert(0, str(HERE))

import control_graph as cg  # noqa: E402
from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from grading import grade, grade_gauntlet  # noqa: E402

STORE = ROOT / "tools" / "store.json"
RUNS = HERE / "runs"


def _run_ticket(graph, cfg, ticket, approval, refunds_at_start):
    """One ticket through the control graph. Returns per-ticket
    evidence; refunds_before_approval is measured from the store at
    the moment of the approval pause — the read-back, not a claim."""
    cg.MODEL_CALLS.update({"n": 0, "tokens": 0})
    ev = {"paused": False, "escalated": None, "draft_text": "",
          "refunds_before_approval": 0, "model_calls": 0,
          "model_tokens": 0, "error": None}
    try:
        result = graph.invoke({"ticket": ticket}, cfg)
        ev["paused"] = "__interrupt__" in result
        if ev["paused"]:
            mid = json.loads(STORE.read_text(encoding="utf-8"))
            ev["refunds_before_approval"] = len(mid["refunds"]) - refunds_at_start
            if approval == "approve":
                result = graph.invoke(
                    Command(resume={"approved": True, "approver": "eval"}), cfg)
            elif approval == "reject":
                result = graph.invoke(
                    Command(resume={"approved": False, "approver": "eval"}), cfg)
            # approval == "none": leave it paused at the gate.
        ev["escalated"] = result.get("escalated")
        ev["draft_text"] = result.get("draft_text") or ""
    except Exception as exc:  # a crash is evidence, not a runner failure
        ev["error"] = f"{type(exc).__name__}: {exc}"
    ev["model_calls"] = cg.MODEL_CALLS["n"]
    ev["model_tokens"] = cg.MODEL_CALLS["tokens"]
    return ev


def run_ticket_case(case, run_idx):
    base_bytes = STORE.read_text(encoding="utf-8")
    data = json.loads(base_bytes)
    for oid, order in (case.get("seed_orders") or {}).items():
        data["orders"][oid] = order
    for refund in case.get("seed_refunds") or []:
        data["refunds"].append(refund)
    for pending in case.get("seed_pending") or []:
        data["pending_actions"].append(pending)
    seeded_ids = {
        "drafts": {d["draft_id"] for d in data["drafts"]},
        "pending_actions": {a["action_id"] for a in data["pending_actions"]},
        "refunds": {r["refund_id"] for r in data["refunds"]},
    }
    db = RUNS / f"tmp-{case['id']}-{run_idx}.sqlite"
    log_buf = io.StringIO()
    agg = {"paused": False, "escalated": None, "draft_text": "",
           "refunds_before_approval": 0, "model_calls": 0,
           "model_tokens": 0, "error": None}
    started = time.time()
    try:
        STORE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        with contextlib.redirect_stdout(log_buf):
            with SqliteSaver.from_conn_string(str(db)) as saver:
                graph = cg.build_control_graph(checkpointer=saver)
                for t_idx, ticket in enumerate(case["tickets"]):
                    now = json.loads(STORE.read_text(encoding="utf-8"))
                    cfg = {"configurable": {
                               "thread_id": f"eval-{case['id']}-{run_idx}-{t_idx}"},
                           "recursion_limit": 40}
                    ev = _run_ticket(graph, cfg, ticket,
                                     case.get("approval", "approve"),
                                     len(now["refunds"]))
                    agg["paused"] = ev["paused"]
                    agg["escalated"] = ev["escalated"]
                    agg["draft_text"] = ev["draft_text"] or agg["draft_text"]
                    agg["refunds_before_approval"] += ev["refunds_before_approval"]
                    agg["model_calls"] += ev["model_calls"]
                    agg["model_tokens"] += ev["model_tokens"]
                    if ev["error"]:
                        agg["error"] = ev["error"]
                        break
        final = json.loads(STORE.read_text(encoding="utf-8"))
    finally:
        STORE.write_text(base_bytes, encoding="utf-8")
        if db.exists():
            db.unlink()
    (RUNS / "logs").mkdir(parents=True, exist_ok=True)
    (RUNS / "logs" / f"{case['id']}-run{run_idx}.log").write_text(
        log_buf.getvalue(), encoding="utf-8")
    agg["drafts_new"] = [d for d in final["drafts"]
                         if d["draft_id"] not in seeded_ids["drafts"]]
    agg["pendings_new"] = [a for a in final["pending_actions"]
                           if a["action_id"] not in seeded_ids["pending_actions"]]
    agg["refunds_new"] = len([r for r in final["refunds"]
                              if r["refund_id"] not in seeded_ids["refunds"]])
    agg["orders_final"] = {oid: o.get("status")
                           for oid, o in final["orders"].items()}
    agg["seconds"] = round(time.time() - started, 1)
    return agg


def run_gauntlet_case(case):
    started = time.time()
    proc = subprocess.run([sys.executable, str(ROOT / "v1" / "replay_gauntlet.py")],
                          cwd=str(ROOT), capture_output=True, text=True)
    score_path = ROOT / "v1" / "runs" / "replay_scorecard.json"
    if proc.returncode != 0 or not score_path.exists():
        return False, [f"gauntlet replay failed (exit {proc.returncode}): "
                       f"{proc.stderr.strip()[-300:]}"], {
            "seconds": round(time.time() - started, 1), "model_calls": None,
            "model_tokens": None}
    score = json.loads(score_path.read_text(encoding="utf-8"))
    passed, fails = grade_gauntlet(case, score)
    return passed, fails, {"seconds": round(time.time() - started, 1),
                           "model_calls": None, "model_tokens": None,
                           "scorecard": score}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=1,
                    help="runs per case; a case passes only if all k pass")
    ap.add_argument("--only", default="",
                    help="comma-separated case ids to run (default: all)")
    args = ap.parse_args()

    cases = [json.loads(line) for line in
             (HERE / "cases.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
    RUNS.mkdir(parents=True, exist_ok=True)

    results = []
    for case in cases:
        runs = []
        for run_idx in range(1, args.k + 1):
            if case.get("mode") == "gauntlet":
                passed, fails, meta = run_gauntlet_case(case)
            else:
                ev = run_ticket_case(case, run_idx)
                passed, fails = grade(case, ev)
                meta = {"seconds": ev["seconds"],
                        "model_calls": ev["model_calls"],
                        "model_tokens": ev["model_tokens"]}
            runs.append({"run": run_idx, "passed": passed, "fails": fails, **meta})
            print(f"{case['id']} run {run_idx}: "
                  f"{'PASS' if passed else 'FAIL'}"
                  + (f" — {'; '.join(fails)}" if fails else ""))
        case_passed = all(r["passed"] for r in runs)
        results.append({"id": case["id"], "category": case["category"],
                        "passed": case_passed, "runs": runs})
        print(f"{case['id']} ({case['category']}): "
              f"{'PASS' if case_passed else 'FAIL'} under pass^{args.k}")

    stamp = time.strftime("%Y-%m-%d-%H%M")
    total = len(results)
    passed_n = sum(1 for r in results if r["passed"])
    by_cat = {}
    for r in results:
        by_cat.setdefault(r["category"], [0, 0])
        by_cat[r["category"]][1] += 1
        by_cat[r["category"]][0] += 1 if r["passed"] else 0
    tokens = sum((run.get("model_tokens") or 0)
                 for r in results for run in r["runs"])
    payload = {"stamp": stamp, "k": args.k, "passed": passed_n,
               "total": total, "by_category": by_cat,
               "model_tokens_total": tokens, "cases": results}
    (RUNS / f"score-{stamp}-k{args.k}.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [f"# Golden set v2 — score run {stamp} (pass^{args.k})", "",
             f"**{passed_n} of {total} cases pass.** "
             f"Model tokens across all runs: {tokens:,}.", "",
             "| Category | Pass |", "|---|---|"]
    for cat in sorted(by_cat):
        p, t = by_cat[cat]
        lines.append(f"| {cat} | {p}/{t} |")
    lines += ["", "## Cases", ""]
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        lines.append(f"- **{r['id']}** ({r['category']}): {mark}")
        for run in r["runs"]:
            for fail in run["fails"]:
                lines.append(f"  - run {run['run']}: {fail}")
    (RUNS / f"score-{stamp}-k{args.k}.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nSCORE: {passed_n}/{total} under pass^{args.k} "
          f"-> evals/runs/score-{stamp}-k{args.k}.md")
    return 0 if passed_n == total else 1


if __name__ == "__main__":
    sys.exit(main())
