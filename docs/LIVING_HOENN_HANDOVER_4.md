# LIVING HOENN — HANDOVER 4 (outreach, recording, and positioning)

Status tags: **[DONE]** · **[DRAFTED, UNSENT]** · **[IN PROGRESS]** ·
**[OPEN]** known gap · **[UNVERIFIED]** never confirmed.

This handover covers a session focused on **outreach, demo recording, and
CV/portfolio positioning** — not code. No code was changed. HANDOVER_3 remains
current for all technical state.

---

## 1. Artifacts produced this session

| File | Purpose |
|---|---|
| LIVING_HOENN_PROJECT_SUMMARY.md | Full CV-oriented project summary — achievements, bug list, metrics, suggested CV bullets |
| LIVING_HOENN_DEMO_SCRIPT.md | 7-9 min technical demo script for Aarbaz Alam |
| LIVING_HOENN_PORTFOLIO_SCRIPT.md | 3 min employer/portfolio script + 60-second cut |
| LIVING_HOENN_RUN_OF_SHOW.md | Shot-by-shot recording plan, scene mapping, window layout |
| LIVING_HOENN_STARTUP_COMMANDS.txt | Plain-text command reference for starting the stack |
| claude/LIVING_HOENN_OBS_RECORDING_SETUP.md | OBS configuration (updated by a Cowork session) |

---

## 2. Faculty outreach — current state of every thread

### Dr Rory Summerley (Course Leader, BA Game Design) — **replied**
- Lab specs: i9-10900X, 16GB RAM, **RTX 2060 Super**
- He wrote "16Gb" for the GPU; **verified the 2060 Super is 8GB** — no 16GB
  variant exists. Likely a speech-to-text duplication of the RAM figure.
- 8GB vs your current 6GB is a marginal gain. Not worth disrupting a
  games-students-only lab for.
- Lab access is restricted to games students; would need a staff member to
  liaise.
- **[DRAFTED, UNSENT]** Reply declining the hardware gracefully and pivoting
  to the more valuable ask: **his Pokemon-fan games students as human
  evaluators/playtesters**, plus a possible talk/demo. Includes a same-day
  4pm availability offer that is now stale — **remove or update that line
  before sending.**

### Dr Daqing Chen (UG Course Leader, BSc CS) — **replied twice, dead-ended**
- First reply: high-end workstations belong to research groups; there are
  some in **FW-114** but permission is needed; check with "the people you are
  working with."
- Second reply, verbatim: **"Please ask your supervisor about this."**
- He is assuming a supervisor exists. There isn't one.
- **[DRAFTED, UNSENT]** Short clarification: you're a **first-year entering
  second year**, this is solo self-directed work outside your course, so
  there is no supervisor or project team to refer to. Asks whether any route
  exists for self-directed student work, and asks him to suggest someone who
  might supervise it early. Mentions Aarbaz as a natural starting point.

### Aarbaz Alam (Lecturer, MSc — AI) — **replied enthusiastically**
- **Not a professor** — signs "Aarbaz Alam, MSc, Lecturer." Earlier drafts
  addressed him wrongly; first-name address now used.
- He is modding **gen1recomp** himself (voxel 3D mods, sprite replacement,
  widescreen; runs on Windows/Mac/Android). Genuine domain peer.
- His conditions: the project must **contribute to studies or be publishable**,
  and **Nintendo legal risk must be handled**.
- **Correction from earlier in session:** he **cannot grant hardware access**.
  He was offering to **contribute to the project**.
- **[DRAFTED, UNSENT]** Reply with the demo recording attached. Two variants:
  one asks directly whether he'd **supervise this as a final-year project**,
  one just accepts the offer to contribute. **The supervision ask is the
  highest-value unsent item in this entire session.**

### Dr Brahim El Boudani (PhD, AI) — **[DRAFTED, UNSENT]**
- Short, peer-level email asking for **AI-side critique** rather than
  resources: how to evaluate generated dialogue objectively, grounding-by-
  static-extraction vs retrieval, whether parameter count or grounding is the
  real bottleneck.
- Deliberately contains **no hardware ask** — mixing critique and resource
  requests dilutes both.

### The strategic finding across all four threads
Three staff members independently gave the same answer: **access follows
institutional affiliation, and you have none.** The bottleneck is not
hardware — it's that Living Hoenn is a solo project with no supervisor and no
formal standing.

**Formalising it as a final-year project with a supervisor solves the access
problem, the CV-credibility problem, and the thin-AI-component problem
simultaneously** — because a dissertation forces the evaluation harness the
project needs anyway. Aarbaz is the obvious candidate.

---

## 3. Recording — where it actually got to

**OBS is fully configured and verified** (see the OBS setup doc). Four scenes:

| Hotkey | Scene |
|---|---|
| Ctrl+Alt+1 | Camera Full |
| Ctrl+Alt+2 | Screen + Cam (PiP bottom-right) |
| Ctrl+Alt+3 | Screen Only |
| Ctrl+Alt+4 | Screen Zoom — **left two-thirds, 1280x720 at (0,180), 1.5x** |
| Ctrl+Alt+R | Record toggle |

Settings: 1080p60, NVENC H.264 CQP 20, Hybrid MP4, look-ahead off, single
pass. Mic: RNNoise -> Limiter. Desktop audio -25 dB. Output:
C:\\Users\\abhis\\Videos\\LivingHoennDemo.

**Disk is NOT a constraint** — measured, not estimated: ~1.2 GB/hour mixed,
9.1 GB/hour pure camera, 51.7 GB free. Whole session ~5-8 GB.

### Progress: **only Aarbaz Section 1 (camera intro) was recorded.**
Session was interrupted — had to go home mid-shoot. Everything else outstanding.

### Still to record
- **Camera block (do together, same sitting):** Aarbaz sections 4, 5, 6
  — scripts are in LIVING_HOENN_DEMO_SCRIPT.md
- **Demo block:** ordinary NPC x2, Route 110 trainer, awe reaction, sign/PC
- **Code block:** four Screen Zoom close-ups (verification output, decoder,
  injection code, mined dialogue table)
- **Entire portfolio video** (3 min) + 60-second cut

### Decisions made about method
- **Recording piecewise**, not as one live-switched take — removes dependence
  on the unverified minimised-hotkey behaviour, and allows re-aiming the
  Screen Zoom crop per clip.
- **Slate every clip out loud** ("Aarbaz, section four, take one") + two
  seconds of silence at head and tail of every take.
- **Camera segments must be recorded in one sitting** — same seat, lighting,
  framing — or the cuts between them will read as stitched.
- **Adobe suite now available** via the university. Premiere is the editor:
  Essential Sound -> Dialogue -> Auto-Match for loudness across separately
  recorded clips, and speech-to-text captions (will need manual correction of
  "pokeemerald", "gStringVar4", "mGBA").

### Recording blockers to clear first
- **[UNVERIFIED]** Do scene hotkeys fire while OBS is minimised? Cowork
  couldn't test this (its keystrokes only reached the focused window).
  Five-second manual test.
- **[OPEN]** **Poly Studio auto-framing / speaker tracking must be disabled**
  in Poly Lens — it re-framed itself mid-test and will drift during a
  talking-head take.
- **[OPEN]** cbcc26c still not live-verified. The unrecorded rehearsal of
  the demo route doubles as that verification — do it before recording the
  demo block.
- Terminal font must be **20pt minimum** or the state payload is unreadable
  after upload compression.
- Delete the two Cowork test files (86 MB) in the output folder.

---

## 4. Honest positioning assessment (from this session)

**Where the project places you against ~100 grad/placement applicants: top
5-10** for software/applied-AI roles. Drivers: it's a systems project rather
than an API wrapper; the root-cause debugging stories are real; the
verification discipline is unusually mature for an undergraduate.

**What holds it back:**
- The **AI component is the thinnest part**, which is awkward on an AI course.
  No training, no fine-tuning, and critically **no evaluation** — every
  quality claim is anecdotal. For ML-research-flavoured roles this drops to
  roughly top 15-20.
- Solo, unshipped, no users — demonstrates nothing about collaboration.
- **Heavy AI assistance in the build.** This is fine and normal, but it means
  any technical interviewer who probes will quickly establish whether you
  understand it or merely supervised it. **Know the injection mechanism and
  the substruct decryption cold** — those are the claims that attract
  questions.

**Highest-leverage next actions, in order:**
1. **Build the evaluation harness** — closes the biggest gap, and is exactly
   what the compute requests are for
2. Record and publish a **90-second demo video** at the top of the README
3. **Fix git attribution** — past commits are authored as
   Pokemon LLM Bridge Build <builder@local>, so your contribution graph
   doesn't show you as author
4. Write up the injection mechanism as a short technical post

---

## 5. AI improvement roadmap (discussed, nothing built)

**Order matters — evaluation first, always.**

1. **Evaluation harness.** Your architecture gives programmatic ground truth:
   you can automatically detect whether a generated line mentions a Pokemon
   that trainer doesn't have. Plus constraint violations (4th-wall vocabulary,
   role breaks, quest/item offers), repetition (n-gram overlap vs recent
   lines), and latency. Rubric-based LLM-as-judge on top, using a *hosted*
   model so it's independent of the model under test. Build it against the
   existing transcripts.jsonl corpus.
2. **Cheap wins before touching weights:** few-shot exemplars drawn from the
   185 mined vanilla lines (highest value per hour); best-of-N generation
   scored by the harness; constrained decoding via Ollama structured output;
   a temperature sweep now that you can measure.
3. **Fine-tuning, the version worth doing: distillation.** Use Groq's
   llama-3.3-70b-versatile as teacher to generate several thousand lines,
   filter through the harness, LoRA-fine-tune a **1-3B student**. Result would
   be publishable-shaped: "a 3B student matched an 8B general model on
   grounding faithfulness at 2.5x the speed." A 3B student fits 6GB
   comfortably; **[HYPOTHESIS]** QLoRA on 7-8B at 6GB is right at the edge —
   verify with one training step and nvidia-smi before planning around it.
4. **Test retrieval as the alternative.** Embed the mined corpus, retrieve
   k-nearest vanilla lines as few-shot context. Cheaper, updatable without
   retraining, no baked-in-weights legal ambiguity. **May well beat
   fine-tuning** — and "I tested both and retrieval won" is a stronger result
   than reflexively training.

**Legal caution:** weights fine-tuned on mined Nintendo text inherit the same
gray-zone status as the mined table, arguably worse since it's less separable.
Keep any fine-tuned weights local and unpublished. Retrieval sidesteps this.

**Scope caution:** this project's own history shows what happens when two
unproven systems run at once. Close out cbcc26c and the full map-mining
rollout before opening a training thread.

---

## 6. Next session focus

1. **Technical standpoint write-up** — a rigorous articulation of the
   project's engineering substance, for interviews and for the eventual
   dissertation proposal.
2. **LinkedIn** — profile rebuild around this project plus the Kilobot RA
   role, and a strategy for actually using the platform to become visible to
   employers rather than just having a profile.
