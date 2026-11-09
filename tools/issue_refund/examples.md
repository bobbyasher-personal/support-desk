# issue_refund — examples

One tool, one business activity: refunding an order. The first tool that changes the world, so it is gated: preview first, then the real call only *submits* — a human approves before any money moves (the B4 trust layer).

## Good calls

**Call (step 1, always first):** `issue_refund(order_id="ORD-2077", reason="item arrived damaged", preview=true)`
**Returns:** `{"mode": "preview", "would_refund": {"order_id": "ORD-2077", "item": "standing desk mat", "amount": 44.99, "order_status_now": "delivered", "reason": "item arrived damaged"}, "note": "PREVIEW ONLY - nothing has changed..."}` — the store is untouched.

**Call (step 2):** `issue_refund(order_id="ORD-2077", reason="item arrived damaged", preview=false)`
**Returns:** `{"pending_action_id": "PEND-0001", "status": "awaiting approval", "would_refund": {...}, "note": "Submitted to the approval gate. The refund has NOT been issued..."}` — the refund exists only after a human runs the approve step, which executes it and reads the store back as the receipt.

## Bad calls — and what the agent reads back

**Call:** `issue_refund(order_id="TKT-1042", reason="late")`
**Returns:** `Error: order_id must look like ORD-1234... That looks like a ticket number, not an order id...`

**Call:** `issue_refund(order_id="ORD-2077", reason="")`
**Returns:** `Error: a reason is required - say why the refund is being issued...`

**Call (after ORD-2077 was refunded):** `issue_refund(order_id="ORD-2077", reason="item arrived damaged", preview=true)`
**Returns:** `Error: order ORD-2077 already has a refund (REF-0001, $44.99, status: issued). Refunds are issued once per order - do not submit another.`
