# Superseded files (not tracked in this repo, kept out on purpose)

> **Status note (2026-10-15, base 38177ea):** still accurate as a list. Checked:
> `step1_dialogue_generator.py` is not tracked on any branch and has never been
> in this repo's git history (`git log --all` finds nothing), so "still exists
> in project history" can only refer to chat or local copies (UNVERIFIABLE FROM
> THE REPO). Its replacement `bridge/step1_dialogue_ollama.py` exists and is
> still imported by the legacy `bridge/bridge_server.py` and by
> `run_all_tests.py`; the current default bridge does not use it.

- **step1_dialogue_generator.py** — the original v1 dialogue harness, calling
  the Anthropic Claude API directly. Superseded by
  `bridge/step1_dialogue_ollama.py`, which uses a free local model (Ollama)
  instead, per the project's design (no paid API dependency for the core
  loop). The Anthropic-API version still exists in project history/chat if
  ever needed, but is intentionally excluded from the backup as dead code.
