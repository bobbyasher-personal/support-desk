"""The local system of record for Support Desk (bite B3).

One JSON file on disk, shared by every tool: orders, help-center
articles, and saved drafts. This is where "truth" lives (F4) - tools
read and write here, and the model only ever sees what a tool returns.

STUB, named as a stub: a real system of record is a database with
transactions and concurrent access. Gap to real: S6 moves this behind
the deployed service; the tool contracts in this folder do not change
when that happens - which is the point of having contracts.
"""

import json
from pathlib import Path

STORE_PATH = Path(__file__).resolve().parent / "store.json"


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
