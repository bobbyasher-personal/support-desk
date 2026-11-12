# Support Desk

A multi-agent support system that takes a customer ticket from arrival to a resolved, human-approved reply — acting on a small system of record (orders, refunds, accounts) inside a sandbox. Real writes, real gates, real run traces.

**Built in public, one bite at a time.** This repo is the working artifact of a build-first agent-engineering curriculum for engineering leaders: 23 sessions, one product, no toy demos. Every capability lands as working code with the traces to prove it — and the failures stay in the record, because they're the interesting part.

## Why this exists

Agent systems are usually taught as concepts and demoed as magic. This track inverts that: bare hands before frameworks, just enough concept per session to build the next real piece, and an eval harness — the product's own exam — gating every milestone. The builder is an engineering leader learning by shipping, with an AI pair. The commit history is the course diary.

## What's built so far (bite 10 of 23, Nov 2026)

- **The loop, bare-handed** — a single-file agent (`v0/agent.py`): model + tools + look → think → act → check, with brakes enforced by code, not prompts — step budget, cost budget, a no-progress rule, a time limit — plus a reflection pass that grades each draft.
- **Tools as contracts** — one folder per business activity (`contract.json` + `tool.py` + `examples.md`): order status, policy search, draft replies, refunds. Outputs and errors are written for the model to read.
- **A trust layer** — the agent acts as the user, never as itself: every world-changing action is previewed first, submitted as a *pending action*, and executed only by a human approving out-of-band. Proof is a read-back receipt from the system of record, never the agent's claim. All file access runs through a sandbox, with a live escape test in the traces (it refused `~/.ssh` and `/etc/passwd`; the control path was allowed).
- **A research step with checked citations** — the policy corpus (5 documents, chunked into 11 citable chunks) is searched two ways at once: a keyword net (exact words and codes) and a meaning net (word-weight vectors). Answers cite chunk ids, and a checker fails any claim the cited chunk doesn't actually support — a wrong number, an uncited fact, a citation pointing at the wrong chunk.
- **Context engineering** — the loop packs the desk per step: only the tools this step can still need are offered (all four contracts cost ~829 tokens on *every* step, used or not), and when the carried history grows past a threshold it is compacted into a desk note rebuilt from structured job state — orders, cited chunks, decisions, pending actions — so a decision lives in a state field and can't be silently dropped by a summary. A long-run drill (one ticket, six asks, three orders, one buried already-refunded trap) runs with packing off and on; the first packed attempt *failed* — it looped and cost more than the raw run — and its trace, diagnosis, and fixes are kept in `v0/runs/` alongside the passing runs.
- **Tests** — 42 contract, trust-layer, retrieval, checker, and desk-packing tests, all passing (`tools/test_tools.py`). Every build's run traces live in `v0/runs/`.

Honest limitations are recorded where they were found — e.g. the meaning net's word-weight vectors nearly tied an irrelevant chunk with the right one on a real query (0.589 vs 0.597); the swap point for a neural embedding is a single function, and the gap is named rather than hidden.

## The team (final shape, assembled bite by bite)

- **Coordinator** — splits the job, routes the pieces, enforces the gates.
- **Intake agent** — classifies and routes each ticket (seeded by a 17-case golden set, grown at the evals milestone).
- **Research agent** — answers from the policy corpus, with checked citations. *(Built — see above.)*
- **Drafter agent** — writes the customer reply.
- **Critic agent** — grades the draft against a rubric before it can move.
- **Trust layer** — preview before every write, human approval before anything sends, read-back receipt after every action. *(Built — see above.)*
- **The exam** — an evaluation harness gating every milestone.

## Milestones

- **M1 (bite B8):** one agent does the whole job end to end, under gates, with receipts.
- **M2 (bite S4):** the team version — kept only if it beats M1 on the product's own exam.
- **M3 (bite S6):** production-shaped service, deployed at a live URL; a 100-ticket batch unattended; cost per resolved ticket known.
- **M4 (bite C1):** finished — failure drills pass or carry named mitigations; the eval gate green on 20 unseen tickets.

## House rules (the short version — full text in `AGENTS.md`)

Never invent facts. Approval before anything sends. Receipts, not claims. The eval gate is law. Idempotency on writes. Budgets and the no-progress rule on every loop. Bare hands before frameworks.

*All data in this repo is fictional sandbox data. No real customers, no real orders, no secrets — the model API key lives outside the repo and was never committed.*
