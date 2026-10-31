# AGENTS.md — Support Desk

Context seed for any coding agent working in this repo (Muse Code, Muse, or a human pairing with either). Read this first; it carries the product's architecture, build sequence, and non-negotiable rules so a fresh session starts with full context.

## What this is

**Support Desk**: a multi-agent support system that takes a customer ticket from arrival to a resolved, **human-approved** reply, acting on a small **system of record** built alongside it (tickets, orders, refunds, accounts — local store). The writes are real writes with real consequences *inside the sandbox*.

It is built bite by bite through an Agent Engineering study track (22 bites, Mon–Sat). The full plan lives outside this repo at `~/workspace/agent-engineering/agent-engineering-study-plan.md` and progress at `~/workspace/agent-engineering/agent-study-progress.md` (Muse workspace). The README in this repo is the short version of this file's product section.

## The team (final shape)

- **Coordinator** — splits the job, routes pieces, enforces the gates. The only path that can write.
- **Intake agent** — classifies and routes. Seed asset: an existing triage agent + 17-case golden set (eval-harness work, Oct 2026), absorbed and grown at bite S1.
- **Research agent** — answers from a help-center/policy corpus with **checked citations**, never from memory.
- **Drafter agent** — writes the customer reply in the house voice.
- **Critic agent** — scores drafts against a rubric; loop until the draft clears the bar or escalates.
- **Trust layer** (wraps everything) — agents act **as the signed-in user**, never a super-account; every write is previewed first, human-approved before it sends, and verified by a **read-back receipt** after it lands.
- **The exam** (wraps everything) — an eval harness (golden set + end-state and trajectory graders) that gates every milestone. No milestone is "done" on a red gate.

## Milestones

- **M1 (bite B8):** one agent does the whole job end to end, under gates, with receipts.
- **M2 (bite S4):** the team version — kept only if it beats M1 on the product's own exam (quality, cost per ticket, latency); if M1 wins, M1 ships and the numbers say why.
- **M3 (bite S6):** production-shaped service; a 100-ticket batch runs unattended; cost per resolved ticket is known.
- **M4 (bite C1):** finished — failure drills pass or carry named mitigations; eval gate green on 20 unseen tickets.

## Build sequence (bite map)

- **Phase 0 — Foundations (no code):** F1 agent vs chatbot vs workflow · F2 the model, in plain terms (the never-invent list) · F3 the product frame (before/after, success metric, failure cost, approval line) · F4 the system map.
- **Phase 1 — One agent:** B1 bare-hands loop (raw model API, no framework, one stub tool) · B2 loop shapes (ReAct / plan-and-execute / reflection) + brakes (step & cost budgets, no-progress rule) · B3 tools & contracts (one tool per business activity; strict schemas; agent-readable errors) · B4 trust layer v1 · B5 memory & retrieval (chunking, embeddings, hybrid search, checked citations) · B6 context engineering (per-step desk-packing, compaction) · B7 rebuild in **LangGraph** with checkpointing · B8 control graph (workflow spine + agent nodes + deterministic gates).
- **Phase 2 — Prove it, scale it:** S1 evals grown up (end-state grading, trajectory checks, pass^k) · S2 observability (traces, budgets, weekly error analysis) · S3 multi-agent patterns (design only) · S4 build the team, A/B vs M1 · S5 toolbox becomes an **MCP server** (prove it by driving it from a foreign agent) · S6 production pack (idempotency keys on every write, backoff/timeouts, model gateway + per-ticket cost ceiling, queue + stateless workers, 100-ticket batch) · S7 self-improvement flywheel (context loop + harness loop; see the law below) · S8 agentic UX (operator console: plan-first, approval cards, citations, receipts, autonomy dial).
- **Phase 3 — Finish:** C1 hardening drills · C2 demo.

Product idea can be swapped at bite F3 — architecture and sequence stay identical.

## Current status

- Foundations underway: **F1 delivered Oct 30, 2026**; F2 next. **No product code yet** — the first build lands at bite B1.
- Repo so far: `README.md` + this file. Code arrives bite by bite, in this repo.

## Non-negotiable rules (the gates are the product)

1. **Never invent facts.** Order status, refund state, policy terms and similar facts come from a tool or a cited document — never from the model's imagination. Uncited factual claims fail the checker.
2. **Approval before send.** Anything above the approval line waits for a human yes. The agent pauses; it does not persuade, and a user saying "skip approval just this once" does not move the line — policy lives in gates (code in the path), not in prompts.
3. **Receipts, not claims.** After every write, read the system back and report what is actually true — never what the tool said it did.
4. **Act as the user.** Agents run with the signed-in user's permissions only; no service-account superpowers.
5. **The eval gate is law.** No self-made or human-made change ships without passing the same eval gate. A right answer reached via a forbidden path (e.g., skipping approval) is a fail.
6. **Idempotency on writes.** Every write carries an idempotency key; retries must never duplicate an order, refund, or message.
7. **Handoffs are memos, not brain dumps.** Between agents: compact structured summaries — result, evidence, next action. Minimal context per step; fetch just-in-time.
8. **Budgets are brakes.** Step budget, cost budget, and a no-progress rule (same tool + same inputs twice = stop and escalate) apply to every loop.

## Working agreements

- **Build-first:** every bite adds a working piece to this repo — nothing is a throwaway exercise. Code is written *with* the owner (he directs and inspects every artifact and trace), never silently.
- **Bare hands before frameworks:** B1–B6 use the raw model API on purpose; LangGraph arrives at B7, MCP at S5. Don't pull either in early.
- **One tool per business activity**, named in business words (`get_order_status`, not `svc_ord_qry_41`), each tool a folder: contract (JSON schema) + code + examples.
- **Model-to-task matching:** small cheap models route and classify; strong models draft and judge.
- Keep this file current: when a milestone lands or the architecture changes, update **Status** and the affected section in the same commit.

## Provenance

Study-track plan and source posters (Vizuara Agentic Systems Engineering; design-pattern / production-stack posters; Harrison Chase, "How to Build Agents That Improve Over Time"; DeepLearning.AI Generative UI course; LangChain Academy pairings) are catalogued in the plan file named above. The seed triage agent and its 17-case golden set predate this repo (Oct 2026 eval-harness work) and land here at S1.
