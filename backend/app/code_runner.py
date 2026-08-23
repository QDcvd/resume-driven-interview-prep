from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _run_one(code: str, assertion: str, timeout: float) -> dict[str, Any]:
    source = f"{code.rstrip()}\n\n{assertion}\n" if assertion else f"{code.rstrip()}\n"
    with tempfile.TemporaryDirectory(prefix="interview-code-") as directory:
        script = Path(directory) / "submission.py"
        script.write_text(source, encoding="utf-8")
        try:
            completed = subprocess.run(
                [sys.executable, "-I", str(script)],
                cwd=directory,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"passed": False, "timed_out": True, "output": "运行超时"}
    output = (completed.stdout + completed.stderr)[-8_000:]
    return {"passed": completed.returncode == 0, "timed_out": False, "output": output}


def run_python_submission(
    code: str, visible_tests: list[str], hidden_tests: list[str], timeout: float
) -> dict[str, Any]:
    smoke_only = not visible_tests
    visible = [_run_one(code, assertion, timeout) for assertion in visible_tests or [""]]
    if any(item["timed_out"] for item in visible):
        return {
            "passed": False,
            "timed_out": True,
            "visible_passed": 0,
            "visible_total": 1 if smoke_only else len(visible_tests),
            "hidden_passed": 0,
            "hidden_total": len(hidden_tests),
            "failures": ["运行超时"],
        }
    hidden = [_run_one(code, assertion, timeout) for assertion in hidden_tests]
    failures = [item["output"] or "断言失败" for item in [*visible, *hidden] if not item["passed"]]
    visible_passed = sum(bool(item["passed"]) for item in visible)
    hidden_passed = sum(bool(item["passed"]) for item in hidden)
    return {
        "passed": not failures,
        "timed_out": any(bool(item["timed_out"]) for item in hidden),
        "visible_passed": visible_passed,
        "visible_total": 1 if smoke_only else len(visible_tests),
        "hidden_passed": hidden_passed,
        "hidden_total": len(hidden_tests),
        "failures": failures,
    }
