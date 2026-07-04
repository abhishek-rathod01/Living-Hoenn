# Superseded files (not tracked in this repo, kept out on purpose)

- **step1_dialogue_generator.py** — the original v1 dialogue harness, calling
  the Anthropic Claude API directly. Superseded by
  `bridge/step1_dialogue_ollama.py`, which uses a free local model (Ollama)
  instead, per the project's design (no paid API dependency for the core
  loop). The Anthropic-API version still exists in project history/chat if
  ever needed, but is intentionally excluded from the backup as dead code.
