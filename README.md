# Support Desk — the product this track builds

A multi-agent support system that takes a customer ticket from arrival to a resolved, human-approved reply, acting on a small system of record built alongside it (tickets, orders, refunds, accounts — local store). Real writes, real consequences, inside a sandbox.

Built bite by bite through the Agent Engineering study track — plan: `~/workspace/agent-engineering/agent-engineering-study-plan.md`; progress: `~/workspace/agent-engineering/agent-study-progress.md`.

## The team (final shape)

- **Coordinator** — splits the job, routes pieces, enforces the gates.
- **Intake agent** — classifies and routes. Seed asset: the triage agent + 17-case golden set at `~/workspace/eval-harness-example/` (absorbed and grown at bite S1).
- **Research agent** — answers from a help-center/policy corpus, with checked citations.
- **Drafter agent** — writes the reply in the house voice.
- **Critic agent** — scores the draft against a rubric; loop until it clears the bar.
- **Trust layer** — acts as the signed-in user; preview before every write; human approval before anything sends; read-back receipt after every action.
- **The exam** — an eval harness (golden set + end-state and trajectory graders) gating every milestone.

## Milestones

- **M1 (bite B8):** one agent does the whole job end to end, under gates, with receipts.
- **M2 (bite S4):** the team version — kept only if it beats M1 on the product's own exam.
- **M3 (bite S6):** production-shaped service; 100-ticket batch unattended; cost per resolved ticket known.
- **M4 (bite C1):** finished — failure drills pass or carry named mitigations; eval gate green on 20 unseen tickets.

## Status

Not started. First build lands at bite B1 (bare-hands agent). Product idea can be swapped at bite F3 — the architecture and sequence stay identical.
