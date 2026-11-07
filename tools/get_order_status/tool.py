"""get_order_status - one tool for one business activity: checking an
order's status (bite B3).

The contract is contract.json, in this folder. This code enforces it:
every bad input gets an error written for the model to read - what went
wrong, what was expected, and what to do next. The tool never guesses
and never stays silent.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from store import get_order

_ORDER_ID_SHAPE = re.compile(r"^ORD-\d+$")


def get_order_status(order_id=None) -> str:
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
    order = get_order(oid)
    if order is None:
        return (
            f"Error: no order found with id '{oid}'. Ask the customer to "
            "double-check the order id on their confirmation email - a single "
            "wrong digit produces this error."
        )
    return json.dumps({"order_id": oid, **order})
