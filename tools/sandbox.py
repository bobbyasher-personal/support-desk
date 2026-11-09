"""The sandbox boundary (bite B4).

The trust layer's fifth mechanism: the agent works in a locked room.
Every file the tool layer touches must resolve INSIDE the Support Desk
folder - the sandbox root. Anything outside it (another folder, the
user's home, a system file, a .. climb) is refused before it is read
or written, and the refusal is the receipt that the boundary held.

Identity limits WHO the agent acts as; this module limits WHERE it
can act at all. B4 covers files; network egress joins the same
allowlist idea at S6, when the deployed service arrives.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # the support-desk/ folder


class SandboxError(Exception):
    """Raised when a path tries to escape the sandbox. Carries words,
    not a stack trace - a refusal the trace can quote."""


def inside(path) -> Path:
    """Resolve `path` and return it ONLY if it lands inside the sandbox
    root. Relative paths resolve against the root. Raises SandboxError
    for anything outside - no silent clamping, no helpful guessing."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    resolved = candidate.resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise SandboxError(
            f"refused: '{path}' resolves to {resolved}, which is outside "
            f"the sandbox ({ROOT}). Tools may only touch files inside the "
            "sandbox."
        )
    return resolved
