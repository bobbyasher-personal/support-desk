# get_order_status — examples

One tool, one business activity: checking an order's status.

## Good calls

**Call:** `get_order_status(order_id="ORD-1042")`
**Returns:** `{"order_id": "ORD-1042", "item": "wireless earbuds", "status": "in transit - delayed at the regional hub", "ordered": "2026-10-26", "eta": "2026-11-07", "last_scan": "2026-11-03, Chicago hub"}`

## Bad calls — and what the agent reads back

**Call:** `get_order_status(order_id="TKT-1042")` *(a ticket number in the order-id slot)*
**Returns:** `Error: order_id must look like ORD-1234 (the letters ORD, a dash, then digits). You sent 'TKT-1042'. That looks like a ticket number, not an order id. Ask the customer for the order id on their confirmation email.`

**Call:** `get_order_status(order_id="")`
**Returns:** `Error: order_id is required and was missing or empty. Order ids look like ORD-1234. Ask the customer for the order id on their confirmation email, then call this tool again.`

**Call:** `get_order_status(order_id="ORD-9999")` *(well-formed, doesn't exist)*
**Returns:** `Error: no order found with id 'ORD-9999'. Ask the customer to double-check the order id on their confirmation email - a single wrong digit produces this error.`
