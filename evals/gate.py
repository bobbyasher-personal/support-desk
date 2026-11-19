#!/usr/bin/env python3
"""S1 — the eval gate. Repo rule 5: the eval gate is law. No milestone
counts as done on a red gate, and no change ships through one.

The gate is the golden set at pass^3 (a case passes only if all three
runs pass — one lucky run proves nothing). It takes a while and costs
real tokens; that is the price of the word "done".

Usage (repo venv python):
  python evals/gate.py [--only gs-01,gs-03]
Exit code 0 = green gate. Anything else = red.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

if __name__ == "__main__":
    cmd = [sys.executable, str(HERE / "run_evals.py"), "--k", "3"]
    if len(sys.argv) > 1:
        cmd += sys.argv[1:]
    code = subprocess.run(cmd).returncode
    print("\nEVAL GATE:", "GREEN — the milestone may proceed."
          if code == 0 else "RED — no milestone counts as done on a red gate.")
    sys.exit(code)
