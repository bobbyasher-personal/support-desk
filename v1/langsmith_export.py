#!/usr/bin/env python3
"""S2 — LangSmith as a VIEWER over the trace store, never the store.

Reads traces/*.jsonl (the OpenTelemetry-schema record written by
v1/tracing.py) and uploads them to LangSmith as run trees, so the
runs can be browsed in LangSmith's UI. The direction is the whole
point of the Nov 17, 2026 decision: the standard-schema store is the
record; LangSmith is one swappable viewer over it. Delete every run
in LangSmith and nothing is lost — re-export from traces/.

Mapping: the trace's root span becomes the LangSmith root run; each
span becomes a child run (dotted_order preserves the tree + timing);
gen_ai.* and supportdesk.* attributes ride along as metadata/tags.

Auth: the registered custom.langsmith connection (the key was entered
through Muse's secure credential flow — never in chat, never in this
repo). Requests carry an hsurr: surrogate via dynamic_credentials;
the real key is swapped in only on the approved request to the
registered host, exactly like the product's Anthropic calls. Project
defaults to "support-desk" (LANGSMITH_PROJECT overrides).

    python v1/langsmith_export.py --dry-run   # show what would upload
    python v1/langsmith_export.py             # upload all traces
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
import tracing
from dynamic_credentials import add_surrogate_to_request

API = "https://api.smith.langchain.com/runs/batch"


def _segment(ts_unix, run_id):
    """One dotted_order segment: the run's UTC start as
    %Y%m%dT%H%M%S%fZ immediately followed by the run's UUID."""
    stamp = datetime.fromtimestamp(ts_unix, tz=timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ")
    return f"{stamp}{run_id}"


def span_to_run(span, trace_uuid, run_id, dotted_order):
    attrs = span["attributes"]
    run = {
        "id": run_id,
        "trace_id": trace_uuid,
        "dotted_order": dotted_order,
        "name": span["name"],
        "run_type": {"gen_ai.chat": "llm", "gen_ai.tool": "tool"}.get(
            span["kind"], "chain"),
        "start_time": span["start"],
        "end_time": span.get("end"),
        "extra": {"metadata": {k: v for k, v in attrs.items()
                               if isinstance(v, (str, int, float, bool))}},
        "tags": [f"case:{attrs.get('supportdesk.case_id', '?')}"],
        "session_name": os.environ.get("LANGSMITH_PROJECT", "support-desk"),
    }
    if span["kind"] == "gen_ai.chat":
        run["inputs"] = {"model": attrs.get("gen_ai.request.model")}
        run["outputs"] = {"usage": {
            "input_tokens": attrs.get("gen_ai.usage.input_tokens"),
            "output_tokens": attrs.get("gen_ai.usage.output_tokens")}}
    if span["status"] == "error":
        run["error"] = f"{attrs.get('error.type')}: {attrs.get('error.message')}"
    return run


def _uuid_from(short, salt):
    """Deterministic UUID-shaped id from a span/trace id (LangSmith
    wants UUIDs; ours are hex already — pad deterministically)."""
    h = (short + salt + "0" * 32)[:32]
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def build_batch(traces):
    """LangSmith's tree scheme: a trace's id IS its root run's id, and
    each run's dotted_order is its parent's dotted_order plus its own
    segment (start-time + run UUID), root first."""
    posts = []
    for t in traces:
        root = t["root"]
        trace_uuid = _uuid_from(root["span_id"], t["trace_id"])
        by_parent = {}
        for s in t["spans"]:
            by_parent.setdefault(s["parent_span_id"], []).append(s)

        def emit(span, parent_dotted):
            run_id = trace_uuid if span is root else _uuid_from(
                span["span_id"], t["trace_id"])
            seg = _segment(span["start_unix"], run_id)
            dotted = seg if parent_dotted is None else f"{parent_dotted}.{seg}"
            run = span_to_run(span, trace_uuid, run_id, dotted)
            if span is root:
                run["inputs"] = {"run_name": t["run_name"],
                                  "case_id": t["case_id"]}
                run["outputs"] = {"outcome": t["outcome"], "totals": t["totals"]}
            else:
                run["parent_run_id"] = trace_uuid if \
                    span["parent_span_id"] == root["span_id"] else _uuid_from(
                        span["parent_span_id"], t["trace_id"])
            posts.append(run)
            for child in sorted(by_parent.get(span["span_id"], []),
                                key=lambda s: s["start_unix"]):
                emit(child, dotted)

        emit(root, None)
    return posts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print the batch summary without sending")
    args = ap.parse_args()
    traces = tracing.list_traces()
    if not traces:
        print("No traces in the store — nothing to export.")
        return 1
    posts = build_batch(traces)
    print(f"{len(traces)} traces -> {len(posts)} LangSmith runs "
          f"(project: {os.environ.get('LANGSMITH_PROJECT', 'support-desk')})")
    if args.dry_run:
        for r in posts[:3]:
            print("  sample:", json.dumps({k: r[k] for k in
                                           ("name", "run_type", "dotted_order")}))
        print("Dry run — nothing sent.")
        return 0
    req = urllib.request.Request(
        API, data=json.dumps({"post": posts}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    add_surrogate_to_request(req, "custom.langsmith",
                             allowed_hosts=["api.smith.langchain.com"])
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"LangSmith accepted the batch (HTTP {resp.status}). "
                  "The store remains traces/ — the viewer is a copy.")
            return 0
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:400]
        print(f"Upload failed: HTTP {exc.code}. LangSmith said: {body}")
        print("The traces are safe in traces/; fix the cause and re-run — "
              "export is idempotent by run id.")
        return 3
    except Exception as exc:
        print(f"Upload failed: {exc}. The traces are safe in traces/; "
              "fix the cause and re-run — export is idempotent by run id.")
        return 3


if __name__ == "__main__":
    sys.exit(main())
