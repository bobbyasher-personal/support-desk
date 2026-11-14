#!/usr/bin/env python3
"""B7 — Support Desk's loop, rebuilt in LangGraph: the frame around the loop.

v0/agent.py is the bare-hands loop: a while-loop with the gates, brakes,
and reflection woven through it, invisible unless you read the code.
This file rebuilds THE SAME BEHAVIOR as a graph — boxes and arrows you
can point at:

    START ─► agent ──(model named a tool)──► tools ─► agent ─► ...
               │
               └──(no tool named)──► reflect ─► END     [ticket mode]
               └──(no tool named)──► END                 [turn mode]

- The model call is v0's own `call_model` (same model, same raw API,
  same surrogate credential route). The tools are v0's own TOOL_FUNCS,
  loaded from the tool folders' contracts — the graph changes the
  FRAME, not the hands, not the brain, not the gates.
- B6 rides along unchanged: per-step desk-packing (pack_tools) chooses
  the contracts offered at each agent step, and absorb() folds tool
  results into the job state — which is now a field of the GRAPH STATE,
  checkpointed at every step instead of living in a local variable.
- The brakes are graph-shaped: the step budget is the state counter the
  agent node checks before every call (and LangGraph's recursion_limit
  is the hard backstop); the token budget escalates the same way v0's
  loop escalated — by stopping, in words, in the trace.
- Checkpointing: compile with a SqliteSaver and a thread_id and every
  super-step is a save-point on disk. A later process — a different
  `python3` entirely — opens the same file and the same thread and the
  job is exactly where it left off. That is the whole bite, proven by
  the gauntlet replay (replay_gauntlet.py), not asserted here.
- The approval gate did NOT move into a prompt or a comment: refunds
  still only ever become pending actions in the store (B4's tool), and
  approval still happens out-of-band. In the graph it is a place you
  can point at: the tools node is the only node that can write, and the
  only write path to a refund runs through issue_refund's gate.

Modes:
    python3 graph_agent.py tickets   the regression tickets (below),
                                     each against a store snapshot that
                                     is restored afterwards
Tickets: `default` (B1's ORD-1042), `refund-timing` (B5's ticket),
`refund-gate` (a damaged ORD-3101 refund — walks preview → gate submit
through the graph; the store snapshot means its pending action is a
run artifact, kept in the trace folder's store snapshot, not live
history).
"""

import importlib.util
import json
import operator
import sys
import time
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "gauntlet"))

# v0's agent: the model call, the tools, the packing, the reflection.
_spec = importlib.util.spec_from_file_location("sd_agent", ROOT / "v0" / "agent.py")
agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent)

# The gauntlet's prompts/case tools, reused verbatim for turn mode so the
# replay runs the SAME conversation discipline as B6+'s Arm B.
_gauntlet_spec = importlib.util.spec_from_file_location(
    "sd_gauntlet", ROOT / "gauntlet" / "run_gauntlet.py")
gauntlet = importlib.util.module_from_spec(_gauntlet_spec)
_gauntlet_spec.loader.exec_module(gauntlet)
import casefile as casefile_mod

MAX_STEPS = 8        # per invocation; v0's default was 6 for one ticket,
                     # the graph's refund flow + reflection needs the same
                     # headroom v0's drill budgets already granted.
MAX_TOKENS = 14000   # per TICKET invocation — the budget Bobby calibrated
                     # at B4, unchanged for the job shape it was set for.
MAX_TOKENS_TURN = 20000  # per TURN invocation in turn mode. Calibrated
                     # from the first replay's trace (kept as
                     # runs/2026-11-14-b7-gauntlet-replay-v1-failed.txt):
                     # v1 applied the per-ticket budget to the whole CASE,
                     # turn 1 alone cost ~14k, and every later turn
                     # escalated instantly — budgets are per invocation,
                     # because that is the unit that can spin. Case totals
                     # are tracked separately (tokens_case) for reporting.

TRACE = []


def log(line=""):
    TRACE.append(line)
    print(line)


class DeskState(TypedDict, total=False):
    messages: Annotated[list, operator.add]  # Anthropic-format messages
    ticket: str          # ticket mode: the ticket; turn mode: last customer msg
    mode: str            # "ticket" | "turn"
    job: dict            # B6 job state (absorb) — now checkpointed state
    steps: int           # per-invocation counters (the brakes read these)
    tokens: int
    tokens_case: int     # cumulative across a case's turns — reporting only
    draft_id: str
    reply: str           # the model's final text for this invocation
    escalated: str
    case_path: str       # turn mode only: the case file on disk (Arm B)
    turn: int            # turn mode only: scenario turn number


def _tools_for(state):
    if state.get("mode") == "turn":
        tools = [agent.CONTRACT_BY_NAME[n] for n in ("get_order_status", "issue_refund")]
        if state.get("case_path"):
            tools = tools + gauntlet.CASE_TOOLS
        return tools
    return agent.pack_tools(state["ticket"], state["job"])


def _system_for(state):
    if state.get("mode") == "turn":
        if state.get("case_path"):
            return gauntlet.BASE_PROMPT + gauntlet.CASEFILE_PROMPT
        return gauntlet.BASE_PROMPT
    return agent.SYSTEM_PROMPT


def agent_node(state):
    steps = state.get("steps", 0)
    tokens = state.get("tokens", 0)
    budget = MAX_TOKENS_TURN if state.get("mode") == "turn" else MAX_TOKENS
    if steps >= MAX_STEPS:
        log(f"  BRAKE: step budget ({MAX_STEPS}) hit in the agent node. Escalating.")
        return {"escalated": f"step budget {MAX_STEPS} hit",
                "reply": f"(escalated to a human - step budget {MAX_STEPS} hit)"}
    if tokens >= budget:
        log(f"  BRAKE: token budget ({budget}) hit in the agent node. Escalating.")
        return {"escalated": f"token budget {budget} hit",
                "reply": f"(escalated to a human - token budget {budget} hit)"}
    tools = _tools_for(state)
    log(f"  [agent] step {steps + 1}: desk = {[t['name'] for t in tools]}")
    reply = agent.call_model(state["messages"], system=_system_for(state), tools=tools)
    i, o = agent.tokens_of(reply)
    texts = [b.get("text", "") for b in reply["content"] if b.get("type") == "text"]
    out = {
        "messages": [{"role": "assistant", "content": reply["content"]}],
        "steps": steps + 1,
        "tokens": tokens + i + o,
        "tokens_case": state.get("tokens_case", 0) + i + o,
    }
    if texts and not any(b.get("type") == "tool_use" for b in reply["content"]):
        out["reply"] = "\n".join(texts).strip()
    return out


def tools_node(state):
    last = state["messages"][-1]
    job = json.loads(json.dumps(state.get("job") or agent.new_job()))
    results = []
    draft_id = state.get("draft_id")
    for tu in [b for b in last["content"] if b.get("type") == "tool_use"]:
        name, args = tu["name"], tu.get("input", {})
        if name in agent.TOOL_FUNCS:
            result = agent.TOOL_FUNCS[name](**args)
        elif name == "read_case_file" and state.get("case_path"):
            current = casefile_mod.load(state["case_path"])
            result = json.dumps(current) if current else (
                "No case file exists yet for this case. Create one with "
                "update_case_file before acting on a change.")
        elif name == "update_case_file" and state.get("case_path"):
            written = casefile_mod.accept_update(
                state["case_path"], args.get("case_file", {}), state.get("turn", 0))
            result = (f"Case file saved: state_version is now "
                      f"{written['state_version']}, updated_at_turn {written['updated_at_turn']}.")
        else:
            result = f"Unknown tool: {name}"
        log(f"  [tools] {name} {json.dumps(args)[:200]} -> {str(result)[:300]}")
        agent.absorb(job, name, args, str(result))
        if name == "create_draft_reply":
            try:
                draft_id = json.loads(result)["draft_id"]
            except (ValueError, KeyError):
                pass
        results.append({"type": "tool_result", "tool_use_id": tu["id"], "content": str(result)})
    out = {"messages": [{"role": "user", "content": results}], "job": job}
    if draft_id:
        out["draft_id"] = draft_id
    return out


def reflect_node(state):
    """Ticket mode only: v0's reflection pass, as its own node — the
    draft is graded against the evidence (the tool results carried in
    the messages), revised once if it fails, and the revision is saved
    through the same tool, exactly as v0 did it."""
    draft_id = state.get("draft_id")
    if not draft_id:
        log("  [reflect] no saved draft — nothing to grade.")
        return {}
    store = json.loads((ROOT / "tools" / "store.json").read_text(encoding="utf-8"))
    draft = next((d for d in store["drafts"] if d["draft_id"] == draft_id), None)
    if draft is None:
        log(f"  [reflect] {draft_id} not found in the store — skipping.")
        return {}
    evidence = []
    for m in state["messages"]:
        content = m.get("content")
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    evidence.append(str(b.get("content", "")))
    final, i, o = agent.reflect_on_draft(state["ticket"], draft["draft_text"], evidence, log)
    out = {"tokens": state.get("tokens", 0) + i + o}
    if final != draft["draft_text"]:
        saved = agent.TOOL_FUNCS["create_draft_reply"](
            ticket_ref=f"ticket about {state['ticket'][:60]}",
            draft_text=final, revision_of=draft_id)
        log(f"  [reflect] revision saved -> {saved}")
        try:
            out["draft_id"] = json.loads(saved)["draft_id"]
        except (ValueError, KeyError):
            pass
    return out


def _route_after_agent(state):
    if state.get("escalated"):
        return "reflect" if state.get("mode") == "ticket" and state.get("draft_id") else END
    last = state["messages"][-1]
    if any(b.get("type") == "tool_use" for b in last.get("content", [])):
        return "tools"
    return "reflect" if state.get("mode") == "ticket" else END


def build_graph(checkpointer=None):
    builder = StateGraph(DeskState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tools_node)
    builder.add_node("reflect", reflect_node)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", _route_after_agent,
                                  {"tools": "tools", "reflect": "reflect", END: END})
    builder.add_edge("tools", "agent")
    builder.add_edge("reflect", END)
    return builder.compile(checkpointer=checkpointer)


TICKETS = {
    "default": ("MY PACKAGE IS A WEEK LATE AND SUPPORT KEEPS IGNORING ME. "
                "THIS IS UNACCEPTABLE. My order is ORD-1042 - where is it??"),
    "refund-timing": ("Hi, my refund for order ORD-2077 was approved and issued - "
                      "how long until the money shows up in my account?"),
    "refund-gate": ("The desk mat from my order ORD-3101 arrived with a bad curl "
                    "that won't flatten out - it's unusable. I want my money back, please."),
}


def run_ticket(name, db_path):
    store_path = ROOT / "tools" / "store.json"
    base = store_path.read_text(encoding="utf-8")
    ticket = TICKETS[name]
    log(f"\n===== GRAPH TICKET: {name} =====")
    log(f"TICKET: {ticket}")
    started = time.time()
    try:
        with SqliteSaver.from_conn_string(str(db_path)) as saver:
            graph = build_graph(checkpointer=saver)
            config = {"configurable": {"thread_id": f"ticket-{name}"},
                      "recursion_limit": 40}
            final = graph.invoke(
                {"messages": [{"role": "user", "content": f"Ticket:\n{ticket}"}],
                 "ticket": ticket, "mode": "ticket", "job": agent.new_job(),
                 "steps": 0, "tokens": 0},
                config)
            snap = graph.get_state(config)
            log(f"CHECKPOINT: state saved at thread ticket-{name}; "
                f"next={snap.next or 'END'}; steps={final.get('steps')}, "
                f"tokens={final.get('tokens')}, draft={final.get('draft_id')}")
        log(f"REPLY: {final.get('reply', '(none)')}")
        log(f"RUN: {time.time() - started:.1f}s, tokens {final.get('tokens')} "
            f"(budget {MAX_TOKENS}), draft {final.get('draft_id')}")
        run_dir = HERE / "runs"
        (run_dir / f"store_after_ticket_{name}.json").write_text(
            store_path.read_text(encoding="utf-8"), encoding="utf-8")
        return final
    finally:
        store_path.write_text(base, encoding="utf-8")
        log("STORE: restored to the pre-run snapshot.")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "tickets"
    if mode == "tickets":
        db = HERE / "runs" / "checkpoints_tickets.sqlite"
        if db.exists():
            db.unlink()
        TRACE.clear()
        for name in TICKETS:
            run_ticket(name, db)
        (HERE / "runs" / "2026-11-14-b7-tickets.txt").write_text(
            "\n".join(TRACE) + "\n", encoding="utf-8")
        print("\nTrace: v1/runs/2026-11-14-b7-tickets.txt")


if __name__ == "__main__":
    main()
