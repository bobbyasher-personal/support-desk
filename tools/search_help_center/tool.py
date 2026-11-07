"""search_help_center - one tool for one business activity: finding the
policy article that answers a question (bite B3).

STUB, named as a stub: behind this contract sits a plain keyword scan of
three seeded articles (store.search_articles). Gap to real: B5 replaces
the innards with real retrieval - chunking, embeddings, hybrid search,
checked citations. The contract (this folder's contract.json) does not
change when that happens; that is the point of having one.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from store import search_articles


def search_help_center(query=None) -> str:
    if query is None or not str(query).strip():
        return (
            "Error: query is required and was missing or empty. Say what you "
            "are looking for in the customer's terms, e.g. 'refund for a "
            "package that never arrived'."
        )
    articles = search_articles(str(query))
    if not articles:
        return (
            "No help-center article matched that query. The help center has "
            "no stated policy on this topic - do not invent one. Tell the "
            "customer a person will follow up, or ask a clarifying question."
        )
    return json.dumps({"articles": articles})
