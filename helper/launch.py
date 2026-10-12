#!/usr/bin/env -S uv run --locked --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Plugin-side launcher (stdlib only; the plugin runs it with `uv run --locked --script`, so it works on every OS).

  launch.py start      start the helper detached unless one is already running; prints started|running
"""
import os
import subprocess
import sys
import time
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / ".state"   # <plugin>/.state, the folder the plugin reads and writes


def is_running() -> bool:
    try:
        return time.time() - (STATE / "alive").stat().st_mtime < 5
    except OSError:
        return False


def start() -> str:
    if is_running():
        return "running"
    STATE.mkdir(parents=True, exist_ok=True)
    for stale in (STATE / "cmd").glob("*.json"):   # commands left over from an earlier run
        stale.unlink(missing_ok=True)
    (STATE / "heartbeat").write_text(str(int(time.time() * 1000)))   # grace period while the models load
    cmd = ["uv", "run", "--locked", "--script", str(Path(__file__).with_name("helper.py")), "--state-dir", str(STATE)]
    log = open(STATE / "helper.out", "ab")
    flags = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}  # detached
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **flags)
    return "started"


if __name__ == "__main__":
    if sys.argv[1:2] == ["start"]:
        print(start())
    else:
        sys.exit("usage: launch.py start")
