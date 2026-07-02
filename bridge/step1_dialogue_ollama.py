"""
STEP 1  --  Offline dialogue generator (Ollama, fully local, zero cost).

Runs WITHOUT mGBA. Feeds FAKE NPC context into a local Ollama model and prints
generated dialogue. This is where you perfect the prompt before touching the
emulator.

`generate_dialogue()` is the reusable core. In Step 2 the ONLY thing that
changes is where `ctx` comes from: instead of the fake list below, mGBA sends a
real game-state dict over a socket. The function stays identical.

SETUP
-----
  1. Install Ollama:  https://ollama.com/download
  2. Pull a model:    ollama pull llama3.2
     (llama3.2 = 3B, ~4GB RAM, fast. For better writing on a good GPU:
      ollama pull llama3.1:8b  and change MODEL below.)
  3. pip install ollama
  4. python step1_dialogue_ollama.py

Ollama runs a local server on 127.0.0.1:11434 automatically once installed.
"""

import ollama

MODEL = "llama3.2"          # local model tag; swap for "llama3.1:8b", "qwen2.5:7b", etc.

SYSTEM_PROMPT = """You write in-game dialogue for a Pokemon Emerald ROM hack.
Rules:
- Match the tone and era of Gen 3 Pokemon (Hoenn region).
- Output ONLY the spoken line(s). No quotation marks, no narration, no asterisks.
- Keep it under 45 words so it fits the game's text box.
- React naturally to the trainer's team and the situation you are given."""


def build_user_message(ctx: dict) -> str:
    """Turn a game-state dict into prompt text. Accepts hook-v3 fields
    (original_line, party as name:level, badges, map ids) and falls back to
    the older v2 fields so old tests/clients still work."""
    party = ", ".join(ctx.get("party") or ctx.get("player_party") or []) or "an unknown team"
    lines = []
    if ctx.get("original_line"):
        lines.append(f"NPC's original game line: {ctx['original_line']!r}")
    if ctx.get("npc_role"):
        lines.append(f"NPC role: {ctx['npc_role']}")
    try:
        from world_tables import MAPS
    except ImportError:
        MAPS = {}
    loc = (ctx.get("map")
           or MAPS.get((ctx.get("map_group"), ctx.get("map_num")))
           or f"map {ctx.get('map_group','?')}-{ctx.get('map_num','?')}")
    lines.append(f"Location: {loc}")
    lines.append(f"Player's badges: {ctx.get('badges', 0)}   "
                 f"Highest level: {ctx.get('player_level', '?')}")
    lines.append(f"Player's party: {party}")
    lines.append(f"Situation: {ctx.get('situation', 'The player talks to this NPC.')}")
    return "\n".join(lines) + "\n\nWrite what this NPC says, staying true to their original line's vibe."


def generate_dialogue(ctx: dict, model: str = MODEL) -> str:
    """CORE REUSABLE FUNCTION: game-state dict in, dialogue string out."""
    resp = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_message(ctx)},
        ],
        options={"temperature": 0.9},   # higher = more varied NPC personalities
    )
    # ChatResponse.message.content holds the text (verified against ollama SDK).
    return resp.message.content.strip()


if __name__ == "__main__":
    # FAKE game state. This is exactly the shape mGBA will send over a socket later.
    fake_contexts = [
        {
            "npc_role": "a Rock-type trainer guarding a cave",
            "map": "Granite Cave entrance",
            "player_level": 25,
            "player_party": ["Blaziken", "Swampert"],
            "situation": "The trainer notices the player's strong team and wants to battle.",
        },
        {
            "npc_role": "an old fisherman",
            "map": "Route 118",
            "player_level": 30,
            "player_party": ["Gyarados", "Manectric", "Hariyama"],
            "situation": "The player interrupts him mid-cast. He's friendly but distracted.",
        },
    ]

    for i, ctx in enumerate(fake_contexts, 1):
        print(f"\n--- NPC {i}: {ctx['npc_role']} ---")
        print(generate_dialogue(ctx))
