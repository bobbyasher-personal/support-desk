"""search_help_center - one tool for one business activity: finding the
policy that answers a question (contract from B3; innards from B5).

B5 replaced the B3 keyword stub with real retrieval (see retrieval.py
in this folder): the policy corpus in corpus/ is chunked into one-idea
chunks with stable ids, indexed two ways, and searched by both nets -
keyword (exact words and codes) and meaning (word-weight vectors).
Results come back as chunks WITH their chunk ids, so the agent can
cite the exact chunk each fact came from, and the citation checker
(retrieval.check_claim) can audit the claim against that chunk.

The contract (this folder's contract.json) did not change when the
innards did - query in, matching policy text out. That is the point
of having one.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import retrieval


def search_help_center(query=None) -> str:
    if query is None or not str(query).strip():
        return (
            "Error: query is required and was missing or empty. Say what you "
            "are looking for in the customer's terms, e.g. 'refund for a "
            "package that never arrived'."
        )
    results = retrieval.search(str(query))
    if not results:
        return (
            "No help-center article matched that query. The help center has "
            "no stated policy on this topic - do not invent one. Tell the "
            "customer a person will follow up, or ask a clarifying question."
        )
    return json.dumps(
        {
            "chunks": results,
            "note": (
                "State only what these chunks state, and cite the chunk_id "
                "for every fact you use - an uncited fact fails the checker."
            ),
        }
    )
