# Support Desk — Product Brief (F3 artifact, Nov 2, 2026)

**The job.** Take a customer support ticket from arrival to a resolved reply — gather the facts from the systems of record, check the policy, draft the answer, execute the allowed actions — and own the outcome end to end. Not a step of the job; the job.

**Before / after.**
- *Before:* a support rep spends **9 minutes per ticket** hunting three systems for the facts, then writes the reply from scratch — and can still end up answering from a stale screen that says one thing while the system holds another.
- *After:* the ticket arrives with the facts attached, the policy cited, and a draft written. The rep only approves.

**Success metric.** Median human time per resolved ticket: **9 minutes → under 1 minute** (approval only). Measured from real run traces, not estimated.
Guardrails that must hold while the metric improves: the eval gate stays green on the golden set and on unseen tickets; zero customer-facing sends without approval; cost per resolved ticket measured and under its ceiling.

**Failure cost.** A confident wrong answer, or an unauthorized write, reaching the customer: a refund issued that shouldn't have been, an order state reported as fact that isn't, a policy promised that doesn't exist. In the sandbox the dollars are fake; the failure modes are graded as if they were real, because in the real version these are the failures that cost customer trust and can't be unsent.

**The approval line.**
- *Above the line — a human always sees it first:* sending any customer-facing reply; issuing or changing a refund; changing account state.
- *Below the line — the agent may act alone, always with a read-back receipt:* gathering facts, classifying and routing tickets, searching policy, writing drafts (a draft is not a send), internal notes.

**The exam.** A golden set of tickets with known-good outcomes (17 cases today) that grades end state, trajectory, and citation correctness — green before any milestone counts as done, and the judge of every later change, including the agent's own proposals.

**Scope notes.** The agent acts only with the signed-in user's permissions. Sandbox data throughout; the real version of this brief points the same system at a real helpdesk, where PII handling and compliance duties join the approval line — that gap is named, not hidden.
