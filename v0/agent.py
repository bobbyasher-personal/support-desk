#!/usr/bin/env python3
"""Support Desk v0 - the bare-hands agent (bites B1 + B2).

One file, standard library only, NO framework. The whole agent is the
while-loop in run_agent():

    put the goal + situation on the desk -> ask the model "next move?"
    -> if it names a tool, run the tool and put the result back on the desk
    -> repeat, until the model says "done", a budget runs out,
       or a brake fires.

B1 built the loop. B2 gives it its shapes and brakes:
- The loop's shape is ReAct (think one step, act, look, think again),
  named here so later bites can change it on purpose.
- Four brakes, checked by the LOOP (not the model - brakes are code,
  not requests): a step budget, a cost budget (total tokens, with the
  dollar estimate shown), a no-progress rule (same tool + same inputs
  twice in a row = stop and escalate, BEFORE the repeat runs - the
  duplicate never happens), and a time limit.
- A reflection pass at the end: the finished draft is graded against a
  checklist by a second model call, and revised once if it fails. This
  is the seed of the critic agent (S4).

The model call is a raw HTTPS POST to the Anthropic Messages API. The API
key is never in this file: the Muse connector (custom.anthropic) swaps in
the real credential on the way out, via the surrogate helper.

STUBS, named as stubs (repo rule: real over toy, stubs labelled):
- get_order_status reads a tiny canned dict below, not a real system of
  record. Gap to real: B3 turns tools into contract folders over a real
  local store; S5 serves them over MCP.
- The reflection "critic" is the same small model wearing a checklist,
  not a separate agent. Gap to real: S4's critic is its own agent with
  its own desk and rubric.
- The reply this produces is a DRAFT only. There is no send tool in v0,
  on purpose: sending sits above the approval line (F3) and the approval
  gate arrives at B4.
- `brake-test` mode swaps the model for a scripted fake that always asks
  for the same tool call, so the no-progress brake can be tested
  deterministically, for free. It tests the brake (loop code), not the
  model - the standard way to test a guardrail.

Run modes:
    python3 agent.py              the B1 ticket (ORD-1042), for real
    python3 agent.py not-found    a real ticket with an unknown order id
    python3 agent.py brake-test   the no-progress brake, scripted, no API
"""

import json
import sys
import time
import urllib.request

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import add_surrogate_to_request, read_json_response

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"  # small + cheap on purpose (model-to-task matching)

# --- The brakes (B2). Numbers the loop enforces; the model cannot move them.
MAX_STEPS = 6        # step budget: at most this many turns around the loop
MAX_TOKENS = 6000    # cost budget: total tokens (in + out) for the whole run
MAX_SECONDS = 120    # time limit: wall-clock seconds for the whole run
# Haiku 4.5 list prices, used only to show the run's dollar estimate.
INPUT_USD_PER_MTOK = 1.00
OUTPUT_USD_PER_MTOK = 5.00

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

# The reflection pass (B2): a second call whose only job is grading the
# draft against this checklist. Same model, different hat - the seed of
# the critic agent (S4).
REFLECT_SYSTEM = """You are the quality checker for Support Desk.
You are given a customer ticket and a DRAFT reply written by another agent.
Grade the draft against this checklist:
1. Every order fact in the draft (item, status, dates, ETA, locations) came
   from the tool results the agent was given - nothing invented, nothing
   embellished.
2. It answers the customer's actual question.
3. Tone: calm and helpful; owns the problem where the company is at fault.
4. It makes no promise the company has not made (no new dates, refunds, or
   discounts that were not in the tool results).

If the draft passes all four, reply with exactly: PASS
If anything fails, reply with: REVISE:
followed by the complete corrected draft, keeping everything that was right."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect refused, verify the endpoint")


def call_model(messages, system=SYSTEM_PROMPT, tools=TOOLS):
    """One raw API call: the desk (messages) goes in, the model's next
    move comes out. This is the only place that talks to the model."""
    body = {
        "model": MODEL,
        "max_tokens": 1024,
        "system": system,
        "messages": messages,
    }
    if tools:
        body["tools"] = tools
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


def tokens_of(reply):
    usage = reply.get("usage", {})
    return usage.get("input_tokens", 0), usage.get("output_tokens", 0)


def reflect_on_draft(ticket: str, draft: str, evidence, log):
    """The reflection pass: grade the draft, revise it once if it fails.
    Returns (final_draft, input_tokens, output_tokens).

    The checker gets the EVIDENCE (the tool results) on its desk, not
    just the draft: without the facts, "did the draft invent anything?"
    is unanswerable - the first version of this function learned that
    the hard way, when the checker honestly refused to grade."""
    messages = [
        {
            "role": "user",
            "content": (
                f"Ticket:\n{ticket}\n\n"
                f"TOOL RESULTS THE AGENT WAS GIVEN:\n"
                + ("\n".join(evidence) if evidence else "(the agent used no tools)")
                + f"\n\nDRAFT REPLY:\n{draft}"
            ),
        }
    ]
    reply = call_model(messages, system=REFLECT_SYSTEM, tools=None)
    in_t, out_t = tokens_of(reply)
    text = "".join(
        b.get("text", "") for b in reply["content"] if b.get("type") == "text"
    ).strip()
    if text.startswith("REVISE:"):
        revised = text[len("REVISE:"):].strip()
        log("REFLECT: draft FAILED the checklist - revised draft below.")
        return revised, in_t, out_t
    if text.startswith("PASS"):
        log("REFLECT: draft PASSED the checklist unchanged.")
        return draft, in_t, out_t
    # A grader that answers off-script is itself a finding: keep the
    # original draft and say so in the trace rather than guessing.
    log(f"REFLECT: checker replied off-script ({text[:60]!r}...) - keeping the original draft.")
    return draft, in_t, out_t


def run_agent(ticket: str) -> str:
    """THE LOOP (ReAct shape). Everything else in this file serves these
    lines - including the brakes, which are checked here, by the loop,
    never left to the model's good behaviour."""
    # The desk: it starts with just the ticket on it.
    messages = [{"role": "user", "content": f"Ticket:\n{ticket}"}]
    trace = []

    def log(line):
        trace.append(line)
        print(line)

    started = time.time()
    total_in = total_out = 0
    last_call_key = None  # the no-progress notebook: the last tool call that ran
    evidence = []  # every tool result, kept for the reflection pass's desk

    def totals_line():
        cost = (total_in * INPUT_USD_PER_MTOK + total_out * OUTPUT_USD_PER_MTOK) / 1_000_000
        return (
            f"RUN TOTALS: {total_in} in / {total_out} out tokens "
            f"({total_in + total_out} of {MAX_TOKENS} budget), "
            f"est. ${cost:.4f}, {time.time() - started:.1f}s elapsed"
        )

    log(f"TICKET: {ticket}")
    for step in range(1, MAX_STEPS + 1):
        # Brake: time limit, checked before each new turn.
        if time.time() - started > MAX_SECONDS:
            log(f"BRAKE: time limit ({MAX_SECONDS}s) hit at step {step}. Escalating.")
            log(totals_line())
            return "(escalated to a human - time-limit brake fired)"

        reply = call_model(messages)
        in_t, out_t = tokens_of(reply)
        total_in += in_t
        total_out += out_t
        log(
            f"STEP {step}: model replied "
            f"(in {in_t} / out {out_t} tokens, stop_reason={reply.get('stop_reason')})"
        )

        # Brake: cost budget, checked the moment the meter moves.
        if total_in + total_out > MAX_TOKENS:
            log(f"BRAKE: cost budget ({MAX_TOKENS} tokens) exceeded at step {step}. Escalating.")
            log(totals_line())
            return "(escalated to a human - cost-budget brake fired)"

        # Whatever the model said goes onto the desk, word for word.
        messages.append({"role": "assistant", "content": reply["content"]})

        tool_calls = [b for b in reply["content"] if b.get("type") == "tool_use"]
        if not tool_calls:
            # No tool named = the model is done. Its text is the draft -
            # which then goes through the reflection pass before it
            # counts as the run's answer.
            draft = "".join(b.get("text", "") for b in reply["content"] if b.get("type") == "text")
            log("DONE: model named no tool - draft written. Running the reflection pass.")
            draft, r_in, r_out = reflect_on_draft(ticket, draft, evidence, log)
            total_in += r_in
            total_out += r_out
            log(totals_line())
            return draft

        # Run each tool it named; results go back on the desk.
        results = []
        for call in tool_calls:
            call_key = (call["name"], json.dumps(call["input"], sort_keys=True))
            # Brake: the no-progress rule. Same tool + same inputs as the
            # call that just ran = the loop is stuck, not working. Stop
            # BEFORE running it again - the repeat (and any duplicate it
            # would cause) never happens.
            if call_key == last_call_key:
                log(
                    f"BRAKE: no-progress rule - {call['name']}({json.dumps(call['input'])}) "
                    "is identical to the previous call. Stopping and escalating."
                )
                log(totals_line())
                return (
                    "(escalated to a human - no-progress brake fired: the agent "
                    f"tried to call {call['name']} twice in a row with identical inputs)"
                )
            log(f"  TOOL CALL: {call['name']}({json.dumps(call['input'])})")
            if call["name"] == "get_order_status":
                result = get_order_status(call["input"].get("order_id", ""))
            else:
                result = f"Error: unknown tool '{call['name']}'."
            last_call_key = call_key
            evidence.append(result)
            log(f"  TOOL RESULT: {result}")
            results.append(
                {"type": "tool_result", "tool_use_id": call["id"], "content": result}
            )
        messages.append({"role": "user", "content": results})

    # The step budget is the brake of last resort.
    log(f"BRAKE: step budget ({MAX_STEPS} steps) ran out before the model finished. Escalating.")
    log(totals_line())
    return "(escalated to a human - step-budget brake fired)"


def fake_model(messages):
    """A scripted stand-in brain for the brake test: whatever is on the
    desk, it asks for the same tool call again. A real stuck loop, minus
    the API bill - used to prove the no-progress brake fires."""
    return {
        "content": [
            {
                "type": "tool_use",
                "id": "fake-call",
                "name": "get_order_status",
                "input": {"order_id": "ORD-1042"},
            }
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
    if mode == "brake-test":
        call_model = fake_model  # the brake is loop code; test it with a fake brain
        ticket = "Where is my order ORD-1042?"
    elif mode == "not-found":
        ticket = (
            "Hi, my order ORD-9999 was supposed to arrive two weeks ago "
            "and there's still nothing. Can you check where it is?"
        )
    else:
        # A messy ticket grown from golden-set t11 (all-caps, a week late)
        # with the order question from t04 - real tickets arrive like this.
        ticket = (
            "MY PACKAGE IS A WEEK LATE AND SUPPORT KEEPS IGNORING ME. "
            "THIS IS UNACCEPTABLE. My order is ORD-1042 - where is it??"
        )
    draft = run_agent(ticket)
    print("\n----- RESULT (drafts need human approval before any send) -----")
    print(draft)
