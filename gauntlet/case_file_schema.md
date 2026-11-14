# B6+ — The case file schema (v1, approved by Bobby, Nov 14, 2026)

The case file is the agent's **versioned working state** for one customer's
case, kept *outside* the conversation transcript. The conversation is an input
stream; this file is what the system has accepted as the state of the case;
the store (`tools/store.json`) remains the truth about the world.

```json
{
  "case_id": "CASE-0001",
  "state_version": 1,
  "customer_ref": "sandbox customer",
  "current_goal": "refund | replacement | status | other",
  "current_order_id": "ORD-XXXX",
  "live_order_ids": ["ORD-XXXX"],
  "facts": [
    {"fact": "order arrived damaged", "source": "customer turn 1", "order_id": "ORD-XXXX"}
  ],
  "latest_decision": {"remedy": "refund", "order_id": "ORD-XXXX", "decided_turn": 1},
  "superseded_decisions": [
    {"remedy": "replacement", "order_id": "ORD-XXXX", "status": "superseded",
     "superseded_by_turn": 5}
  ],
  "completed_actions": [
    {"action_id": "PEND-XXXX", "kind": "refund submitted to the approval gate",
     "order_id": "ORD-XXXX", "amount": 49.99, "receipt_readback": true}
  ],
  "pending_approval": {"action_id": "PEND-XXXX", "order_id": "ORD-XXXX",
                       "amount": 49.99, "status": "awaiting approval"},
  "open_question": "Which order does 'that one' mean?",
  "updated_at_turn": 3
}
```

## Rules that ride with the schema

1. `state_version` increments on every **accepted** change — and only on an
   accepted change. An ambiguous message is not an accepted change.
2. The updated case file is written **before** the agent acts on the turn.
3. The old decision is never deleted or overwritten in place: it moves to
   `superseded_decisions`, labeled, with the turn that replaced it.
4. Exact IDs, amounts, action IDs, and statuses live in this file's fields —
   never only in a prose summary. Compaction may summarize the chatter; it
   may not be the only home of an exact fact.
5. `completed_actions` are recorded only from tool results / store read-backs
   (receipts, not claims). Final-status answers are read back from the store,
   not copied from this file.
