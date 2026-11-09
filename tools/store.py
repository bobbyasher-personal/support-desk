"""The local system of record for Support Desk (bites B3 + B4).

One JSON file on disk, shared by every tool: orders, help-center
articles, saved drafts - and, since B4, the trust layer's state:
pending actions waiting at the approval gate, and issued refunds.
This is where "truth" lives (F4) - tools read and write here, and the
model only ever sees what a tool returns.

Every read and write passes through the sandbox boundary (sandbox.py):
the store file lives inside the sandbox, and the guard proves it on
every access rather than assuming it.

STUB, named as a stub: a real system of record is a database with
transactions and concurrent access. Gap to real: S6 moves this behind
the deployed service; the tool contracts in this folder do not change
when that happens - which is the point of having contracts.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sandbox

STORE_PATH = sandbox.inside("tools/store.json")


def load_store() -> dict:
    return json.loads(STORE_PATH.read_text(encoding="utf-8"))


def save_store(store: dict) -> None:
    STORE_PATH.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")


def get_order(order_id: str):
    return load_store()["orders"].get(order_id)


def search_articles(query: str):
    """Plain keyword overlap over the seeded articles. B5 replaces this
    with real retrieval (chunking, embeddings, hybrid search, checked
    citations); the tool's contract stays the same."""
    words = {w.strip(".,?!").lower() for w in query.split() if len(w) > 2}
    scored = []
    for article in load_store()["help_articles"]:
        text = f"{article['title']} {article['body']}".lower()
        hits = sum(1 for w in words if w in text)
        if hits:
            scored.append((hits, article))
    scored.sort(key=lambda pair: -pair[0])
    return [article for _, article in scored]


def add_draft(ticket_ref: str, draft_text: str, revision_of=None) -> dict:
    store = load_store()
    record = {
        "draft_id": f"DRAFT-{len(store['drafts']) + 1:04d}",
        "ticket_ref": ticket_ref,
        "draft_text": draft_text,
        "revision_of": revision_of,
        "status": "awaiting human approval",
    }
    store["drafts"].append(record)
    save_store(store)
    return record


# --- The trust layer's state (B4) -------------------------------------------
# A write above the approval line does not execute when the agent asks.
# It becomes a PENDING ACTION and waits. A human approves it out-of-band;
# only then does the change land, and the land is verified by reading
# the store back (the receipt). The functions below are the whole gate:
# there is no other path from "the agent wants a refund" to "a refund
# exists in the store".


class GateError(Exception):
    """Raised when the approval gate refuses: approving something that
    is not waiting, or executing twice. Words, not a stack trace."""


def find_refund_for_order(order_id: str):
    for refund in load_store().get("refunds", []):
        if refund["order_id"] == order_id:
            return refund
    return None


def add_pending_action(action: dict) -> dict:
    store = load_store()
    store.setdefault("pending_actions", [])
    record = {
        "action_id": f"PEND-{len(store['pending_actions']) + 1:04d}",
        **action,
        "status": "awaiting approval",
        "approved_by": None,
        "refund_id": None,
    }
    store["pending_actions"].append(record)
    save_store(store)
    return record


def get_pending_action(action_id: str):
    for record in load_store().get("pending_actions", []):
        if record["action_id"] == action_id:
            return record
    return None


def approve_and_execute(action_id: str, approver: str) -> dict:
    """The human side of the gate. Approves a waiting action and executes
    it, in one step that cannot be reached from the agent's loop.

    Idempotent by refusal: an action that is not 'awaiting approval'
    cannot be executed - approving twice raises GateError instead of
    refunding twice."""
    store = load_store()
    record = next(
        (a for a in store.get("pending_actions", []) if a["action_id"] == action_id),
        None,
    )
    if record is None:
        raise GateError(f"no pending action with id '{action_id}'")
    if record["status"] != "awaiting approval":
        raise GateError(
            f"action {action_id} is '{record['status']}', not 'awaiting "
            "approval' - it cannot be executed again"
        )
    if record["type"] != "refund":
        raise GateError(f"action {action_id} is a '{record['type']}' - not executable here")

    order = store["orders"][record["order_id"]]
    store.setdefault("refunds", [])
    refund = {
        "refund_id": f"REF-{len(store['refunds']) + 1:04d}",
        "order_id": record["order_id"],
        "amount": record["amount"],
        "reason": record["reason"],
        "approved_by": approver,
        "status": "issued",
    }
    store["refunds"].append(refund)
    order["status"] = "refunded"
    record["status"] = "executed"
    record["approved_by"] = approver
    record["refund_id"] = refund["refund_id"]
    save_store(store)
    return record
