# The Analyst — S2's companion build

A read-only deep agent that runs the weekly error-analysis pass over
Support Desk's trace store (`traces/`, written by `v1/tracing.py` in
the OpenTelemetry GenAI schema).

**Why it exists.** Traces show everything that happened; they cannot
rank what matters. The Analyst turns the recording into a work list:
read every trace, cluster the failures, count them — the biggest
category is next week's work, and its failures become S1 golden-set
cases.

**How a pass runs** (`analyst.py`, stdlib only): it prints its plan
first (a deep agent shows its plan before it acts), reads the traces
back through the same reader the eval gate uses, clusters failures
from span attributes alone (policy blocks with the gate's own
reasons, rubric failures, run errors, escalations, rejected
approvals), drafts the weekly one-pager into `reports/` (runs,
outcomes, tokens, cost per resolved ticket, categories biggest-first),
and updates the failure-knowledge wiki in `wiki/` — one page per
cluster, a passes table per page, so last week's claims are checked
against this week's traces and a stale claim shows as a changed
number. The Analyst is the wiki's single writer.

**Read-only by construction.** The Analyst imports the trace reader
and the standard library — nothing that can write to the product.
Its only writes land inside `analyst/`. A wrong Analyst can mislead
a report; it cannot break the product. And the report is a *claim*
until a human spot-checks it against the traces (F4) — every report
says so on its face.

**Named gap.** At current scale a pass is a single sweep. The
design's sub-agent fan-out — one sub-agent per failure cluster,
reading its cluster's traces deeply — is structured for in
`analyst.py`'s cluster functions and becomes real fan-out when the
trace volume earns it.

First pass: Nov 18, 2026, over the three S2 proof-run traces —
`reports/2026-11-18-error-analysis.md` (2 approved, 1 policy block;
cost per resolved ticket $0.0048 at list prices).
