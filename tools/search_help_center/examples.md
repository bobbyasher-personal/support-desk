# search_help_center — examples

One tool, one business activity: finding the policy that answers a question.

## Good calls

**Call:** `search_help_center(query="refund for a package that never arrived")`
**Returns:** the "Late or lost packages" article (7+ days past ETA, or tracking unmoved for 5 days → customer's choice of full refund or free reshipment; do not promise a new date).

**Call:** `search_help_center(query="how long does a refund take")`
**Returns:** the "How long refunds take" article (original payment method, 5–7 business days).

## Bad / empty calls — and what the agent reads back

**Call:** `search_help_center(query="")`
**Returns:** `Error: query is required and was missing or empty. Say what you are looking for in the customer's terms, e.g. 'refund for a package that never arrived'.`

**Call:** `search_help_center(query="gift wrapping options")` *(no article exists)*
**Returns:** `No help-center article matched that query. The help center has no stated policy on this topic - do not invent one. ...` — a no-match is information, not an error: it marks the edge of what the agent may claim.
