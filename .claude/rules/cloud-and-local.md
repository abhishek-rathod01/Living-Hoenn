# Working on Living-Hoenn: local PC vs cloud session

<!-- Managed by claude-cloud-kit. Edit the kit, re-run generate.py, re-run bootstrap. -->

**Cloud viability: Partial - you can build and test in the cloud, but final verification needs your PC.**

Trunk branch: `main`

## Where am I running?

Check `$CLAUDE_CODE_REMOTE`. It is `true` in a Claude Code cloud session and
unset locally. Never assume; the two environments differ in ways that matter.

| | Local (Windows PC) | Cloud session |
|---|---|---|
| OS | Windows | Ubuntu 24.04, root |
| Paths | `C:\Users\abhis\...` | `/home/...`, POSIX |
| Resources | your machine | ~4 vCPU, 16 GB RAM, 30 GB disk |
| Untracked local files | present | **absent** - only what is committed |
| GUI / emulators / devices | available | **not available** |
| Network | open | proxied allowlist (Trusted by default) |

Any command in this repo's docs written with a Windows path or a PowerShell
idiom needs translating before it runs in a cloud session. Translate it; do not
guess that it will work.

## Do this in a cloud session

- run_all_tests.py (15 tests) -- the whole Python layer
- the decomp-mining pilot from HANDOVER section 5: clone your own pokeemerald fork in-session instead of the local Desktop path
- parser work on scripts.inc / map.json / trainers.h
- prompt tuning in dialogue_bridge_server.py, reviewed by tests

## Do NOT attempt this in a cloud session

- mGBA, the Lua hook, or anything touching a ROM -- no emulator, no legally dumped ROM in the cloud
- Ollama (no local model server); use --backend gemini/groq with a key set as a cloud env var, or --echo
- the section 4 live re-test of the Nurse Joy persona fix -- hardware only

If a task lands in the second list, say so and stop rather than producing an
unverifiable result. "The harness passed" is not the same claim as "it works".

## Session hygiene (applies everywhere)

- Push after every commit, not just at the end of a session.
- Sequential work by default. Parallel subagents each cold-start and re-read
  shared context, and that redundancy is paid for. Only parallelise genuinely
  siloed tasks.
- Give unattended runs an explicit stop condition: same error 3x -> escalate
  once -> log it as blocked and move on. Never loop.
- Record which kind of verification actually happened (harness vs. real
  hardware) in the commit message, not just that "tests pass".

## Read order when starting cold

1. `docs/LIVING_HOENN_HANDOVER.md` - current state, verified vs. open
2. `CLAUDE.md`
3. `docs/ARCHITECTURE.md`
4. `docs/VERIFICATION_REPORT.md` - every memory offset and how it was verified

## Standing rule

**Verify every game fact two independent ways** before trusting it - against the
real pokeemerald decomp or mGBA source, never from memory. State plainly what is
confirmed versus what is hypothesis.

## The cloud unlock for this repo

Handover section 5 (the decomp-mined NPC knowledge base) is written against a
local pokeemerald clone at a Windows Desktop path. In a cloud session, clone
`abhishek-rathod01/pokeemerald` instead - it is your own fork and reachable
through the GitHub proxy. That makes the whole pilot extraction pipeline a
cloud-viable task: parse `data/maps/<Map>/map.json`, cross-reference
`scripts.inc`, resolve `trainerbattle` constants against `src/data/trainers.h`,
emit one table keyed `map_group:map_num:npc_id`.

Pilot scope only: 4-5 named maps (Lilycove, Fortree, Slateport, one Pokemon
Center interior, one Route with a trainer). `scripts.inc` syntax is not uniform
across all ~400 maps; a parser that works on 5 is not proven on 400.

Spot-check a handful of generated entries by hand against the raw `.inc` before
trusting the table. Do not hand-edit the generated table - regenerate it.

## Cloud limits specific to this repo

- No mGBA, no ROM, no Lua hook testing. Anything in handover sections 3 and 4
  is hardware-only.
- Ollama is not available. Use `--echo` (no model) for plumbing tests, or
  `--backend gemini` / `--backend groq` with the key set as a **cloud
  environment variable**. Cloud environments have no secrets store - anyone who
  can edit the environment can read the value. Use a throwaway free-tier key.
- Add `generativelanguage.googleapis.com` (Gemini) or `api.groq.com` (Groq) to a
  Custom network allowlist if you want live backend calls.
- Never paste an API key into a chat with any assistant. If one leaks, revoke
  and regenerate.

## Known failure mode worth not re-diagnosing

If replies silently degrade to "...", check the terminal for
`persona designer produced unusable output:` or `missing field(s)` first. That
diagnostic was added specifically for this; do not re-derive it from scratch.
