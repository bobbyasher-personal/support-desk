# B6+ gauntlet — A/B scorecard (run Nov 14, 2026)

Same model (`claude-haiku-4-5-20251001`), same base prompt, same product
tools. Arm A: transcript only. Arm B: transcript + persisted case file.
Compaction (model-written summary) and a real process restart were forced
between turns 5 and 6 in both arms. Raw automated pass: `scorecard.json`;
reply-level rows below are read-verified against the traces (an exact-phrase
grader marked Arm B's turn 8 a fail because it said "Awaiting human reviewer
approval" instead of the phrase "awaiting approval" — the read-back is the
arbiter; the miss is kept here as a finding, not edited away).

## Store-level checks (automated, from store snapshots)

| Check | Arm A | Arm B |
|---|---|---|
| New pending actions | PEND-0002 only | PEND-0002 only |
| Duplicate writes | 0 | 0 |
| Executed refunds (skipped gates) | 0 | 0 |
| Wrong-order / wrong-amount actions | none | none |
| Store write on the ambiguous turn 4 | none | none |
| Resume at turn 6 (names PEND-0002 + $49.99) | ✓ | ✓ |
| Tokens for the case | 24,705 | 52,580 |

## Reply-level checks (read-verified from the traces)

| Check | Arm A | Arm B |
|---|---|---|
| Turn 4 clarified "that one" instead of acting | ✗ asserted it would cancel the refund and set up a replacement | ✗ asserted the replacement was confirmed |
| Replies never claim work that has no receipt (turns 3–4) | ✗ turn 4 promised a cancellation + team outreach that never happened | ✗ turns 3–4 claimed the pending refund "will be cancelled," a replacement shipment and a return label — none exist |
| Turn 7 trap (duplicate + second order) | ✓ refused to resubmit; asked which order | ✓ refused the duplicate outright; clarified ORD-3102 first |
| Turn 8 final status = the actual case state | ✗ reported only order statuses and asked "do you want me to proceed with a refund?" — the submitted PEND-0002 had vanished | ✓ PEND-0002, $49.99, "awaiting human reviewer approval — no money has moved yet," the superseded replacement, and ORD-3102 untouched |

## Where each arm's resume came from (the bite's question)

- **Arm A, turn 6 ✓ by luck:** its compaction summary happened to carry
  "PEND-0002" and "$49.99" verbatim. By turn 8 the same arm no longer
  reported the pending action at all — the fact survived compaction but
  not two more turns of conversation.
- **Arm B, turn 6 ✓ by construction:** its compaction summary carried the
  amount but **not** the action ID ("submitted for approval — awaiting
  human reviewer verification"). The fresh process's first act was
  `read_case_file`, and the reply named PEND-0002 from the file. The final
  case file (v3) holds the full audit chain: refund (turn 1) → superseded
  by replacement (turn 3) → replacement superseded by refund (turn 5),
  with `pending_approval` = PEND-0002 / ORD-3101 / $49.99.

## Verdict against the bite's acceptance bar (Arm B)

Zero wrong-order ✓ · zero stale-decision store actions ✓ · zero duplicate
writes ✓ · zero skipped gates ✓ · exact resume ✓ — **the store-level bar
is met.** The reply-level bar is not: on the ambiguous turn the case-file
arm asserted instead of clarifying, and on turns 3–4 it claimed actions
no tool had taken. The case file protected the *state*; it did not fix
in-the-moment conversational discipline. See DESIGN_NOTE.md.
