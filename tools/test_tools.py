#!/usr/bin/env python3
"""Contract tests for the B3 + B4 tool folders - no model, no API, no cost.

Every check fires a call at a tool and reads back what the agent would
read. The bad-call checks are the bite's point: a contract is only real
if garbage in produces an agent-readable error, not a guess, a crash,
or silence. Run: python3 tools/test_tools.py
"""

import importlib.util
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
import store as store_mod


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS_DIR / name / "tool.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, name)


get_order_status = load("get_order_status")
search_help_center = load("search_help_center")
create_draft_reply = load("create_draft_reply")
issue_refund = load("issue_refund")
import sandbox as sandbox_mod

failures = []


def check(label, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}: {label}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(label)


# --- get_order_status -------------------------------------------------------
out = get_order_status("ORD-1042")
check("good call returns the order", "wireless earbuds" in out and "ORD-1042" in out, out)

out = get_order_status("")
check("empty id -> required error", out.startswith("Error: order_id is required"), out)

out = get_order_status()
check("missing id -> required error", out.startswith("Error: order_id is required"), out)

out = get_order_status("TKT-1042")
check(
    "ticket number -> format error naming the confusion",
    "must look like ORD-1234" in out and "ticket number" in out,
    out,
)

out = get_order_status("ORD-9999")
check("unknown id -> not-found error", "no order found" in out, out)

# --- search_help_center -----------------------------------------------------
out = search_help_center("refund for a package that never arrived")
check("policy query finds the late-package article", "Late or lost packages" in out, out)

out = search_help_center("")
check("empty query -> required error", out.startswith("Error: query is required"), out)

out = search_help_center("gift wrapping options")
check("no-match is stated, not improvised", out.startswith("No help-center article matched"), out)

# --- create_draft_reply -----------------------------------------------------
out = create_draft_reply("", "Some reply text")
check("missing ticket_ref -> error", out.startswith("Error: ticket_ref is required"), out)

out = create_draft_reply("ticket about ORD-1042", "")
check("empty draft -> error", out.startswith("Error: draft_text was empty"), out)

before = len(store_mod.load_store()["drafts"])
out = create_draft_reply("contract test ticket", "TEST DRAFT - safe to delete.")
check("good save returns a draft id", '"draft_id"' in out, out)
saved = store_mod.load_store()["drafts"]
check(
    "read-back: the draft is actually in the store, awaiting approval",
    len(saved) == before + 1 and saved[-1]["status"] == "awaiting human approval",
)
# Clean up the test draft so the store only holds real run artifacts.
data = store_mod.load_store()
data["drafts"] = [d for d in data["drafts"] if d["draft_text"] != "TEST DRAFT - safe to delete."]
store_mod.save_store(data)

# --- issue_refund (B4: preview, gate, approval, receipt) --------------------
# Snapshot the whole store first: this section runs a full refund
# lifecycle on a throwaway order, then restores the snapshot so the
# store keeps only real run artifacts.
import json as _json

_store_snapshot = store_mod.STORE_PATH.read_text(encoding="utf-8")
# Guarantee the restore even if a check below crashes: without this, a
# failed run leaves its throwaway order and pending actions behind in
# the live store (bit Nov 9, 2026, once real refund history existed).
import atexit as _atexit
_atexit.register(lambda: store_mod.STORE_PATH.write_text(_store_snapshot, encoding="utf-8"))
_data = store_mod.load_store()
_data["orders"]["ORD-0000"] = {
    "eta": "2026-10-27",
    "item": "test widget",
    "last_scan": "2026-10-27, left at front door",
    "ordered": "2026-10-20",
    "price": 10.00,
    "status": "delivered",
}
store_mod.save_store(_data)

# History-independent: the store may already hold real pending actions
# and refunds from live runs, so compare counts, never absolute emptiness.
_before = store_mod.load_store()
_n_pending_before = len(_before.get("pending_actions", []))
_n_refunds_before = len(_before.get("refunds", []))
out = issue_refund("ORD-0000", "item arrived damaged", preview=True)
_state = store_mod.load_store()
check(
    "preview shows the refund and changes NOTHING",
    '"mode": "preview"' in out and '"amount": 10.0' in out
    and len(_state.get("pending_actions", [])) == _n_pending_before
    and len(_state.get("refunds", [])) == _n_refunds_before,
    out,
)

out = issue_refund("", "damaged")
check("refund: empty id -> required error", out.startswith("Error: order_id is required"), out)

out = issue_refund("TKT-1042", "damaged")
check(
    "refund: ticket number -> format error naming the confusion",
    "must look like ORD-1234" in out and "ticket number" in out,
    out,
)

out = issue_refund("ORD-9999", "damaged")
check("refund: unknown id -> not-found error", "no order found" in out, out)

out = issue_refund("ORD-0000", "")
check("refund: empty reason -> error", out.startswith("Error: a reason is required"), out)

out = issue_refund("ORD-0000", "item arrived damaged", preview=False)
_action_id = _json.loads(out)["pending_action_id"]
_state = store_mod.load_store()
_mine = [p for p in _state.get("pending_actions", []) if p["action_id"] == _action_id]
check(
    "gate: the real call creates a pending action and NO refund",
    len(_mine) == 1
    and _mine[0]["status"] == "awaiting approval"
    and len(_state.get("refunds", [])) == _n_refunds_before
    and _state["orders"]["ORD-0000"]["status"] == "delivered",
    out,
)

_done = store_mod.approve_and_execute(_action_id, "contract-test")
_state = store_mod.load_store()
check(
    "approval executes; read-back shows the refund and the order 'refunded'",
    _done["status"] == "executed"
    and store_mod.find_refund_for_order("ORD-0000")["status"] == "issued"
    and _state["orders"]["ORD-0000"]["status"] == "refunded",
)

try:
    store_mod.approve_and_execute(_action_id, "contract-test")
    _refused = False
except store_mod.GateError:
    _refused = True
check("double approval is refused - no second execution", _refused)

out = issue_refund("ORD-0000", "item arrived damaged", preview=True)
check("second refund on a refunded order -> error naming the refund", "already has a refund" in out, out)

store_mod.STORE_PATH.write_text(_store_snapshot, encoding="utf-8")

# --- retrieval + checked citations (B5) -------------------------------------
import importlib.util as _ilu

_rspec = _ilu.spec_from_file_location(
    "retrieval", TOOLS_DIR / "search_help_center" / "retrieval.py"
)
retrieval = _ilu.module_from_spec(_rspec)
_rspec.loader.exec_module(retrieval)

out = search_help_center("how long does a refund take")
check(
    "retrieval: the refund-timing chunk leads, with the 5-to-7 fact and a citation id",
    "refund-timing/c1" in out and "5 to 7 business days" in out,
    out,
)

out = search_help_center("my package is really late")
check(
    "retrieval: a paraphrase finds the late-package policy",
    "Late or lost packages" in out,
    out,
)

out = search_help_center("can I swap this for a different size")
check(
    "retrieval: the exchanges chunk answers a swap question",
    "exchanges/c1" in out,
    out,
)

_v = retrieval.check_claim("Refunds take 5 to 7 business days", "refund-timing/c1")
check("checker: a true claim with its citation passes", _v["ok"], _v["message"])

_v = retrieval.check_claim("Refunds take 3 to 5 business days", "refund-timing/c1")
check(
    "checker: a number the chunk does not contain fails, naming the number",
    not _v["ok"] and "3" in _v["message"],
    _v["message"],
)

_v = retrieval.check_claim("Refunds take 5 to 7 business days")
check(
    "checker: an uncited claim fails",
    not _v["ok"] and "no citation" in _v["message"],
    _v["message"],
)

_v = retrieval.check_claim("Refunds take 5 to 7 business days", "damaged-on-arrival/c1")
check("checker: a claim cited to the wrong chunk fails", not _v["ok"], _v["message"])

_v = retrieval.check_claim(
    "You'll also receive an email confirmation when the refund is issued",
    "refund-timing/c2",
)
check(
    "checker: a true claim in the draft's own words passes (no contraction false positive)",
    _v["ok"],
    _v["message"],
)

# --- the sandbox (B4) ---------------------------------------------------------
try:
    sandbox_mod.inside("tools/store.json")
    _inside_ok = True
except sandbox_mod.SandboxError:
    _inside_ok = False
check("sandbox allows a path inside the sandbox", _inside_ok)

for _evil in ("~/.ssh/id_ed25519", "/etc/passwd", "../outside.json"):
    try:
        sandbox_mod.inside(_evil)
        _refused = False
    except sandbox_mod.SandboxError:
        _refused = True
    check(f"sandbox refuses {_evil}", _refused)

print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED'}")
sys.exit(1 if failures else 0)
