"""Start the local interview exam service without installing dependencies."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


def backup_database() -> None:
    database = ROOT / "data" / "interview_exam.db"
    if not database.exists():
        return
    backup_dir = ROOT / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"interview_exam-{datetime.now():%Y%m%d-%H%M%S}.db"
    shutil.copy2(database, target)
    backups = sorted(backup_dir.glob("interview_exam-*.db"), reverse=True)
    for old_backup in backups[10:]:
        old_backup.unlink()


def migrate_database() -> None:
    config = ROOT / "alembic.ini"
    if config.exists():
        subprocess.run(["alembic", "-c", str(config), "upgrade", "head"], cwd=ROOT, check=True)


def open_browser_later(url: str) -> None:
    time.sleep(1.2)
    webbrowser.open(url)


def kill_port_processes(port: int) -> None:
    """启动前释放目标端口：结束占用该端口的旧进程，避免 10048 端口占用。

    只结束监听目标端口的进程，不会误杀同项目其他进程或其他服务。
    """
    pids: set[int] = set()
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0] == "TCP":
                    local, state, pid = parts[1], parts[3], parts[-1]
                    if (
                        state == "LISTENING"
                        and local.rsplit(":", 1)[-1] == str(port)
                        and pid.isdigit()
                    ):
                        pids.add(int(pid))
        else:
            result = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.splitlines():
                if line.strip().isdigit():
                    pids.add(int(line.strip()))
    except Exception:
        return
    for pid in pids:
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True,
                    text=True,
                )
            else:
                os.kill(pid, 9)
        except Exception:
            pass


def main() -> None:
    load_dotenv(ROOT / ".env")
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "8000"))
    kill_port_processes(port)
    backup_database()
    migrate_database()
    url = f"http://{host}:{port}"
    if os.getenv("APP_OPEN_BROWSER", "true").lower() in {"1", "true", "yes", "on"}:
        threading.Thread(target=open_browser_later, args=(url,), daemon=True).start()
    print(f"考试系统已启动：{url}")
    uvicorn.run("backend.app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
