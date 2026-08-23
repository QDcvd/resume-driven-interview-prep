"""Run FastAPI and Vite development servers together."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    backend = subprocess.Popen(
        ["uv", "run", "uvicorn", "backend.app.main:app", "--reload", "--port", "8000"],
        cwd=ROOT,
    )
    frontend = subprocess.Popen(["npm", "run", "dev"], cwd=ROOT / "frontend")
    try:
        exit_code = max(backend.wait(), frontend.wait())
    except KeyboardInterrupt:
        exit_code = 130
    finally:
        backend.terminate()
        frontend.terminate()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
