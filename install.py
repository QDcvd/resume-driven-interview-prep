"""Install Python and frontend dependencies, then build the Vue application."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"


def require_command(name: str, help_text: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise SystemExit(f"缺少 {name}。{help_text}")
    return executable


def run(command: list[str], cwd: Path = ROOT) -> None:
    print(f"\n> {' '.join(command)}")
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    uv = require_command("uv", "请先安装 uv：https://docs.astral.sh/uv/")
    npm = require_command("npm", "请先安装 Node.js 20 或更高版本。")
    (ROOT / "data" / "backups").mkdir(parents=True, exist_ok=True)
    if not (ROOT / ".env").exists():
        shutil.copy2(ROOT / ".env.example", ROOT / ".env")
        print("已从 .env.example 创建 .env，请在使用 AI 评分前填写模型配置。")
    run([uv, "sync", "--dev"])
    npm_command = [npm, "ci"] if (FRONTEND / "package-lock.json").exists() else [npm, "install"]
    run(npm_command, FRONTEND)
    run([npm, "run", "build"], FRONTEND)
    print("\n安装完成。运行：uv run python start.py")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
    except KeyboardInterrupt:
        sys.exit(130)
