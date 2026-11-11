# search_help_center — examples

One tool, one business activity: finding the policy that answers a question.

Since B5 the tool runs real retrieval over the corpus in `corpus/`:
both nets (keyword + meaning) search one-idea chunks, and the results
come back as chunks **with their chunk ids**, so every fact the agent
states can cite the chunk it came from — and the citation checker
(`retrieval.check_claim`) can audit the claim against that chunk.

## Good calls

**Call:** `search_help_center(query="refund for a package that never arrived")`
**Returns:** chunks led by `late-or-lost-package/c1` (7+ days past ETA, or tracking unmoved for 5 days → customer's choice of full refund or free reshipment; do not promise a new date).

**Call:** `search_help_center(query="how long does a refund take")`
**Returns:** chunks led by `refund-timing/c1` — "Approved refunds go back to the original payment method within 5 to 7 business days." Cite it as `refund-timing/c1`.

**Call:** `search_help_center(query="can I swap this for a different size")`
**Returns:** chunks led by `exchanges/c1` (a different size or color of the same product, within 30 days of delivery, unused, original packaging).

## Bad / empty calls — and what the agent reads back

**Call:** `search_help_center(query="")`
**Returns:** `Error: query is required and was missing or empty. Say what you are looking for in the customer's terms, e.g. 'refund for a package that never arrived'.`

**Call:** `search_help_center(query="gift wrapping options")` *(no policy exists)*
**Returns:** `No help-center article matched that query. The help center has no stated policy on this topic - do not invent one. ...` — a no-match is information, not an error: it marks the edge of what the agent may claim.
