"""create_draft_reply - one tool for one business activity: saving the
finished reply draft (bite B3).

Saving is a WRITE, so this tool is careful about the line (F3): a draft
is below the approval line - the agent may save drafts alone - but a
draft is not a send. Every saved draft lands in the store with status
"awaiting human approval"; the send itself does not exist as a tool
until B4 builds the approval gate.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from store import add_draft


def create_draft_reply(ticket_ref=None, draft_text=None, revision_of=None) -> str:
    if ticket_ref is None or not str(ticket_ref).strip():
        return (
            "Error: ticket_ref is required - say what this draft answers, "
            "e.g. 'ticket about ORD-1042'."
        )
    if draft_text is None or not str(draft_text).strip():
        return (
            "Error: draft_text was empty - an empty draft cannot be saved. "
            "Write the complete reply first, then save it."
        )
    record = add_draft(str(ticket_ref), str(draft_text), revision_of=revision_of)
    return json.dumps(
        {
            "draft_id": record["draft_id"],
            "status": record["status"],
            "note": "Draft saved. It has NOT been sent - a human approves every reply before sending.",
        }
    )
