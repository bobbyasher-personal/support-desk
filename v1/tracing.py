#!/usr/bin/env python3
"""S2 — the flight recorder: OpenTelemetry-shaped traces for Support Desk.

One trace per run (task). One span per operation: a graph node, a model
call, a tool call, a gate, the human approval. Spans are parented, so a
trace is a tree, not a pile of log lines — you can walk from the report
to the exact step that burned the money or broke the rule.

Schema: the OpenTelemetry GenAI semantic conventions, adopted Nov 17,
2026 — standard attribute names (gen_ai.request.model, gen_ai.tool.name,
gen_ai.usage.*) plus Support Desk governance attributes (supportdesk.*:
gate verdicts, policy decisions, approval references). Two standing
rules from that decision:

- The B6+ case id is stamped on EVERY span (supportdesk.case_id), so a
  multi-turn case — even one that restarts mid-case — reads as one
  thread across traces.
- Retries are separate spans. A step that runs twice leaves two spans;
  history is never rewritten to look cleaner than it was.

The store is plain JSONL: one file per trace under traces/ at the repo
root, one span per line, the root span first. This file format IS the
record — viewers (LangSmith, the Run Viewer) read from it, never the
other way round, and two consumers already do: S1's eval gate can grade
recorded runs, and the Analyst (analyst/) mines the same files for the
weekly error analysis. Dual-consumer rule: one store, standard schema.

Stdlib only, like everything before S5. A Tracer that is never started
costs nothing: control_graph checks for an active tracer and no-ops.
"""

import json
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORE = ROOT / "traces"

SCHEMA = "opentelemetry-genai (supportdesk profile, 2026-11-18)"


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _slug(text):
    keep = [c if (c.isalnum() or c in "-_") else "-" for c in str(text)]
    return "".join(keep).strip("-")[:40] or "run"


class Tracer:
    """Records one run as a span tree and writes it as JSONL.

    Usage:
        tracer = Tracer(case_id="cg2", run_name="control-graph cg2",
                        store_dir=DEFAULT_STORE)
        with tracer.span("intake", "agent.operation"):
            ...
        path = tracer.finish(outcome="approved")
    """

    def __init__(self, case_id, run_name, store_dir=None, agent_name="support-desk"):
        self.trace_id = uuid.uuid4().hex
        self.case_id = str(case_id)
        self.run_name = run_name
        self.store_dir = Path(store_dir) if store_dir else DEFAULT_STORE
        self.agent_name = agent_name
        self.spans = []
        self._stack = []
        self._t0 = time.time()
        self.root_span_id = uuid.uuid4().hex[:16]
        self._root = {
            "trace_id": self.trace_id,
            "span_id": self.root_span_id,
            "parent_span_id": None,
            "name": run_name,
            "kind": "trace",
            "start": _now_iso(),
            "start_unix": self._t0,
            "status": "running",
            "attributes": {
                "schema": SCHEMA,
                "gen_ai.agent.name": agent_name,
                "supportdesk.case_id": self.case_id,
            },
        }
        self.spans.append(self._root)
        self._stack.append(self.root_span_id)

    # -- recording ------------------------------------------------------

    @contextmanager
    def span(self, name, kind, attributes=None):
        span_id = uuid.uuid4().hex[:16]
        record = {
            "trace_id": self.trace_id,
            "span_id": span_id,
            "parent_span_id": self._stack[-1] if self._stack else self.root_span_id,
            "name": name,
            "kind": kind,
            "start": _now_iso(),
            "start_unix": time.time(),
            "status": "running",
            "attributes": {
                "gen_ai.agent.name": self.agent_name,
                "supportdesk.case_id": self.case_id,
                **(attributes or {}),
            },
        }
        self.spans.append(record)
        self._stack.append(span_id)
        try:
            yield record
        except Exception as exc:  # recorded, then re-raised — never swallowed
            if type(exc).__name__ == "GraphInterrupt":
                # A human-approval pause is the design working, not an
                # error: the span closes as interrupted, and the resume
                # opens its own span (retries are separate spans).
                record["status"] = "interrupted"
            else:
                record["status"] = "error"
                record["attributes"]["error.type"] = type(exc).__name__
                record["attributes"]["error.message"] = str(exc)[:300]
            raise
        else:
            if record["status"] == "running":
                record["status"] = "ok"
        finally:
            record["end"] = _now_iso()
            record["duration_ms"] = round((time.time() - record["start_unix"]) * 1000, 1)
            self._stack.pop()

    def set(self, record, **attributes):
        """Stamp extra attributes on an open span (e.g. a gate verdict
        known only after the gated code has run)."""
        record["attributes"].update(attributes)

    # -- finishing --------------------------------------------------------

    def totals(self):
        model = [s for s in self.spans if s["kind"] == "gen_ai.chat"]
        return {
            "spans": len(self.spans),
            "model_calls": len(model),
            "input_tokens": sum(s["attributes"].get("gen_ai.usage.input_tokens", 0)
                                for s in model),
            "output_tokens": sum(s["attributes"].get("gen_ai.usage.output_tokens", 0)
                                 for s in model),
            "tool_calls": sum(1 for s in self.spans if s["kind"] == "gen_ai.tool"),
            "errors": sum(1 for s in self.spans if s["status"] == "error"),
        }

    def finish(self, outcome=None):
        totals = self.totals()
        self._root["status"] = "ok"
        self._root["end"] = _now_iso()
        self._root["duration_ms"] = round((time.time() - self._t0) * 1000, 1)
        self._root["attributes"].update({
            "supportdesk.outcome": outcome or "unknown",
            "supportdesk.totals": totals,
        })
        self.store_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        path = self.store_dir / f"{stamp}-{_slug(self.case_id)}-{self.trace_id[:8]}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for record in self.spans:
                fh.write(json.dumps(record) + "\n")
        return path


def read_trace(path):
    """Read one trace file back: {trace_id, case_id, run_name, spans,
    root}. The read-back is the receipt — graders and the Analyst work
    from this, never from a run's own claims."""
    spans = [json.loads(line) for line in
             Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    root = next((s for s in spans if s["kind"] == "trace"), {})
    return {
        "trace_id": root.get("trace_id"),
        "case_id": root.get("attributes", {}).get("supportdesk.case_id"),
        "run_name": root.get("name"),
        "outcome": root.get("attributes", {}).get("supportdesk.outcome"),
        "totals": root.get("attributes", {}).get("supportdesk.totals", {}),
        "duration_ms": root.get("duration_ms"),
        "spans": spans,
        "root": root,
    }


def list_traces(store_dir=None):
    store = Path(store_dir) if store_dir else DEFAULT_STORE
    if not store.exists():
        return []
    return [read_trace(p) for p in sorted(store.glob("*.jsonl"))]
