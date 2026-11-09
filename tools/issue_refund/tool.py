"""issue_refund - one tool for one business activity: refunding an
order (bite B4).

This is Support Desk's first tool that can change the world, so it is
built as the trust layer demands:

- PREVIEW first: preview=true returns exactly what would happen and
  changes nothing - no pending action, no refund, no store write.
- The GATE on the real call: preview=false does NOT issue the refund.
  It submits a pending action and stops. The refund only exists after
  a human approves the action out-of-band (store.approve_and_execute,
  reached from the `approve` command, never from the agent's loop).
- IDEMPOTENT: an order that already has a refund gets an error naming
  that refund, never a second one.

Validation mirrors get_order_status: garbage in gets an error written
for the model to read - what went wrong, what was expected, what to
do next.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from store import add_pending_action, find_refund_for_order, get_order

_ORDER_ID_SHAPE = re.compile(r"^ORD-\d+$")


def issue_refund(order_id=None, reason=None, preview=False) -> str:
    if order_id is None or not str(order_id).strip():
        return (
            "Error: order_id is required and was missing or empty. "
            "Order ids look like ORD-1234. Ask the customer for the order id "
            "on their confirmation email, then call this tool again."
        )
    oid = str(order_id).strip()
    if not _ORDER_ID_SHAPE.match(oid):
        hint = ""
        if oid.upper().startswith("TKT"):
            hint = " That looks like a ticket number, not an order id."
        return (
            f"Error: order_id must look like ORD-1234 (the letters ORD, a dash, "
            f"then digits). You sent '{oid}'.{hint} Ask the customer for the "
            "order id on their confirmation email."
        )
    if reason is None or not str(reason).strip():
        return (
            "Error: a reason is required - say why the refund is being "
            "issued, in a few words from the ticket, e.g. 'item arrived "
            "damaged'."
        )
    order = get_order(oid)
    if order is None:
        return (
            f"Error: no order found with id '{oid}'. Ask the customer to "
            "double-check the order id on their confirmation email - a single "
            "wrong digit produces this error."
        )
    existing = find_refund_for_order(oid)
    if existing is not None:
        return (
            f"Error: order {oid} already has a refund ({existing['refund_id']}, "
            f"${existing['amount']:.2f}, status: {existing['status']}). Refunds "
            "are issued once per order - do not submit another."
        )

    would_refund = {
        "order_id": oid,
        "item": order["item"],
        "amount": order["price"],
        "order_status_now": order["status"],
        "reason": str(reason),
    }
    if preview:
        return json.dumps(
            {
                "mode": "preview",
                "would_refund": would_refund,
                "note": (
                    "PREVIEW ONLY - nothing has changed: no refund, no pending "
                    "action. To proceed, call this tool again with preview=false "
                    "to submit the refund to the approval gate."
                ),
            }
        )
    record = add_pending_action({"type": "refund", **would_refund})
    return json.dumps(
        {
            "pending_action_id": record["action_id"],
            "status": record["status"],
            "would_refund": would_refund,
            "note": (
                "Submitted to the approval gate. The refund has NOT been "
                "issued - a human must approve this pending action first, "
                "and only the read-back receipt after approval proves it "
                "happened."
            ),
        }
    )
