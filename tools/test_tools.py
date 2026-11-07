#!/usr/bin/env python3
"""Contract tests for the B3 tool folders - no model, no API, no cost.

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

print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED'}")
sys.exit(1 if failures else 0)
