# B6+ design note — conversation is input; the case file is working state; the system of record is truth

**The claim this bite had to earn:** a multi-turn support agent should not
carry a case in its transcript. The transcript is an input stream — messy,
changeable, and lossy under compaction. The case lives in a persisted,
versioned **case file** (goal, current order, facts with provenance, latest
decision, superseded decisions, completed actions, pending approval, open
question). The **store** remains the truth about the world; the case file
is never a substitute for reading it back.

**The test** (`scenario.md`): one scripted, messy 8-turn conversation —
refund, order switch, remedy reversal, an ambiguous "that one," a second
reversal — run against two arms with the same model, prompt, and tools:
transcript-only (A) vs transcript + case file (B). Compaction and a real
process restart were forced mid-case in both arms. Traces, summaries, and
store snapshots: `runs/`.

## What the run showed (Nov 14, 2026; scorecard in `runs/scorecard.md`)

1. **State survived in B by construction, in A by luck — briefly.** Both
   arms resumed exactly at turn 6. A's summary happened to keep the
   pending action's ID and amount; B's summary lost the ID, and B resumed
   from the case file its fresh process read first. By turn 8, A had lost
   the pending action entirely (it asked whether to *start* a refund that
   was already submitted); B's final accounting was exact.
2. **The store-level bar was met by both arms; the reply-level bar by
   neither.** No wrong-order, duplicate, or gate-skipping writes anywhere.
   But on the ambiguous turn, *both* arms asserted a course of action
   instead of clarifying, and both claimed work no tool had done (a
   "cancelled" refund, a "shipped" replacement). B was worse on claims —
   a richer state file made its narrator *more* confident, not more
   honest. State discipline and reply discipline are separate problems;
   the second is trajectory-grader territory (S1) and a critic's job (S4).
3. **The case file costs real tokens: 52,580 vs 24,705 (2.1×).** Reading
   and fully rewriting the file on every change is the naive shape. B6's
   lesson points at the cheaper one: a harness-maintained state object
   (absorb-style, written by code from tool results) with the model
   reading a packed view — the design LangGraph's checkpointed state
   formalizes at B7.
4. **Graders need read-backs too.** The automated final-status check
   exact-phrase-matched "awaiting approval" and failed a correct reply
   ("Awaiting human reviewer approval"). Phrase graders miss true claims
   — the same failure the B5 citation checker shipped and fixed. Every
   automated verdict in the scorecard is paired with the trace so a human
   can re-grade it.

## Honest limits of this run

- One run per arm, one small model. This is evidence, not proof; S1 turns
  the scenario into a repeated eval case.
- Both arms submitted the refund at turn 1 (the prompt allows submit when
  the refund is right), so turn 5 became a re-confirmation rather than
  the first submission; the pending action existed from turn 1.
- There is no replacement tool, so the turn-3 remedy reversal was
  conversational only — which is precisely what exposed the overclaiming.
- Arm B's case file has blemishes: `completed_actions` is empty (the
  submission lives under `pending_approval`), and the model wrote an
  order ID into `case_id`/`customer_ref`. The harness's merge protected
  the superseded history anyway — by design.

## What carries forward

- **B7** replays this gauntlet as its LangGraph checkpoint/resume
  regression test: same scenario, resume on a fresh process.
- The scenario joins the S1 golden set as a multi-turn case, including
  the turn-4 clarify failure as a graded behavior — for both arms.
