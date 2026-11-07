# create_draft_reply — examples

One tool, one business activity: saving the finished reply draft. Saving is not sending — every draft waits for a human's approval (the F3 line).

## Good calls

**Call:** `create_draft_reply(ticket_ref="ticket about ORD-1042", draft_text="Thank you for your patience...")`
**Returns:** `{"draft_id": "DRAFT-0001", "status": "awaiting human approval", "note": "Draft saved. It has NOT been sent - a human approves every reply before sending."}`

**Call (a revision, e.g. after the reflection pass):** `create_draft_reply(ticket_ref="ticket about ORD-1042", draft_text="...", revision_of="DRAFT-0001")`
**Returns:** a new draft id, with the revision link recorded in the store.

## Bad calls — and what the agent reads back

**Call:** `create_draft_reply(ticket_ref="ticket about ORD-1042", draft_text="")`
**Returns:** `Error: draft_text was empty - an empty draft cannot be saved. Write the complete reply first, then save it.`

**Call:** `create_draft_reply(draft_text="...")` *(no ticket_ref)*
**Returns:** `Error: ticket_ref is required - say what this draft answers, e.g. 'ticket about ORD-1042'.`
