# PokéNav / match-call addresses

2026-07-05 — grepped from `pokeemerald.map` in
`C:\Users\abhis\Desktop\Living hoenn\pokeemerald`. Recorded only; nothing
built against these yet.

| Symbol | Address | Method |
|---|---|---|
| `gTrainers` | `0x08310030` | `grep -w gTrainers pokeemerald.map` |
| `sMatchCallState` | `0x0203cd80` | Not in `pokeemerald.map` (file-scope `static` in `src/match_call.c`, same as `sTextPrinters`/`sFieldMessageBoxMode`). Resolved via `arm-none-eabi-nm pokeemerald.elf` (`0x0203cd80`), cross-checked against `match_call.o`'s local offset (`0x0`) + its `ewram_data` section base (`0x0203cd80`) from the map — both methods agreed exactly.
