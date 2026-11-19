#!/usr/bin/env python3
"""S2 companion build — the Analyst: a read-only deep agent that runs
the weekly error-analysis pass over the trace store.

What it does, in order (the plan it works from is printed first —
a deep agent shows its plan before it acts):
  1. PLAN    list the trace store: how many traces, which cases.
  2. READ    read every trace back from traces/ (v1/tracing.py's
             reader — the same record the eval gate grades).
  3. SORT    cluster each run's failures from its spans: policy
             blocks (with the gate's own reasons), rubric failures,
             run errors, escalations, rejected approvals.
  4. REPORT  draft the weekly one-pager into analyst/reports/:
             runs, outcomes, tokens, cost per resolved ticket, and
             the failure categories counted — biggest first, because
             the biggest category is next week's work.
  5. REMEMBER update the failure-knowledge wiki in analyst/wiki/:
             one page per cluster, a passes table per page (each pass
             appends its count, so a stale claim shows as a changed
             number, never a silent rewrite), and a small index.

READ-ONLY BY CONSTRUCTION: this module imports the trace reader and
the standard library — nothing that can write to the product. Its
only writes land inside analyst/ (reports + wiki). A wrong Analyst
can mislead a report; it cannot break the product. Its report is a
CLAIM until a human spot-checks it against the traces (F4).

Named gap (real over toy): at tonight's scale the pass is a single
sweep. The design's sub-agent fan-out — one sub-agent per failure
cluster, each reading its cluster's traces deeply — is structured
for in the cluster functions below and becomes real fan-out when
the trace volume earns it.

    ~/workspace/agent-engineering/.venv-b7/bin/python analyst/analyst.py
"""

import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "v1"))
import tracing

# Published list prices for claude-haiku-4-5 (the product's model) —
# cost figures are estimates at these rates, labeled as such.
INPUT_PER_MTOK = 1.00
OUTPUT_PER_MTOK = 5.00

CLUSTERS = {
    "policy_block": "Policy blocks — the policy gate stopped the run before any draft",
    "rubric_fail": "Rubric failures — a draft failed the rubric gate at least once",
    "run_error": "Run errors — a span recorded an error",
    "escalated_other": "Escalations — the run escalated for a reason other than a policy block",
    "approval_rejected": "Approvals rejected — a human said no at the gate",
}


def cluster_trace(t):
    """Sort one trace into failure clusters, from its spans alone."""
    found = defaultdict(list)
    for s in t["spans"]:
        attrs = s["attributes"]
        if s["kind"] == "supportdesk.gate" and \
                attrs.get("supportdesk.gate.name") == "policy_gate" and \
                attrs.get("supportdesk.gate.verdict") == "block":
            for reason in attrs.get("supportdesk.gate.reasons") or []:
                found["policy_block"].append(reason)
        if s["kind"] == "supportdesk.gate" and \
                attrs.get("supportdesk.gate.name") == "rubric_gate" and \
                attrs.get("supportdesk.gate.verdict") == "fail":
            for reason in attrs.get("supportdesk.gate.reasons") or []:
                found["rubric_fail"].append(reason)
        if s["status"] == "error":
            found["run_error"].append(
                f"{s['name']}: {attrs.get('error.type', 'error')}")
        if s["kind"] == "supportdesk.human" and \
                attrs.get("supportdesk.approval.approved") is False:
            found["approval_rejected"].append("human rejected the draft")
    if t["outcome"] == "escalated" and "policy_block" not in found:
        found["escalated_other"].append("escalated (see trace)")
    return found


def cost_of(t):
    ti = t["totals"].get("input_tokens", 0)
    to = t["totals"].get("output_tokens", 0)
    return ti / 1e6 * INPUT_PER_MTOK + to / 1e6 * OUTPUT_PER_MTOK


def run_pass(store_dir=None, today=None):
    today = today or date.today().isoformat()
    traces = tracing.list_traces(store_dir)
    print("PLAN — error-analysis pass")
    print(f"  1. read the trace store ({len(traces)} traces)")
    cases = sorted({t['case_id'] for t in traces})
    print(f"  2. cases present: {', '.join(cases) if cases else '(none)'}")
    print("  3. cluster failures from spans; count categories")
    print("  4. draft the report; update the wiki (single writer: the Analyst)")

    per_trace = []
    cluster_counts = Counter()
    cluster_members = defaultdict(list)
    for t in traces:
        found = cluster_trace(t)
        for cluster, reasons in found.items():
            cluster_counts[cluster] += 1
            cluster_members[cluster].append(
                {"trace_id": t["trace_id"][:8], "case_id": t["case_id"],
                 "reasons": reasons})
        per_trace.append({"t": t, "found": found})

    resolved = [t for t in traces if t["outcome"] == "approved"]
    total_cost = sum(cost_of(t) for t in traces)
    total_tokens = sum(t["totals"].get("input_tokens", 0)
                       + t["totals"].get("output_tokens", 0) for t in traces)
    cpr = (sum(cost_of(t) for t in resolved) / len(resolved)) if resolved else None

    # -- the report (a claim, until a human spot-checks it) --------------
    lines = [f"# Error analysis — pass of {today}",
             "",
             f"Traces read: **{len(traces)}** · Outcomes: " +
             ", ".join(f"{k} {v}" for k, v in
                       Counter(t['outcome'] for t in traces).items()),
             f"Model tokens across all runs: **{total_tokens:,}** · "
             f"estimated cost ${total_cost:.4f} (list prices, "
             f"${INPUT_PER_MTOK}/${OUTPUT_PER_MTOK} per MTok in/out)",
             (f"Resolved (approved) tickets: **{len(resolved)}** · cost per "
              f"resolved ticket: **${cpr:.4f}**" if cpr is not None else
              "Resolved (approved) tickets: **0**"),
             "",
             "## Failure categories (biggest first — the biggest is next week's work)",
             ""]
    if cluster_counts:
        for cluster, n in cluster_counts.most_common():
            lines.append(f"- **{cluster}** — {n} run(s). {CLUSTERS[cluster]}")
            for m in cluster_members[cluster]:
                for r in m["reasons"]:
                    lines.append(f"  - {m['case_id']} (trace {m['trace_id']}): {r}")
    else:
        lines.append("- none recorded in this pass")
    lines += ["", "## Runs", ""]
    for row in per_trace:
        t = row["t"]
        cats = ", ".join(row["found"].keys()) or "clean"
        lines.append(f"- {t['case_id']} · trace {t['trace_id'][:8]} · "
                     f"outcome {t['outcome']} · {t['totals'].get('model_calls', 0)} "
                     f"model calls · {cats}")
    lines += ["", "_The Analyst's report is a claim until a human spot-checks "
              "it against the traces (F4)._", ""]
    report = "\n".join(lines)

    reports_dir = HERE / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / f"{today}-error-analysis.md"
    report_path.write_text(report, encoding="utf-8")

    # -- the wiki (persistent failure knowledge, one writer) -------------
    wiki = HERE / "wiki"
    wiki.mkdir(exist_ok=True)
    index_lines = ["# Failure-knowledge wiki — index",
                   "",
                   "One page per failure cluster. Each page carries a passes "
                   "table: a pass appends its count, so a stale claim shows "
                   "as a changed number — notes are claims, re-verified "
                   "against the traces every pass.",
                   ""]
    for cluster, blurb in CLUSTERS.items():
        page = wiki / f"{cluster}.md"
        n = cluster_counts.get(cluster, 0)
        history = []
        if page.exists():
            for line in page.read_text(encoding="utf-8").splitlines():
                if line.startswith("| 20"):
                    history.append(line)
        history.append(f"| {today} | {n} |")
        members = cluster_members.get(cluster, [])
        body = [f"# {cluster}", "", blurb + ".", "",
                "## Passes", "", "| date | runs in this cluster |",
                "|---|---|", *history, "", "## Latest pass members", ""]
        if members:
            for m in members:
                body.append(f"- {m['case_id']} (trace {m['trace_id']})")
                for r in m["reasons"]:
                    body.append(f"  - {r}")
        else:
            body.append("- none in the latest pass")
        body.append("")
        page.write_text("\n".join(body), encoding="utf-8")
        index_lines.append(f"- [{cluster}]({cluster}.md) — {n} run(s) in the "
                           f"latest pass ({today})")
    (wiki / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")

    print(f"\nREPORT: {report_path.relative_to(ROOT)}")
    print(report)
    return report_path


if __name__ == "__main__":
    run_pass()
