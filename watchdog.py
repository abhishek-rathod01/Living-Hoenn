"""
watchdog.py -- keep the bridge alive on an unattended PC.

Restarts the child whenever it exits, with a small backoff, and timestamps
the watchdog's OWN events (start, child exit code and uptime, restart count) to
a log file; the child's output is not captured and goes to the console only.
Ctrl+C stops both.

    python watchdog.py -- python bridge/dialogue_bridge_server.py --echo
    python watchdog.py --max-restarts 5 --backoff 3 -- <any command>

With no command after `--`, the default is `quest_bridge_server.py`, which is
the PARKED quest bridge (not the current default bridge) and is resolved
relative to the current directory, so it only starts from bridge/. Always pass
the command you want explicitly (checked 2026-10-15).
"""

import argparse
import subprocess
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backoff", type=float, default=3.0,
                    help="seconds to wait before a restart (default 3)")
    ap.add_argument("--max-restarts", type=int, default=0,
                    help="stop after N restarts (0 = forever)")
    ap.add_argument("--log", default="watchdog.log")
    ap.add_argument("cmd", nargs="*",
                    help="command after '--' (default: quest_bridge_server.py, the parked "
                         "quest bridge; resolved relative to the current directory)")
    args = ap.parse_args()
    cmd = args.cmd or [sys.executable, "-u", "quest_bridge_server.py"]

    def log(msg):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [watchdog] {msg}"
        print(line, flush=True)
        try:
            with open(args.log, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    restarts = 0
    log(f"supervising: {' '.join(cmd)}")
    try:
        while True:
            start = time.time()
            proc = subprocess.Popen(cmd)
            rc = proc.wait()
            uptime = time.time() - start
            restarts += 1
            log(f"child exited rc={rc} after {uptime:.1f}s (restart #{restarts})")
            if args.max_restarts and restarts >= args.max_restarts:
                log("max restarts reached; stopping")
                return 1
            time.sleep(args.backoff)
    except KeyboardInterrupt:
        log("interrupted; stopping child")
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
