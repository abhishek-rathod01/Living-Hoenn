# Open-day demo kit

Everything here is additive. Without `--trace`, the bridge behaves exactly as it did before: the same calls go to the model, with the same settings. `t_demo_trace` in `run_all_tests.py` checks this.

## The three buttons (repo root)

| Double-click | What it does |
|---|---|
| `START_DEMO.bat` | Starts Ollama if needed and picks the model (qwen3:8b first). Preloads it onto the GPU with `num_ctx` 2048, runs `run_all_tests.py`, then starts the bridge with `--trace`, the dashboard, and mGBA with the ROM and the hook. |
| `RESTART_BRIDGE.bat` | Restarts only the bridge. Then reload the hook in mGBA, because it only connects when it loads. |
| `STOP_DEMO.bat` | Stops the bridge and dashboard. Asks before closing mGBA or unloading the model. |

Options go after the name, in a terminal:

```
START_DEMO.bat -Model qwen3:8b -SkipTests -State 1
START_DEMO.bat -Mgba "C:\path\to\mGBA.exe"     (it remembers the path afterwards)
```

`-State 1` loads savestate slot 1 (`pokeemerald.ss1` next to the ROM). `-Quiet` never asks a question: every prompt takes its default answer, which suits unattended runs.

**mGBA 0.10.3 (the version on this laptop) can't load a script from the command line.** The launcher notices, opens mGBA with the ROM, and prints the menu path. Load the hook through mGBA's scripting window, under File > Load recent script, which remembers `mgba_hook.lua`.

## Crash recovery

- **The bridge runs under `watchdog.py`.** If it ever exits, it's back within 3 seconds, every time. That also covers Ollama going down and coming back. The dashboard then shows a red banner telling you to reload the hook, because the hook only connects when it loads.
- **Every model call has a 45 s cap** (`--llm-timeout`). The `ollama` package waits forever by default, so a stuck Ollama used to freeze the bridge for every NPC after it.
- **No error text reaches the game.** Any failure inside the bridge sends the neutral `...` and writes the real error, with a traceback, to the bridge window and the dashboard. Before this, the player saw text like `[error] KeyError: ...` in the NPC's text box.
- **Garbage from the socket** (bad bytes, non-object JSON) gets one `...` reply, and the connection stays open.
- **A print can't kill the bridge.** The console is set to replace characters it can't show instead of crashing on them.
- **Only one bridge can hold port 8888.** On Windows, `SO_REUSEADDR` let a second bridge bind the same port, and live testing showed two bridges "listening" at once. The bridge now asks Windows for exclusive use, so a second copy exits with code 2 and a clear message instead.
- **`RESTART_BRIDGE.bat` and `STOP_DEMO.bat` find processes by command line.** They stop every supervisor and every bridge, whether or not it holds a port. Then a restart starts exactly one fresh pair.

In `run_all_tests.py`, `t_bridge_crash_recovery` covers the bridge side (no error text reaches the game, the model-call timeout when the `ollama` package is installed, garbage input over a real socket, a second bridge exiting with code 2) and `t_watchdog` covers the restart loop. No automated test covers the console-encoding setting or the `.bat`/PowerShell process handling (checked 2026-10-15).

## The dashboard (http://127.0.0.1:8890/)

- **Timeline:** the last 30 seconds, one lane each for the game, the bridge, the model and the thinking replay. A thinking bar with a red X was stopped because the game asked for a new line.
- **The exchange:** what the hook read from RAM (with the real addresses from `lua/mgba_hook.lua`) and the line written back to `gStringVar4`.
- **Prompt sent to the model:** the model, temperature, context window, token counts, speed, and the model load time ("cold" means it had to load). Also shows the exact user message and the system prompt.
- **What the model is thinking:** the same prompt sent again with `think=true`, streamed live. It's a fresh sample, not the in-game run. The in-game run keeps thinking off, because after `WAIT_TIMEOUT` (about 10 s) the hook warns and shows `...`. A replay stops itself when a new request arrives, so it never queues GPU work in front of the game.

## If something goes wrong

| Symptom | Fix |
|---|---|
| NPC shows `...` and nothing else | Look at the bridge window. Run `RESTART_BRIDGE.bat`, then reload the hook. |
| "mGBA hook: disconnected" | In mGBA: Tools > Scripting... > File > **Reset**, then File > Load recent script > `mgba_hook.lua`. Do the Reset every time: in live testing on mGBA 0.10.3, loading the hook over an old copy dropped the new connection a few seconds after the first reply, and the console filled with `[hook] socket error`. Reset first fixed it. |
| Model load says "cold" | The model was unloaded. Leave the dashboard open, because it keeps the model warm. |
| Model shows less than 100% on GPU | Close other GPU users (Firefox/Teams/CoppeliaSim, video, games), then restart the demo. In the 3 Oct test qwen3:8b loaded only 73% on the GPU with those apps open: a first-visit NPC took about 11 s and a repeat visit about 3 s. |
| "can't show its thinking" | The model isn't a reasoning model. Use `-Model qwen3:8b`. |

Files this kit writes: `demo/trace.jsonl` (moved to `demo/trace-archive/` on the next start, never deleted), plus `demo/.last_model`, `demo/.mgba_path` and `demo/watchdog.log` (the watchdog's own events). All of them are gitignored (`.gitignore` lines for the trace, its archive, the two dot-files, and `*.log`).
