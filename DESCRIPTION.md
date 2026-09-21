# DockerOps — Project Description

> **Team name:** brotatoes
> **Project name:** DockerOps — AI copilot for shipping-document operations
> **Event:** Averis × Monash Hackathon 2026
> **Live demo:** https://dockerops.vercel.app
> **API (OpenAPI docs):** https://sdoc-api-969206696114.asia-southeast1.run.app/docs

---

## 1. Team & Project

| | |
|---|---|
| **Team** | brotatoes |
| **Project** | DockerOps |
| **One-liner** | An AI copilot that reads a shipping-operations inbox, verifies every Bill of Lading against its Shipping Instruction, and escalates anything it can't trust — with exact, auditable verdicts. |

**Project summary.** DockerOps automates the most repetitive, error-prone job in shipping operations: checking that a draft Bill of Lading (BL) faithfully reflects the customer's Shipping Instruction (SI). It ingests a real, messy inbox, triages every email into five queues, reads documents in any format (text, PDF, DOCX, XLSX — including image-only scans via vision OCR), extracts the seven fields that must agree, compares them deterministically, and produces one of three verdicts per email: `OK`, `MISMATCH` (with the exact defect fields), or `NEEDS_REVIEW` (with a specific reason). A web dashboard lets human reviewers confirm or override every decision, and every action is persisted to Postgres for a full audit trail.

---

## 2. The Problem — who it affects and why it matters

**Who it affects.** Freight forwarders, shipping lines, and logistics operations teams — the people who process booking confirmations and issue Bills of Lading. Every day their shared inbox fills with emails carrying Shipping Instructions and draft BLs, plus a constant background of SI requests, invoice queries, general correspondence, and spam.

**The manual workflow today.** Before a BL can be issued, an operator must open the SI and the draft BL side by side and check **seven fields by eye**:

`shipper` · `consignee` · `notify_party` · `port_of_loading` · `port_of_discharge` · `container_count` · `gross_weight_kg`

**Why it's hard:**

- **Format chaos.** Documents arrive as `.txt`, `.pdf`, `.docx`, and `.xlsx`. Some PDFs are scans with no text layer at all — a human can read them, a naive parser cannot.
- **Inconsistent labeling.** The same field is labeled differently across carriers and templates: `Port of Loading` vs `Load Port` vs `Port of Shipment`; `Gross Weight (KG)` vs `Gross Wt (kgs)` vs bilingual labels. Fields must be aligned **by meaning, not by header text**.
- **Ambiguous failure modes.** An email might ask for a comparison but attach an invoice instead of a BL, attach nothing, attach a corrupted file, or attach a document with blank fields. Each of these needs a *different* response — none of them should silently produce a wrong answer.

**Why it matters.** A missed mismatch isn't a typo — it becomes a wrong Bill of Lading: customs holds, cargo delays, amendment fees, and disputes over a legal document of title. Meanwhile the checking itself is tedious, high-volume, and exactly the kind of work where tired humans make mistakes. The cost of error is high; the cost of attention is higher.

---

## 3. The Solution

DockerOps turns the inbox into a verification pipeline with a human in the loop:

1. **Triage** — every email is classified into one of five queues: `BL_COMPARISON`, `SI_REQUEST`, `INVOICE_QUERY`, `GENERAL`, `SPAM`. Operators only touch what matters.
2. **Verify** — for BL-check emails, DockerOps reads the SI and BL attachments (any format, including scanned PDFs via a vision model), detects whether each document really is what its filename claims, extracts all seven canonical fields using a label-synonym map, and compares normalized values exactly.
3. **Escalate** — anything that can't be decided safely goes to a human review queue with a reason, not a guess.

**Exact verdicts, not vibes.** Every email ends with a structured verdict:

| Verdict | Meaning |
|---|---|
| `OK` | all 7 fields match (or the email only needed triage) |
| `MISMATCH` | ≥1 field differs — `defect_fields` names exactly which |
| `NEEDS_REVIEW` | undecidable — `review_reason` says why |

Normalization is deliberate: parties and ports are stripped of punctuation/case (`BIGBUYERLLC`), numbers drop comma grouping — so a **0.5 kg difference is a defect, but formatting noise is not**.

---

## 4. How it works — the pipeline

```
 inbox/*.json                 attachments/*
      │                            │
      ▼                            ▼
 ┌─────────┐                ┌──────────┐
 │ INGEST  │───────────────►│ Neon     │  emails + attachment metadata
 └────┬────┘                │ Postgres │
      ▼                     └──────────┘
 ┌───────────┐   rules on subject/body/filenames first,
 │ CLASSIFY  │   LLM only as fallback for no-cue emails
 └────┬──────┘
      │ BL_COMPARISON?        (other categories → verdict, done)
      ▼
 ┌───────────┐   readers for txt · pdf · docx · xlsx ·
 │   READ    │   vision OCR for image-only PDFs
 └────┬──────┘
      ▼ DocText(text, readable)
 ┌───────────┐   title first, body fallback — is this
 │ DETECT    │   really an SI? really a BL?
 │ DOC TYPE  │
 └────┬──────┘
      ▼
 ┌───────────┐   label synonyms → 7 canonical fields
 │ EXTRACT   │   regex first, LLM rescue for unknown layouts
 └────┬──────┘
      ▼ si_fields / bl_fields
 ┌───────────┐   escalate if docs missing / unreadable /
 │ ESCALATE? │   wrong type / blank fields
 └────┬──────┘
      ▼ all clear
 ┌───────────┐
 │ COMPARE   │   normalized exact match, per field
 └────┬──────┘
      ▼
   OK | MISMATCH + defect_fields  →  pipeline_results → submission → scorer
```

### Verdict decision tree

```
BL_COMPARISON?
 ├── no  → OK (triaged only)
 └── yes → SI + BL attachments present?
           ├── no → body asks to COMPARE (not just "send me the BL")?
           │        ├── yes → NEEDS_REVIEW / missing_attachment
           │        └── no  → OK (awaiting docs — not a defect)
           └── yes → both files readable?
                     ├── no → OCR succeeds? → continue : NEEDS_REVIEW / unreadable
                     └── yes → doc types == SI + BL?
                               ├── no → NEEDS_REVIEW / wrong_doc_type
                               └── yes → all 7 fields extracted?
                                         ├── no → NEEDS_REVIEW / missing_value
                                         └── yes → COMPARE → OK | MISMATCH
```

The four escalation reasons cover the real-world failure modes — an invoice mislabeled `*_BL.pdf`, a pair that never arrived, a corrupted or scanned file, a document with blank fields. **Nothing silently produces a wrong answer.** The "awaiting docs" nuance matters too: an email asking us to *send* a BL isn't escalated just because no documents arrived yet.

### Label synonyms (extraction aligned by meaning)

| Canonical field | SI labels | BL labels |
|---|---|---|
| `shipper` | Shipper, Shipper/Exporter | Shipper (Principal or Seller) |
| `consignee` | Consignee | Consignee (Non-Negotiable), To the Order of |
| `notify_party` | Notify Party | Notify, Notify Party/Intermediate Consignee |
| `port_of_loading` | Port of Loading, POL | Load Port, Port of Shipment |
| `port_of_discharge` | Port of Discharge, POD | Discharge Port, Place of Delivery |
| `container_count` | No. of Containers | Total Containers, `3 x 40'HC` → 3 |
| `gross_weight_kg` | Gross Weight (KG) | Gross Wt (kgs), 毛重 bilingual labels |

---

## 5. Core design principle — "LLMs read, code decides"

The AI/code boundary is the architectural spine of DockerOps:

| AI does **perception** | Code does **judgement** |
|---|---|
| Classification fallback (no-cue emails) | Field normalization & comparison — pure Python |
| Extraction fallback (unknown layouts) | Verdicts, escalation, defect-field sets |
| Vision OCR (image-only PDFs) | Audit trail, run accounting, review workflow |

Raw model output **never** decides a verdict. The scoring task requires exact defect-field sets, not plausible-sounding text — so everything after perception is deterministic and reproducible. The pipeline runs to completion with **no LLM API key at all**; the models are strictly opt-in assists.

---

## 6. Technical architecture

```
 browser ──► web (Vercel, public) ──/api/* server-side proxy──► sdoc-api (Cloud Run)
                                                                  │  ├─ Neon Postgres
                                                                  │  ├─ OpenRouter (optional)
                                                                  │  ├─ gs://…-sdoc-uploads (mounted)
                                                                  │  ├─ sdoc-scorer (Cloud Run, IAM-private)
                                                                  │  └─ sdoc-worker (Cloud Run Job, 1 execution per full run)
```

| Component | Technology | Role |
|---|---|---|
| `web` | Next.js 15, React 19, pnpm → Vercel | Dashboard, triaged inbox, field-by-field diff view, review queue, live intake, runs/scoreboard. `/api/*` is proxied **server-side** — the browser never calls the API cross-origin, so the UI works identically on localhost, in compose, or deployed |
| `api` | FastAPI, async SQLAlchemy, Python 3.13, uv → Cloud Run | REST API, pipeline orchestration, Neon access. Same image also runs the Cloud Run **Job** (`pipeline.worker`) so long runs never execute inside a request |
| `scorer` | provided eval service → Cloud Run, **IAM-private** | Scores submissions against private ground truth; only the API's service account may invoke it |
| Neon | managed Postgres | `emails`, `runs`, `pipeline_results`, `reviews` — every verdict and override persisted |
| OpenRouter | managed LLM gateway | free-tier Nemotron text + vision models (opt-in) |

**Data model.** `emails` (sender, subject, body, attachment metadata) → `pipeline_results` (category, who decided — `rule` or `llm` — extracted SI/BL field JSON, doc types, evidence, status, defect fields) → `runs` (per-run stats + scorer response) and `reviews` (confirm / override_status / override_fields, reviewer, timestamp). Latest-run joins power every screen; old runs are kept as the scoreboard and audit trail.

---

## 7. Tech stack — key technologies

**Backend:** FastAPI · async SQLAlchemy · Pydantic DTOs · repository pattern (routes contain zero SQL) · Python 3.13 · `uv`

**Frontend:** Next.js 15 · React 19 · TypeScript · server-side `/api/*` proxy route · `pnpm`

**Data:** Neon Postgres (managed, serverless) · JSONB for extracted fields and evidence

**AI/ML:** OpenRouter free-tier models — `nemotron-3-ultra-550b` (classification/extraction fallback) · `nemotron-3-nano-omni-30b` (vision OCR) · pypdfium2 for PDF page rendering · scikit-learn TF-IDF + logistic-regression spam classifier (trained artifact: `api/ml/models/spam.joblib`)

**Infra:** Docker Compose (local) · Google Cloud Run (API + IAM-private scorer + worker Job) · Vercel (web) · Google Cloud Storage (upload mount) · GitHub Actions CI/CD · Workload Identity Federation (no service-account keys in the repo)

**Safety rails:** reviewer passcode on every write · route-table test that fails any unguarded endpoint · intake caps (4 files, 3 MiB each and total) · model fallback chain · content-hash LLM cache · Cloud Function billing killswitch at **RM40/month**

---

## 8. Implementation details

- **Document readers** — pluggable readers per format (`.txt`, `.pdf`, `.docx`, `.xlsx`) all returning a uniform `DocText(text, readable)`; unreadable PDFs fall through to the vision-OCR reader, which renders pages with pypdfium2 and asks the vision model to transcribe them.
- **Extraction** — a label-synonym engine maps dozens of real-world headers to the 7 canonical fields (block and inline layouts); regex-based parsing first, LLM rescue only when a parse finds zero fields.
- **`llm_json` hardening** — prompt-for-JSON → strip code fences → slice the `{...}` block → pydantic validation → one repair retry → tenacity backoff. Malformed model output degrades gracefully instead of corrupting a verdict.
- **Model fallback chain** — `TEXT_MODEL` plus an ordered `TEXT_MODEL_FALLBACKS` list; a retired slug or rate-limited model is skipped and the call only fails once the whole chain has. (We lost `nemotron-nano-12b-v2-vl:free` to a 404 mid-build — the chain is why that stopped being an incident.)
- **Content-hash cache** — every parsed LLM reply is stored under `.cache/llm` keyed by request hash, so rerunning the same document is free and deterministic.
- **Spam detection** — a measured TF-IDF + logistic-regression pipeline with a selected threshold and dataset fingerprint, retrained via `uv run python -m api.ml.train`; experiment history lives in `api/ml/PERFORMANCE.md`.
- **Review workflow** — reviewers confirm a verdict, override its status, or override extracted fields; overrides write `reviews` rows and take effect **without re-running the pipeline**.
- **Health that means something** — `GET /health` reports what the service can actually reach (Neon round-trip, configured model chain, data directory) and answers 503 when the DB is down — and never calls a model.

---

## 9. Challenges faced

1. **Exactness vs. fluency.** LLMs produce plausible text; the task needs the *exact set* of defect fields. Solution: restrict models to perception and make every judgement deterministic Python.
2. **Free-tier model instability.** A model slug 404'd mid-build and others rate-limit unpredictably. Solution: ordered fallback chain + content-hash cache + all assists off by default.
3. **Image-only PDFs.** Scanned documents have no text layer. Solution: render pages with pypdfium2 and transcribe with a vision model — but if OCR fails, escalate `unreadable` rather than guess.
4. **Label heterogeneity.** The same field appears under many names across carriers. Solution: a curated synonym map aligned by meaning, with LLM extraction as the long-tail rescue.
5. **Cheap-cloud constraints.** A public demo on free/cheap tiers can burn budget fast. Solution: `--max-instances 1`, run caps (1 active, 20/day), and a Cloud Function that disconnects billing at RM40/month.
6. **Long-running work in a request/response world.** Full pipeline runs exceed HTTP timeouts. Solution: a Cloud Run Job (same image) executes runs; the API just schedules and reports.
7. **Demo safety.** Judges need to browse freely but not mutate state. Solution: reads are open, every write is behind a reviewer passcode — enforced by a test, not by convention.

---

## 10. Security & robustness

- **Writes gated by design** — `require_reviewer` checks a passcode (`X-Demo-Passcode`); the web UI exchanges it for a 12-hour HttpOnly cookie. A **route-table test** fails the build if any write route forgets the guard.
- **CI gate** — every push runs `ruff`, `pytest` (64 tests — golden, anti-overfit, LLM-client, health, review; no DB or network needed), `tsc --noEmit`, `next build`, and a container smoke test. Deploy fires only when everything is green.
- **No secrets in the repo** — Workload Identity Federation for deploys; `.env` and `secrets/` git-ignored.
- **Bounded blast radius** — scorer is IAM-private; uploads go to a mounted bucket; joblib model artifacts are only ever loaded from the repo's own trained artifact.
- **Graceful degradation** — Gmail integration, LLM assists, and OCR are all optional; unset config degrades cleanly instead of crashing.

---

## 11. Impact — metrics, results, evidence

Scored by the organizers' **own scorer service against private ground truth** — not our own metric:

| Metric | Result |
|---|---|
| **Final score** (0.30·macro-F1 + 0.20·defect-F1 + 0.50·end-to-end) | **1.00** |
| Stage-1 classification macro-F1 (5 categories) | **1.00** |
| Stage-3 defect F1 | **1.00** |
| End-to-end defects caught | **46/46** |
| Escalation precision & recall | **1.00 — 20/20 review cases, all 4 reasons** |

**What that means for a user:**

- A per-email manual check — opening two documents, eyeballing seven fields — becomes a batch verdict with named defect fields, so fixes start immediately instead of after a second reading.
- Escalation replaces silent failure: the 20 genuinely undecidable emails in the dataset were *all* caught, with the right reason each time.
- Every decision is persisted and auditable — reviewers can confirm, override, and leave a trail, which is what a real ops tool needs to be trusted.

**Suggested measures of success in production:** defect catch rate, reviewer override rate, time-to-verdict, escalation precision/recall over time.

---

## 12. Future roadmap

- **Inbox connectors in production** — Gmail import already works locally (read-only scope, OAuth consent); wire it into the cloud deploy, then Outlook/Exchange.
- **More document types** — packing lists, certificates of origin, commercial invoices; the reader/plugin architecture already supports adding formats.
- **Learning from reviews** — reviewer overrides are structured data; use them to tune extraction thresholds and the spam classifier.
- **Downstream integration** — emit verdicts to TMS/ERP systems and carrier portals; the audit-ready `pipeline_results` schema is already shaped for it.
- **Notifications** — proactive alerts on `MISMATCH`/`NEEDS_REVIEW` instead of polling the queue.

---

## 13. Links

| Resource | URL |
|---|---|
| Live prototype | https://dockerops.vercel.app |
| API / OpenAPI docs | https://sdoc-api-969206696114.asia-southeast1.run.app/docs |
| Slide deck | `pitch/DockerOps-pitch-deck.pptx` |
| Deployment runbook | `docs/deploy.md` |

*Judges can browse the deployment read-only with no login; writes (starting runs, confirming reviews, intake) require the reviewer passcode.*
