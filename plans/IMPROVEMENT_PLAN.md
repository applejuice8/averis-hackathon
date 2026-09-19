# Improvement Plan — mapped to the preliminary judging rubric

Rubric: **100 pts = Technical 70 + Product & Impact 30**.
Bands: 10-pt → excellent 8–10 · 15-pt → excellent 12–15 · 25-pt → excellent 19–25.

> Scoring note from the rubric: *"Base scores on what is demonstrated,
> submitted or clearly explained. Do not reward the same evidence twice."*
> Every improvement below is tied to something a judge can see, click, or read.

## Mandatory submission artifacts (gate before any scoring)

| Artifact | Rule | Status |
|---|---|---|
| Public prototype link | "publicly accessible … functional during judging" | ❌ **missing — biggest single risk** |
| Demo video ≤ 5 min | live walkthrough, unlisted/public YouTube | ❌ not produced |
| Slide deck / docs link | architecture, implementation, challenges, roadmap | 🟡 README exists; needs deck form |
| Repo link | code access | ✅ ready |
| AI as key component | rules §AI usage | ✅ met — but must be *visible* to judges |
| Cloud infrastructure | "utilize cloud … in development, deployment or core" | 🟡 Neon is cloud; app itself still local-only |

---

## Criterion 1 — System Design & Architecture (15 pts)

*Excellent = coherent, well justified, supported by prototype evidence.*

**Current evidence:** layered pipeline (ingest → classify → read → extract →
escalate → compare → submit), README diagrams, compose services, clean
separation of `pipeline/` (logic) from `app/` (serving).

**Improvements**

- [ ] **One-page architecture poster** (slide + `plans/ARCHITECTURE.md`):
  components, data flow, interfaces, and *why* — the README diagrams
  exist but aren't framed as justified design decisions.
- [ ] **Write down the 3 key design decisions with reasoning:**
  1. *LLMs read, code decides* — exact-field scoring demands determinism.
  2. *Rules-first classification* — cost/latency + auditable `decided_by`.
  3. *Escalate don't guess* — reliability over coverage (matches the
     scorer's escalation metrics and real ops risk).
- [ ] **Sequence diagram** of a `POST /api/pipeline/run → submit` round-trip
  (exists in README §5 — reuse it in the deck).
- [ ] Explicit dependency/interface list: Neon schema contract, OpenRouter
  JSON contract, scorer submission contract — the "interfaces and
  dependencies" wording judges assess.

## Criterion 2 — Working Core Prototype (25 pts, largest)

*Excellent = core flow works reliably end-to-end.*

**Current evidence:** 520-email pipeline, 5 queues, diff view, review
actions, scorer loop — all working in compose.

**Improvements**

- [ ] **Deploy publicly** — the rubric requires a link judges can open.
  Cheapest path that keeps compose intact: single VM (or Render/Fly) running
  `docker compose up`; alternatively web→Vercel + api→Render, Neon already
  managed. Scorer stays local — it's dev-only, judges don't need it.
- [ ] **Demo-critical UX gaps:**
  - field-level defect override UI (API `override_fields` exists, UI only
    does status-level — judges may test the human-in-the-loop flow);
  - loading/progress state while a run executes (runs are synchronous-ish
    background tasks — show "running…" and auto-refresh);
  - attachment viewer (raw doc text next to extracted fields = instant
    credibility).
- [ ] **Rehearse the golden path**: inbox → email_004 (visible mismatch) →
  Run AI assist → review queue → confirm action → runs page score. Every
  step must survive a live demo (no spinner dead-ends).
- [ ] **Resilience proof:** kill the OpenRouter key mid-demo and the
  pipeline still completes deterministically — that *is* the demo.

## Criterion 3 — Technology Integration (15 pts)

*Excellent = deep, seamless integration; tools used to full potential.*

**Current evidence:** OpenAI SDK→OpenRouter (2 models), Neon async, uv,
pnpm, Docker compose, pypdfium2+vision OCR.

**Improvements**

- [ ] **Make AI visibly load-bearing**, not just present:
  - surface `decided_by` stats on the dashboard ("78% decided by rules,
    22% needed the model" — shows intentional AI use, not wrapper-ness);
  - per-field extraction provenance (which line/model produced each value);
  - the vision-OCR path demonstrated on a real scanned PDF — synthesize one
    from a known BL, watch the model read it (strong "full potential" signal).
- [ ] **LLM cache by content hash** (`llm_cache` table) + bounded
  concurrency semaphore — turns the rate-limit caveat into an engineering
  story instead of a limitation.
- [ ] **OpenRouter model fallback chain** (ultra → nano-omni → next free
  model) — we already lived this once (the 12b-vl slug died); codifying it
  shows craftsmanship.
- [ ] `.env.example` + health endpoint that reports LLM/DB connectivity —
  judges poking `/health` see a real system.

## Criterion 4 — Technical Feasibility & Validation (15 pts)

*Excellent = critical assumptions validated with clear evidence + credible
path to completion.*

**Current evidence:** 28 tests (14 golden + 14 anti-overfit), scorer
integration, 1.0 local score, live-verified LLM paths.

**Improvements**

- [ ] **CI workflow** (GitHub Actions): `uv run pytest` + `pnpm build` on
  every push — "validated with clear evidence" made concrete.
- [ ] **Eval report artifact**: after each run, write
  `runs/<id>/scorecard.md` — judge-legible proof of the 46/46 e2e number.
- [ ] **Failure-mode matrix** (one table in docs): model down / rate-limited
  / malformed JSON / unknown label / corrupt PDF / missing pair → observed
  behavior for each (we have evidence for all of them — collect it).
- [ ] **Latency/cost numbers**: emails/sec rules-only vs with-LLM,
  LLM calls per run, quota headroom — feasibility needs numbers, not vibes.
- [ ] **Honest limitation list** in the deck (free-tier quota, single
  dataset, no auth) + the concrete mitigation path — "important limitations
  are understood" is literally the Strong→Excellent wording.

## Criterion 5 — Problem Understanding (10 pts)

*Excellent = strong, well-supported understanding of users/context/need.*

**Improvements**

- [ ] **Persona slide**: shipping-ops exec, ~N doc-checks/day, BL cutoff
  pressure, cost of a finalized-wrong BL — frame every feature as relieving
  a named pain (find email → open 2 docs → compare 7 fields → escalate).
- [ ] **"A day in the inbox" before/after** in the video — 30 seconds of
  the manual process vs one click.
- [ ] Dashboard counters framed in ops language (queue depth, escalations
  awaiting human, defects caught) rather than ML metrics — the dashboard
  already counts; relabel toward the user's job.
- [ ] Show the **4 escalation reasons as business cases** (wrong doc,
  missing pair, unreadable, blank fields) — they map to real ops failures.

## Criterion 6 — Innovation & Solution Approach (10 pts)

*Excellent = original, well justified, clear advantage.*

**Improvements**

- [ ] **Name the differentiation explicitly**: most teams will prompt an
  LLM end-to-end; we use models for perception and code for verdicts —
  that's why we can promise *exact* defect fields and zero hallucinated
  verdicts. One sentence on the slide: "the LLM never decides."
- [ ] **`decided_by` as a feature**: per-decision audit trail of
  rule-vs-model — enterprises ask exactly this question about AI systems.
- [ ] **OCR-assisted escalation** — when a PDF is unreadable we *both*
  escalate (safe) and show what the vision model could extract (capability).
  No other team will demo a corrupt file handled gracefully.
- [ ] Optional differentiator if time: **self-serve synonym table** — the
  label map rendered in settings UI so ops teams extend it without code.

## Criterion 7 — Practical Value & Potential (10 pts)

*Excellent = clear value + credible path to wider use.*

**Improvements**

- [ ] **ROI math on one slide**: N BL checks/day × ~M min manual each
  × loaded hourly cost → hours saved/month; plus risk cost of one missed
  consignee defect. Even rough numbers beat "saves time."
- [ ] **Adoption path**: works on any mailbox export + any SI/BL pair —
  the filename-independent pairing (just built) is the proof point.
  Next: IMAP/Graph connector, more doc pairs (packing list vs invoice),
  SSO + reviewer identities.
- [ ] **Roadmap slide**: prelim (deterministic core + assists) →
  final (cloud deploy, HITL polish, metrics) → post-hackathon (connectors,
  more doc types, learning from reviewer corrections).
- [ ] **Learning loop** (cheap to build, big story): reviewer overrides
  already persist in `reviews` — surface them as "corrections feed" and
  describe how they'd tune thresholds/synonyms over time.

---

## Suggested order (points ÷ effort)

1. **Deploy publicly** — unlocks the mandatory link + sells criterion 2/7.
2. **Field-level override + attachment viewer + run progress** — polish the
   demo surface for criterion 2.
3. **CI + eval report + failure-mode matrix** — criterion 4 is nearly free
   given the tests already exist.
4. **decided_by stats + LLM cache + model fallback chain** — criterion 3
   depth.
5. **Deck + video** (persona, ROI math, golden-path walkthrough) —
   criteria 5–7 are mostly *presentation* of what's already built.
6. Stretch: K8s manifests, synonym self-serve UI, corrections feed.
