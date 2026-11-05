#!/usr/bin/env python3
"""Support Desk v0 - the bare-hands agent (bite B1).

One file, standard library only, NO framework. The whole agent is the
while-loop in run_agent():

    put the goal + situation on the desk -> ask the model "next move?"
    -> if it names a tool, run the tool and put the result back on the desk
    -> repeat, until the model says "done", the step budget runs out,
       or a rule fires.

The model call is a raw HTTPS POST to the Anthropic Messages API. The API
key is never in this file: the Muse connector (custom.anthropic) swaps in
the real credential on the way out, via the surrogate helper.

STUBS, named as stubs (repo rule: real over toy, stubs labelled):
- get_order_status reads a tiny canned dict below, not a real system of
  record. Gap to real: B3 turns tools into contract folders over a real
  local store; S5 serves them over MCP.
- The reply this produces is a DRAFT only. There is no send tool in v0,
  on purpose: sending sits above the approval line (F3) and the approval
  gate arrives at B4.
"""

import json
import sys
import urllib.request

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import add_surrogate_to_request, read_json_response

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"  # small + cheap on purpose (model-to-task matching)
MAX_STEPS = 6  # the step budget: the loop may take at most this many turns

# ---------------------------------------------------------------------------
# The stub system of record: canned orders. "Truth" lives here (F4) - the
# model is not allowed to state an order fact that did not come from here.
# ---------------------------------------------------------------------------
ORDERS = {
    "ORD-1042": {
        "item": "wireless earbuds",
        "status": "in transit - delayed at the regional hub",
        "ordered": "2026-10-26",
        "eta": "2026-11-07",
        "last_scan": "2026-11-03, Chicago hub",
    },
    "ORD-2077": {
        "item": "standing desk mat",
        "status": "delivered",
        "ordered": "2026-10-20",
        "eta": "2026-10-27",
        "last_scan": "2026-10-27, left at front door",
    },
}


def get_order_status(order_id: str) -> str:
    """The one stub tool: look up an order in the canned store."""
    order = ORDERS.get(order_id)
    if order is None:
        # An error written for the model to read: what went wrong + what to try.
        return (
            f"Error: no order found with id '{order_id}'. "
            "Order ids look like ORD-1234. If the customer gave a different "
            "kind of number, ask them for the order id on their confirmation email."
        )
    return json.dumps({"order_id": order_id, **order})


# The tool's contract, in the shape the API expects: name in business words,
# what it does, and the exact input it takes. (B3 grows this into a full
# contract folder; this is the seed of it.)
TOOLS = [
    {
        "name": "get_order_status",
        "description": (
            "Look up the current status of one customer order. "
            "Returns the item, status, order date, ETA and last scan, "
            "or an error if the order id is unknown."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The order id, e.g. ORD-1042",
                }
            },
            "required": ["order_id"],
        },
    }
]

SYSTEM_PROMPT = """You are the agent for Support Desk, a customer support system.
Your job: take the ticket below and work it to a resolved DRAFT reply.

Rules:
- Never invent facts. Order facts may only come from the get_order_status tool.
- If the ticket contains an order id, look it up before answering.
- Your final answer is a draft reply to the customer. A human approves every
  reply before it is sent; you never send anything yourself.
- When you have what you need, stop calling tools and write the draft."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect refused, verify the endpoint")


def call_model(messages):
    """One raw API call: the desk (messages) goes in, the model's next
    move comes out. This is the only place that talks to the model."""
    body = {
        "model": MODEL,
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "tools": TOOLS,
        "messages": messages,
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    request.add_header("anthropic-version", "2023-06-01")
    add_surrogate_to_request(request, "custom.anthropic", allowed_hosts=["api.anthropic.com"])
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
        return read_json_response(response)


def run_agent(ticket: str) -> str:
    """THE LOOP. Everything else in this file exists to serve these lines."""
    # The desk: it starts with just the ticket on it.
    messages = [{"role": "user", "content": f"Ticket:\n{ticket}"}]
    trace = []

    def log(line):
        trace.append(line)
        print(line)

    log(f"TICKET: {ticket}")
    for step in range(1, MAX_STEPS + 1):
        reply = call_model(messages)
        usage = reply.get("usage", {})
        log(
            f"STEP {step}: model replied "
            f"(in {usage.get('input_tokens', '?')} / out {usage.get('output_tokens', '?')} tokens, "
            f"stop_reason={reply.get('stop_reason')})"
        )
        # Whatever the model said goes onto the desk, word for word.
        messages.append({"role": "assistant", "content": reply["content"]})

        tool_calls = [b for b in reply["content"] if b.get("type") == "tool_use"]
        if not tool_calls:
            # No tool named = the model is done. Its text is the draft.
            final = "".join(b.get("text", "") for b in reply["content"] if b.get("type") == "text")
            log("DONE: model named no tool - final answer below.")
            return final

        # Run each tool it named; results go back on the desk.
        results = []
        for call in tool_calls:
            log(f"  TOOL CALL: {call['name']}({json.dumps(call['input'])})")
            if call["name"] == "get_order_status":
                result = get_order_status(call["input"].get("order_id", ""))
            else:
                result = f"Error: unknown tool '{call['name']}'."
            log(f"  TOOL RESULT: {result}")
            results.append(
                {"type": "tool_result", "tool_use_id": call["id"], "content": result}
            )
        messages.append({"role": "user", "content": results})

    log("STOPPED: step budget ran out before the model finished.")
    return "(no final answer - step budget exhausted)"


if __name__ == "__main__":
    # A messy ticket grown from golden-set t11 (all-caps, a week late) with
    # the order question from t04 - real tickets arrive like this.
    ticket = (
        "MY PACKAGE IS A WEEK LATE AND SUPPORT KEEPS IGNORING ME. "
        "THIS IS UNACCEPTABLE. My order is ORD-1042 - where is it??"
    )
    draft = run_agent(ticket)
    print("\n----- DRAFT REPLY (human approval required before any send) -----")
    print(draft)
