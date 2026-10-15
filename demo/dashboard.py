"""
demo/dashboard.py -- live open-day dashboard for the dialogue bridge.

    python demo/dashboard.py                     # tails demo/trace.jsonl, opens the browser
    python demo/dashboard.py --model qwen3:8b --no-open

Needs the bridge started with --trace demo/trace.jsonl (START_DEMO.bat does
this). Standard library only, so nothing new has to be installed on demo day,
and it binds to 127.0.0.1 only.

What the page shows comes from two sources, kept apart on screen:

  1. The real in-game request, from the bridge's --trace events: the game
     state the Lua hook read from RAM, the exact system + user messages, the
     model and its settings (temperature, num_ctx, think), token counts and
     timings, and the line sent back to the hook.

  2. A reasoning replay: the same messages sent again to the same model with
     think=true, streamed token by token. This is a fresh sample, NOT the run
     that produced the in-game line. The in-game run uses think=False on
     purpose: mgba_hook.lua shows "..." and warns when a reply takes longer than WAIT_TIMEOUT (~10 s),
     which thinking on an 8B model on a 6 GB GPU can exceed.

GPU safety: a replay is cancelled the moment the bridge logs a new request
(the stream is closed, which makes Ollama stop generating), so the dashboard
never holds the GPU while the game is waiting. Replays reuse the bridge's own
num_ctx, because Ollama reloads the model whenever num_ctx changes.
"""

import argparse
import collections
import datetime
import json
import os
import queue
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_TRACE = os.path.join(HERE, "trace.jsonl")
PAGE = os.path.join(HERE, "dashboard.html")

MAX_THINK_TOKENS = 1024      # cap on a replay's thinking + answer
KEEP_WARM_MARGIN_S = 90      # re-pin the model when it would unload within this


def log(msg):
    # ASCII only: the Windows console codepage is not guaranteed to be UTF-8.
    print("[dashboard] " + msg.encode("ascii", "replace").decode("ascii"), flush=True)


# ---------------------------------------------------------------- event hub
class Hub:
    """Fan-out of JSON events to every open browser tab (Server-Sent Events)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.clients = []
        self.recent = collections.deque(maxlen=300)   # bridge events, for page reloads
        self.latest = {}                              # last event per singleton kind

    def publish(self, ev, keep=True):
        data = json.dumps(ev, ensure_ascii=False, default=str)
        with self.lock:
            if keep:
                self.recent.append(data)
            for q in list(self.clients):
                try:
                    q.put_nowait(data)
                except queue.Full:
                    pass

    def set_latest(self, kind, ev):
        with self.lock:
            self.latest[kind] = ev
        self.publish(ev, keep=False)

    def subscribe(self):
        q = queue.Queue(maxsize=20000)
        with self.lock:
            self.clients.append(q)
            snapshot = list(self.recent)
            latest = [json.dumps(v, ensure_ascii=False, default=str)
                      for v in self.latest.values()]
        return q, snapshot, latest

    def unsubscribe(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)


# ---------------------------------------------------------------- Ollama I/O
def http_json(url, body=None, timeout=5.0):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def parse_ollama_time(s):
    """Ollama's expires_at has nanosecond fractions, which older Pythons'
    fromisoformat rejects. Returns a POSIX timestamp or None."""
    if not s:
        return None
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?(Z|[+-]\d\d:\d\d)?$", s)
    if not m:
        return None
    tz = m.group(2) or "+00:00"
    tz = "+00:00" if tz == "Z" else tz
    try:
        return datetime.datetime.fromisoformat(m.group(1) + tz).timestamp()
    except ValueError:
        return None


def budget_for(options, prompt_tokens):
    """num_predict for a replay: never more than MAX_THINK_TOKENS, and never
    past the end of the bridge's context window (prompt + output <= num_ctx)."""
    ctx = int(options.get("num_ctx") or 2048)
    room = ctx - int(prompt_tokens or 0) - 16
    return max(128, min(MAX_THINK_TOKENS, room))


def parse_stream_line(raw):
    """One NDJSON line from /api/chat (stream=true) -> (thinking, content,
    final_chunk_or_None). Raises RuntimeError on an in-stream error."""
    raw = raw.strip()
    if not raw:
        return "", "", None
    chunk = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    if chunk.get("error"):
        raise RuntimeError(chunk["error"])
    msg = chunk.get("message") or {}
    final = chunk if chunk.get("done") else None
    return msg.get("thinking") or "", msg.get("content") or "", final


# ---------------------------------------------------------------- replays
class Replayer:
    def __init__(self, hub, ollama_url, auto=True):
        self.hub = hub
        self.url = ollama_url.rstrip("/")
        self.auto = auto
        self.lock = threading.Lock()
        self.calls = {}          # req id -> {"start": llm_start ev, "done": llm_done ev}
        self.last_req = None     # newest req id that had a completed chatter call
        self.cur = None
        self.seq = 0
        self.last_activity = time.time()

    # bridge events arrive here from the tailer
    def on_bridge_event(self, ev, live):
        kind = ev.get("ev")
        req = ev.get("req")
        if kind in ("request", "llm_start"):
            self.last_activity = time.time()
            if live:
                self.cancel("The game asked for a new line, so the replay stopped to free the GPU.")
        if kind == "llm_start" and ev.get("stage") == "chatter":
            self.calls.setdefault(req, {})["start"] = ev
        elif kind == "llm_done" and ev.get("stage") == "chatter":
            self.calls.setdefault(req, {})["done"] = ev
            if "start" in self.calls[req]:
                self.last_req = req
        elif kind == "reply" and live and self.auto and ev.get("kind") == "llm":
            if req == self.last_req:
                self.start(req, auto=True)
        if len(self.calls) > 50:
            for k in sorted(self.calls, key=lambda x: (x is None, x))[:-50]:
                self.calls.pop(k, None)

    def snapshot(self):
        with self.lock:
            cur = self.cur
            if not cur:
                return None
            return {"ev": "think_snapshot", "rid": cur["rid"], "req": cur["req"],
                    "status": cur["status"], "thinking": cur["thinking"],
                    "answer": cur["answer"], "model": cur["model"],
                    "options": cur["options"], "t0": cur["t0"],
                    "final": cur.get("final"), "note": cur.get("note")}

    def cancel(self, reason):
        with self.lock:
            cur = self.cur
            if cur and cur["status"] in ("waiting", "thinking", "answering"):
                cur["cancel"].set()
                cur["status"] = "cancelled"
                cur["note"] = reason
                self.hub.publish({"ev": "think_cancelled", "rid": cur["rid"],
                                  "reason": reason}, keep=False)
                return True
        return False

    def start(self, req=None, auto=False):
        req = self.last_req if req is None else req
        call = self.calls.get(req) or {}
        start, done = call.get("start"), call.get("done")
        if not start:
            return False, "No model call to replay yet. Talk to an NPC in the game first."
        self.cancel("A newer replay started.")
        options = dict(start.get("options") or {})
        options["num_predict"] = budget_for(options, (done or {}).get("prompt_tokens"))
        with self.lock:
            self.seq += 1
            cur = {"rid": self.seq, "req": req, "cancel": threading.Event(),
                   "status": "waiting", "thinking": "", "answer": "",
                   "model": start.get("model"), "options": options,
                   "t0": time.time()}
            self.cur = cur
        self.hub.publish({"ev": "think_start", "rid": cur["rid"], "req": req,
                          "model": cur["model"], "options": options, "auto": auto,
                          "t0": cur["t0"]}, keep=False)
        body = {"model": start.get("model"), "messages": start.get("messages"),
                "think": True, "stream": True, "options": options}
        threading.Thread(target=self._run, args=(cur, body), daemon=True).start()
        return True, "started"

    def _run(self, cur, body):
        rid = cur["rid"]
        req = urllib.request.Request(self.url + "/api/chat",
                                     data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                for raw in resp:
                    if cur["cancel"].is_set():
                        break      # leaving the with-block closes the stream;
                                   # Ollama stops generating on disconnect
                    thinking, content, final = parse_stream_line(raw)
                    if thinking:
                        with self.lock:
                            cur["thinking"] += thinking
                            cur["status"] = "thinking"
                        self.hub.publish({"ev": "think_delta", "rid": rid,
                                          "text": thinking}, keep=False)
                    if content:
                        with self.lock:
                            cur["answer"] += content
                            cur["status"] = "answering"
                        self.hub.publish({"ev": "answer_delta", "rid": rid,
                                          "text": content}, keep=False)
                    if final is not None:
                        info = {k: final.get(k) for k in (
                            "done_reason", "prompt_eval_count", "eval_count",
                            "load_duration", "prompt_eval_duration",
                            "eval_duration", "total_duration")}
                        with self.lock:
                            cur["status"] = "done"
                            cur["final"] = info
                        if not cur["thinking"]:
                            info["no_thinking"] = True
                        self.hub.publish(dict({"ev": "think_done", "rid": rid}, **info),
                                         keep=False)
                        break
        except urllib.error.HTTPError as e:
            self._fail(cur, self._http_error_text(e))
        except Exception as e:
            if not cur["cancel"].is_set():
                self._fail(cur, f"{type(e).__name__}: {e}")

    @staticmethod
    def _http_error_text(e):
        try:
            detail = json.loads(e.read().decode("utf-8")).get("error") or ""
        except Exception:
            detail = ""
        if "think" in detail.lower():
            return (f"This model can't show its thinking ({detail}). "
                    "Thinking needs a reasoning model such as qwen3.")
        return f"Ollama returned HTTP {e.code}: {detail or e.reason}"

    def _fail(self, cur, text):
        with self.lock:
            cur["status"] = "error"
            cur["note"] = text
        self.hub.publish({"ev": "think_error", "rid": cur["rid"], "error": text},
                         keep=False)

    def busy(self):
        with self.lock:
            return bool(self.cur and self.cur["status"] in ("waiting", "thinking", "answering"))


# ---------------------------------------------------------------- background loops
def tail_trace(path, hub, replayer, state, stop):
    """Follow the bridge's trace file. Seeds the page with the recent past
    (not replayed into auto-replay), then streams new lines as they land."""
    pos = 0
    buf = b""
    if os.path.exists(path):
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - 256 * 1024))
            seed = f.read()
        pos = size
        lines = seed.split(b"\n")
        if size > 256 * 1024:
            lines = lines[1:]          # first line is probably cut in half
        for raw in lines[-300:]:
            ev = _parse(raw)
            if ev:
                ev["seeded"] = True
                _handle(ev, hub, replayer, state, live=False)
    while not stop.is_set():
        try:
            if os.path.exists(path):
                size = os.path.getsize(path)
                if size < pos:         # file was cleared: start over
                    pos, buf = 0, b""
                if size > pos:
                    with open(path, "rb") as f:
                        f.seek(pos)
                        chunk = f.read(size - pos)
                    pos += len(chunk)
                    buf += chunk
                    *complete, buf = buf.split(b"\n")
                    for raw in complete:
                        ev = _parse(raw)
                        if ev:
                            _handle(ev, hub, replayer, state, live=True)
        except OSError:
            pass                       # bridge mid-write on Windows: try again
        stop.wait(0.08)


def _parse(raw):
    raw = raw.strip()
    if not raw:
        return None
    try:
        ev = json.loads(raw.decode("utf-8", "replace"))
        return ev if isinstance(ev, dict) and ev.get("ev") else None
    except ValueError:
        return None


def _handle(ev, hub, replayer, state, live):
    kind = ev.get("ev")
    if kind == "llm_start" and ev.get("model"):
        state["model"] = ev["model"]
        state["num_ctx"] = (ev.get("options") or {}).get("num_ctx", state.get("num_ctx"))
    elif kind == "bridge_up":
        m = re.search(r"\((.+)\)\s*$", ev.get("mode") or "")
        if m and "ollama" in (ev.get("mode") or ""):
            state["model"] = m.group(1)
    hub.publish(ev, keep=True)
    replayer.on_bridge_event(ev, live)


def watch_ollama(url, hub, replayer, state, stop, keep_warm):
    url = url.rstrip("/")
    version = None
    last_ping = 0.0
    while not stop.is_set():
        info = {"ev": "ollama", "up": False, "url": url, "models": [],
                "keep_warm": keep_warm, "checked": time.time()}
        try:
            if version is None:
                version = http_json(url + "/api/version", timeout=2).get("version")
            ps = http_json(url + "/api/ps", timeout=2)
            info["up"] = True
            info["version"] = version
            for m in ps.get("models") or []:
                info["models"].append({
                    "name": m.get("name") or m.get("model"),
                    "size": m.get("size"), "size_vram": m.get("size_vram"),
                    "expires_at": parse_ollama_time(m.get("expires_at")),
                    "context_length": m.get("context_length")})
        except Exception as e:
            version = None
            info["error"] = f"{type(e).__name__}"
        info["target_model"] = state.get("model")
        hub.set_latest("ollama", info)

        # keep-warm: Ollama unloads a model 5 min after its last request unless
        # OLLAMA_KEEP_ALIVE says otherwise. A load-only request with
        # keep_alive=-1 re-pins it. Same num_ctx as the bridge, or Ollama
        # would reload the model at a different context size.
        model = state.get("model")
        if keep_warm and info["up"] and model and not replayer.busy() \
                and time.time() - last_ping > 30 \
                and time.time() - replayer.last_activity > 5:
            loaded = [m for m in info["models"] if m["name"] == model]
            exp = loaded[0]["expires_at"] if loaded else None
            soon = (not loaded) or (exp is not None and exp - time.time() < KEEP_WARM_MARGIN_S)
            if soon:
                last_ping = time.time()
                try:
                    http_json(url + "/api/generate",
                              {"model": model, "keep_alive": -1,
                               "options": {"num_ctx": int(state.get("num_ctx") or 2048)}},
                              timeout=120)
                    hub.publish({"ev": "keepwarm", "model": model, "ok": True,
                                 "loaded_before": bool(loaded)}, keep=False)
                except Exception as e:
                    hub.publish({"ev": "keepwarm", "model": model, "ok": False,
                                 "error": f"{type(e).__name__}: {e}"}, keep=False)
        stop.wait(2.0)


# ---------------------------------------------------------------- HTTP
def make_handler(hub, replayer, state):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                with open(PAGE, encoding="utf-8") as f:
                    self._send(200, f.read().encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/events":
                self._events()
            elif path == "/api/state":
                self._json(200, {"auto": replayer.auto, "trace": state["trace"],
                                 "model": state.get("model")})
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            u = urlparse(self.path)
            if u.path == "/api/replay":
                ok, msg = replayer.start(auto=False)
                self._json(200 if ok else 409, {"ok": ok, "message": msg})
            elif u.path == "/api/stop":
                ok = replayer.cancel("Stopped from the dashboard.")
                self._json(200, {"ok": ok})
            elif u.path == "/api/auto":
                on = parse_qs(u.query).get("on", ["1"])[0] == "1"
                replayer.auto = on
                hub.publish({"ev": "auto", "on": on}, keep=False)
                self._json(200, {"ok": True, "auto": on})
            else:
                self._send(404, b"not found", "text/plain")

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q, snapshot, latest = hub.subscribe()
            try:
                hello = {"ev": "hello", "auto": replayer.auto, "trace": state["trace"],
                         "server_time": time.time()}
                self._write(json.dumps(hello))
                for data in snapshot:
                    self._write(data)
                self._write(json.dumps({"ev": "seed_done"}))
                for data in latest:
                    self._write(data)
                snap = replayer.snapshot()
                if snap:
                    self._write(json.dumps(snap, ensure_ascii=False, default=str))
                while True:
                    try:
                        data = q.get(timeout=15)
                        self._write(data)
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            finally:
                hub.unsubscribe(q)

        def _write(self, data):
            self.wfile.write(b"data: " + data.encode("utf-8") + b"\n\n")
            self.wfile.flush()

    return Handler


def main():
    ap = argparse.ArgumentParser(description="Living Hoenn live dashboard")
    ap.add_argument("--trace", default=DEFAULT_TRACE,
                    help="trace file the bridge writes with --trace (default demo/trace.jsonl)")
    ap.add_argument("--port", type=int, default=8890)
    ap.add_argument("--ollama", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default=None,
                    help="model to keep warm before the bridge's first call")
    ap.add_argument("--no-auto", action="store_true",
                    help="start with automatic reasoning replays off")
    ap.add_argument("--no-keep-warm", action="store_true")
    ap.add_argument("--no-open", action="store_true", help="don't open a browser tab")
    args = ap.parse_args()

    trace = os.path.abspath(args.trace)
    state = {"trace": trace, "model": args.model, "num_ctx": 2048}
    hub = Hub()
    replayer = Replayer(hub, args.ollama, auto=not args.no_auto)
    stop = threading.Event()

    threading.Thread(target=tail_trace, args=(trace, hub, replayer, state, stop),
                     daemon=True).start()
    threading.Thread(target=watch_ollama,
                     args=(args.ollama, hub, replayer, state, stop, not args.no_keep_warm),
                     daemon=True).start()

    class QuietServer(ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            # Browsers drop keep-alive connections all the time. That is not
            # an error, and a full traceback in the window looks alarming.
            exc = sys.exc_info()[1]
            if isinstance(exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
                return
            super().handle_error(request, client_address)

    server = QuietServer(("127.0.0.1", args.port), make_handler(hub, replayer, state))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{args.port}/"
    log(f"live at {url}")
    log(f"following {trace}")
    if not args.no_open:
        webbrowser.open_new_tab(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        log("shutting down")
    finally:
        stop.set()
        replayer.cancel("Dashboard closed.")
        server.server_close()


if __name__ == "__main__":
    sys.exit(main())
