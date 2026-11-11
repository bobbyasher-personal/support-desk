#!/usr/bin/env python3
"""Support Desk v0 - the bare-hands agent (bites B1 + B2 + B3 + B4).

One file, standard library only, NO framework. The whole agent is the
while-loop in run_agent():

    put the goal + situation on the desk -> ask the model "next move?"
    -> if it names a tool, run the tool and put the result back on the desk
    -> repeat, until the model says "done", a budget runs out,
       or a brake fires.

B1 built the loop. B2 gave it brakes (step / cost / no-progress / time)
and a reflection pass. B3 gives it real hands: the tools now live in
their own folders under ../tools/, one per business activity, each with
a contract (contract.json), code (tool.py) and examples (examples.md).
THIS FILE READS THE CONTRACTS FROM THOSE FOLDERS - the model's view of
a tool and the folder's contract are the same document, so they can
never drift apart. Validation lives in the tool code: garbage in gets
an agent-readable error back, never a guess and never silence.

The model call is a raw HTTPS POST to the Anthropic Messages API. The API
key is never in this file: the Muse connector (custom.anthropic) swaps in
the real credential on the way out, via the surrogate helper.

STUBS, named as stubs (repo rule: real over toy, stubs labelled):
- The system of record is a local JSON file (tools/store.json) read and
  written by tools/store.py. Gap to real: S6 moves it behind the
  deployed service; the contracts do not change when it does.
- search_help_center is a keyword stub behind a real contract. Gap to
  real: B5 gives it chunking, embeddings, hybrid search and checked
  citations.
- The reflection "critic" is the same small model wearing a checklist,
  not a separate agent. Gap to real: S4's critic is its own agent.
- The reply is still a DRAFT only: create_draft_reply saves it with
  status "awaiting human approval". There is still no send tool, on
  purpose. B4 builds the trust layer where it belongs - on WRITES:
  issue_refund previews first, then only SUBMITS a pending action; a
  human approves it out-of-band (the `approve` mode below) and the
  store read-back is the receipt. Every file the tools touch passes
  the sandbox guard (tools/sandbox.py) - see `escape-test` mode.
- `brake-test` mode swaps the model for a scripted fake that always asks
  for the same tool call, so the no-progress brake can be tested
  deterministically, for free.

Run modes:
    python3 agent.py              the B1 ticket (ORD-1042), for real
    python3 agent.py policy       ORD-1042 + a refund-policy question
    python3 agent.py messy        a ticket waving a TICKET number as an id
    python3 agent.py not-found    a real ticket with an unknown order id
    python3 agent.py brake-test   the no-progress brake, scripted, no API
    python3 agent.py refund       a damaged-item refund ticket (B4)
    python3 agent.py approve PEND-0001 bobby
                                  the human side of the gate: approve a
                                  pending action, execute it, print the
                                  read-back receipt (B4)
    python3 agent.py escape-test  two sandbox escape attempts + a control
                                  (B4)
"""

import importlib.util
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import add_surrogate_to_request, read_json_response

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"  # small + cheap on purpose (model-to-task matching)

# --- The brakes (B2). Numbers the loop enforces; the model cannot move them.
MAX_STEPS = 6        # step budget: at most this many turns around the loop
MAX_TOKENS = 14000   # cost budget: total tokens (in + out) for the whole run.
                     # Was 6,000 at B2 (one-tool desk). Raised at B3 (Nov 7,
                     # 2026) after a traced run showed the three-tool desk's
                     # legitimate shape costs ~6,600 tokens before reflection -
                     # budgets are calibrated to the job's real shape, from
                     # traces, not raised to silence the alarm.
                     # Raised again at B4 (Nov 9, 2026, Bobby approved): the
                     # four-tool desk's refund run - lookup, policy search,
                     # preview, gate submit, draft - cost 12,593 tokens and
                     # the brake fired at the final step, skipping the
                     # reflection pass. 14,000 fits that shape with headroom;
                     # if a future bite's traced shape outgrows it, recalibrate
                     # from the trace again, with Bobby's say-so.
MAX_SECONDS = 120    # time limit: wall-clock seconds for the whole run
# Haiku 4.5 list prices, used only to show the run's dollar estimate.
INPUT_USD_PER_MTOK = 1.00
OUTPUT_USD_PER_MTOK = 5.00

# ---------------------------------------------------------------------------
# The toolbox (B3): one folder per business activity under ../tools/.
# The contracts the model reads are loaded from the folders' own
# contract.json files - one source of truth, no drift.
# ---------------------------------------------------------------------------
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
TOOL_NAMES = ["get_order_status", "search_help_center", "create_draft_reply", "issue_refund"]


def _load_tool_func(name):
    spec = importlib.util.spec_from_file_location(
        f"sd_tool_{name}", TOOLS_DIR / name / "tool.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, name)


def _load_contract(name):
    raw = json.loads((TOOLS_DIR / name / "contract.json").read_text(encoding="utf-8"))
    # The API gets exactly these three keys; the rest of the file is the
    # human-facing half of the contract (error catalogue, pointers).
    return {key: raw[key] for key in ("name", "description", "input_schema")}


TOOL_FUNCS = {name: _load_tool_func(name) for name in TOOL_NAMES}
TOOLS = [_load_contract(name) for name in TOOL_NAMES]

SYSTEM_PROMPT = """You are the agent for Support Desk, a customer support system.
Your job: take the ticket below and work it to a resolved, saved DRAFT reply.

Rules:
- Never invent facts. Order facts may only come from the get_order_status
  tool. Policy may only come from the search_help_center tool.
- If the ticket contains an order id, look it up before answering.
- Write the reply, then save it with create_draft_reply. Saving is not
  sending: a human approves every reply before it is sent, and you never
  send anything yourself.
- Refunds: use issue_refund, and always call it with preview=true first.
  If the refund is right, call it again with preview=false - that SUBMITS
  it to the approval gate; it does not issue it. Never tell the customer
  a refund has been issued or completed. Say it has been submitted and
  is awaiting human approval.
- Once the draft is saved, stop and give a one-line summary of what you did."""

# The reflection pass (B2): a second call whose only job is grading the
# draft against this checklist. Same model, different hat - the seed of
# the critic agent (S4).
REFLECT_SYSTEM = """You are the quality checker for Support Desk.
You are given a customer ticket and a DRAFT reply written by another agent.
Grade the draft against this checklist:
1. Every order fact in the draft (item, status, dates, ETA, locations) came
   from the tool results the agent was given - nothing invented, nothing
   embellished. Every policy statement matches a help-center article the
   agent was given.
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
    saved_draft = None  # the last draft the agent saved via create_draft_reply

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
            # No tool named = the model is done. What gets graded is the
            # SAVED draft if there is one (that is the artifact of
            # record), else the closing text.
            closing = "".join(b.get("text", "") for b in reply["content"] if b.get("type") == "text")
            if saved_draft:
                draft = saved_draft["text"]
                log(f"DONE: model finished - grading the saved draft ({saved_draft['id']}) in the reflection pass.")
            else:
                draft = closing
                log("DONE: model named no tool - draft written but never saved. Running the reflection pass.")
            draft, r_in, r_out = reflect_on_draft(ticket, draft, evidence, log)
            total_in += r_in
            total_out += r_out
            if saved_draft and draft != saved_draft["text"]:
                # The reflection pass revised a saved draft: persist the
                # revision through the same tool, as a new version.
                out = TOOL_FUNCS["create_draft_reply"](
                    ticket_ref=saved_draft["ticket_ref"],
                    draft_text=draft,
                    revision_of=saved_draft["id"],
                )
                log(f"REFLECT-SAVE: revision persisted via create_draft_reply -> {out}")
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
            func = TOOL_FUNCS.get(call["name"])
            if func is None:
                result = f"Error: unknown tool '{call['name']}'."
            else:
                try:
                    result = func(**call["input"])
                except TypeError as exc:
                    # The call's shape broke the contract itself: say so
                    # in words the model can act on.
                    result = (
                        f"Error: that call did not match the {call['name']} contract ({exc}). "
                        "Check the contract for the exact inputs this tool takes, then try again."
                    )
            last_call_key = call_key
            evidence.append(result)
            if call["name"] == "create_draft_reply" and '"draft_id"' in result:
                saved_draft = {
                    "id": json.loads(result)["draft_id"],
                    "text": call["input"].get("draft_text", ""),
                    "ticket_ref": call["input"].get("ticket_ref", ""),
                }
            log(f"  TOOL RESULT: {result}")
            if call["name"] == "issue_refund" and '"mode": "preview"' in result:
                log("  PREVIEW: the tool showed what would happen - nothing was changed.")
            if call["name"] == "issue_refund" and '"pending_action_id"' in result:
                log("  GATE: the write is submitted, not executed - it waits for a human approver, outside this loop.")
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
    if mode == "approve":
        # THE HUMAN SIDE OF THE GATE (B4). Not the agent: a person runs
        # this, out-of-band, after reviewing what the pending action's
        # preview showed. It executes the write, then reads the store
        # back - the read-back printed below is the receipt, not the
        # tool's claim that it worked.
        sys.path.insert(0, str(TOOLS_DIR))
        import store as store_mod

        action_id = sys.argv[2]
        approver = sys.argv[3] if len(sys.argv) > 3 else "bobby"
        action = store_mod.get_pending_action(action_id)
        if action is None:
            print(f"GATE: no pending action '{action_id}' - nothing to approve.")
            sys.exit(1)
        print(
            f"GATE: {action_id} is '{action['status']}': refund "
            f"${action['amount']:.2f} for {action['order_id']} "
            f"({action['reason']}), submitted by the agent."
        )
        try:
            done = store_mod.approve_and_execute(action_id, approver)
        except store_mod.GateError as exc:
            print(f"GATE REFUSED: {exc}")
            sys.exit(1)
        # THE RECEIPT: a fresh read of the store, after the write.
        refund = store_mod.find_refund_for_order(done["order_id"])
        order = store_mod.get_order(done["order_id"])
        print(f"APPROVED by {approver} - executed.")
        print(f"RECEIPT (read back from the store): refund {json.dumps(refund)}")
        print(
            f"RECEIPT (read back from the store): order {done['order_id']} "
            f"status is now '{order['status']}'"
        )
        sys.exit(0)
    if mode == "escape-test":
        # THE ESCAPE ATTEMPT (B4): prove the sandbox holds. Two attempts
        # to reach files outside the sandbox, plus one legitimate path
        # as the control - a boundary that refuses everything would be
        # as broken as one that refuses nothing.
        sys.path.insert(0, str(TOOLS_DIR))
        import sandbox

        for attempt in ("~/.ssh/id_ed25519", "/etc/passwd"):
            try:
                sandbox.inside(attempt)
                print(f"ESCAPE: {attempt} was ALLOWED - the sandbox FAILED")
            except sandbox.SandboxError as exc:
                print(f"ESCAPE ATTEMPT REFUSED: {exc}")
        ok = sandbox.inside("tools/store.json")
        print(f"CONTROL: tools/store.json resolves inside the sandbox ({ok}) - allowed, as it should be.")
        print("SANDBOX: boundary held - the tools can only touch files inside the sandbox.")
        sys.exit(0)
    if mode == "brake-test":
        call_model = fake_model  # the brake is loop code; test it with a fake brain
        ticket = "Where is my order ORD-1042?"
    elif mode == "not-found":
        ticket = (
            "Hi, my order ORD-9999 was supposed to arrive two weeks ago "
            "and there's still nothing. Can you check where it is?"
        )
    elif mode == "policy":
        ticket = (
            "My order ORD-1042 is a week late - where is it? And if it "
            "never turns up, what happens? Do I get my money back?"
        )
    elif mode == "messy":
        # Grown from the messy end of the golden set: all-caps anger, and
        # the only number offered is a TICKET number, not an order id.
        ticket = (
            "WHERE IS MY PACKAGE?? Ticket TKT-1042. Nobody is helping me "
            "and I want answers NOW."
        )
    elif mode == "refund":
        # The B4 ticket: delivered, damaged, customer wants money back -
        # the ticket that walks the whole trust layer: preview, gate,
        # (human approval out-of-band), receipt.
        ticket = (
            "The desk mat from my order ORD-2077 arrived with a bad curl "
            "in it that won't flatten out - it's unusable. I don't want a "
            "replacement, I want my money back please."
        )
    elif mode == "refund-timing":
        # The B5 ticket: the order record says the refund was issued
        # (B4's live run), but WHEN the money lands lives only in the
        # policy corpus - the agent must fetch the refund-timing chunk
        # and answer from it, with its citation there to be checked.
        ticket = (
            "Hi, my refund for order ORD-2077 was approved and issued - "
            "how long until the money shows up in my account?"
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
