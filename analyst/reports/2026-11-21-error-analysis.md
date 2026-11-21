# Error analysis — pass of 2026-11-21

Traces read: **3** · Outcomes: approved 2, escalated 1
Model tokens across all runs: **6,733** · estimated cost $0.0095 (list prices, $1.0/$5.0 per MTok in/out)
Resolved (approved) tickets: **2** · cost per resolved ticket: **$0.0048**

## Failure categories (biggest first — the biggest is next week's work)

- **policy_block** — 1 run(s). Policy blocks — the policy gate stopped the run before any draft
  - cause (Three Gulfs): **— (gate working as designed)** — fix route: not itself a failure. A RISING count is a comprehension signal: customers asking for things the policy does not cover — read those traces first
  - cg3 (trace d45e458c): ORD-2077: already refunded (REF-0001, $44.99) - a second refund is refused

## Runs

- cg1 · trace ff14da6b · outcome approved · 3 model calls · clean
- cg2 · trace 290102a3 · outcome approved · 3 model calls · clean
- cg3 · trace d45e458c · outcome escalated · 0 model calls · policy_block

_The Analyst's report is a claim until a human spot-checks it against the traces (F4)._
