# Averis x Monash Hackathon 2026 — Requirements & Plan

**Project:** Shipping Document Verification — "From email inbox to discrepancy report"
**Source docs:** `docs-provided/` (infopack, rules & regulations, problem statement PDF, judging rubrics, sample dataset)

---

## 1. Business Context

A shipping operations team (modelled on APRIL Fine Paper Trading's real inbox) receives a
**shared mailbox** where several kinds of work arrive mixed together:

- Requests to **verify shipping documents** before they are released
- Requests to **prepare new Shipping Instructions (SI)**
- **Invoice / billing questions**
- **General operational updates** (berthing reports, SLA reminders, bot notifications, HR mail)
- **Spam**

Today, a human reads every message, decides what it needs, and — for document checks —
manually compares a **Shipping Instruction (SI)** (the customer's intended shipment details)
against a **draft Bill of Lading (BL)** to catch errors *before* the BL is finalized.

### The pain points (from the problem statement)

1. **Finding the right emails takes time.** Every message must be read and triaged. A
   document-check request that is overlooked never reaches the checking step at all.
2. **Manual comparison is repetitive and error-prone.** Names, ports, quantities and weights
   must be cross-checked across two documents. A missed discrepancy means corrections,
   delays and extra work downstream.
3. **The same information looks different.** One document says `Port of Loading`, the other
   says `Load Port`. The system must align fields by *meaning*, not by header text.

### The business outcome

For every email in the inbox, produce a **clear, actionable result**: what kind of message it
is, and for document checks — whether the draft BL matches the SI, **exactly which fields
differ**, or whether a **human needs to look at it** because the system cannot decide safely.

---

## 2. Product Vision (what we are building)

An **AI-powered inbox copilot for shipping documentation** that:

1. **Reads the inbox** — ingests every email (subject, body, attachments).
2. **Triages automatically** — sorts mail into work queues (doc check / SI prep / billing /
   general / junk).
3. **Verifies documents** — for doc-check requests, reads the SI and BL attachments,
   extracts the 7 key shipment fields, and compares them.
4. **Reports discrepancies** — shows SI value vs BL value side by side for each mismatched
   field, or declares "No mismatch detected".
5. **Escalates honestly** — when input is unreadable, missing, or ambiguous, routes the case
   to a human with the evidence and the reason, instead of guessing.

The brief is deliberately open about *how* this is achieved; the hackathon requires **AI as a
key component** and **meaningful use of cloud infrastructure**.

---

## 3. The Data We Work With

### 3.1 The inbox dataset

- **520 email records** (`inbox/email_001.json` … `email_520.json`). Each record:
  `email_id`, `from`, `subject`, `body`, `attachments[]`.
- **~250 attachment files** (`attachments/email_XXX_SI.*`, `email_XXX_BL.*`) in
  `.txt` (majority), `.pdf`, `.docx`, `.xlsx`.
- Category mix (realistic inbox skew):

  | Category | Count | Share |
  |---|---|---|
  | BL_COMPARISON (doc-check requests) | 220 | 42% |
  | SI_REQUEST (new shipping instruction) | 125 | 24% |
  | INVOICE_QUERY (billing) | 75 | 14% |
  | GENERAL (ops updates, bots, HR) | 60 | 12% |
  | SPAM | 40 | 8% |

- Of the 220 doc-check requests: **124 have both SI+BL attached**, ~94 have no usable pair
  (most are "please send me the draft BL" requests), and **20 are deliberately problematic**
  edge cases that should go to human review.
- Of the comparable pairs: **63 are clean** (all fields match) and **46 contain planted
  discrepancies** (1–2 wrong fields each).

### 3.2 Two ways to access the same data

| Option | How |
|---|---|
| Static bundle | `sdoc-hackathon-bundle/` — read `inbox/` and `attachments/` directly; `loader.py` included; nothing to run. |
| Docker server | `sdoc-hackathon-docker/` — `docker compose up --build` serves the same dataset at `http://localhost:8080` (`GET /emails`, `GET /emails/{id}`, `GET /attachments/{path}`) plus a self-evaluation endpoint `POST /submit`. Ground truth stays private on the server. |

The provided `loader.py` (`Inbox("data")` or `Inbox("http://localhost:8080")`) gives one API
for both.

---

## 4. Feature Requirements (business-first)

### F1 — Automatic email triage

**As an** operations team member, **I want** every incoming email automatically sorted into
the right work queue, **so that** document-check requests are never missed and I don't read
spam.

**Requirement:** classify each of the 520 emails into exactly one of five queues:

| Queue | Business meaning | Real example from the data |
|---|---|---|
| `BL_COMPARISON` | "Check this draft BL against the SI before we release it." The only queue that flows into document verification. | `email_001` — subject `TO CONFIRM DOCS _ 5RSG-00133 _ CALLAO_PERU _ MOORIM SP CO., LTD _ MEDUUD104332`, body: *"Attached are the SI and draft BL for OC 5RSG-00133 (PAPERONE DIGITAL COPIER PAPER). Please check the details and confirm."* |
| `SI_REQUEST` | "Here is / we need a Shipping Instruction." Often contains the full SI inline in the body. Only needs sorting, not comparison. | `email_007` — subject `REQUEST SI _ 5RFR-37631 _ GDANSK_POLAND _ AL GURG STATIONERY LLC _ SIJ1051834`, body contains a complete SI: POL/POD, shipper/consignee/notify blocks, `15X20'GP PAPERBOARD`, `GROSS WT: 354,765 KG`, docs required. No attachments. |
| `INVOICE_QUERY` | Billing questions: missing GR, cancel invoice, THC/local charges, D&D charges, freight totals. | `email_002` — subject `RE_ LOCAL CHARGES FOB - KARGOSMAR - 5AKR-61849 - TELEX RELEASE CHARGES`, body: *"Query on invoice 5250075931: is the THC / local charge included or billed separately?"* |
| `GENERAL` | Everything legitimate but non-actionable for doc checking: update summaries, berthing reports, SLA reminders, RPA bot notifications, outstanding-BL lists, HR mail. | `email_011` — subject `15_01_2026 - UPDATE SUMMARY LE HAVRE V.QI540A`, body: *"Please find attached the list of outstanding BL (BDP SG). Kindly action the pending items."* |
| `SPAM` | Marketing, phishing, prize scams. | `email_015` — from `info@crypto-invest.net`, subject *"Increase your shipping revenue with this ONE weird trick"*. |

**Business nuances the classifier must handle:**

- **Subjects are coded, not clean.** Real subjects look like
  `AFRT - LONG BEACH_US - EVER(EGLV433335384951) - 5RSG-19787 - 5250071809 - EAST BRIGHT FZ-LLC - OA_CFR`
  — department codes (AIE/AFPTME/AFRT/AFEMY), carrier BL numbers, OC refs, payment terms
  (OA/DP/LC/CFR), all concatenated. Classification must use body + sender + subject together.
- **Senders overlap.** Both customers/forwarders (`docs@vitalsolutions.sg`,
  `aziztz@safqa.co.ke`) and internal staff (`@aprilasia.com`, `@april.com.my`) send work mail;
  spam comes from junk domains (`crypto-invest.net`, `webmail-verify.co`).
- **Forwarded threads & banners.** ~60% of doc-check emails quote a previous thread
  (`From: ... Sent: Friday, December 15, 2026 ... Please follow the previous instruction.`),
  and ~30% carry an external-sender `WARNING: This email originated outside of our
  organisation` banner. Neither changes the category.
- **"Send me the BL" ≠ "compare these docs" — but both are BL_COMPARISON.** 91 doc-check
  emails ask staff to *send* the draft BL for checking (e.g. `email_003`: *"Please assist to
  send the draft BL for SIN832764835 for checking asap."*) — no attachments yet. They still
  belong to the doc-check queue but have nothing to compare (business status: effectively
  "awaiting documents", reported as OK in the reference data). Only 5 specific emails where
  a comparison was *explicitly requested but the documents are missing* must escalate (see F5).

### F2 — Document reading (extraction)

**As an** ops team member, **I want** the system to pull the key shipment fields out of
whatever document format was attached, **so that** staff stop re-keying data.

**Requirement:** for each doc-check email with attachments, identify which file is the SI
and which is the BL, then extract the 7 comparison fields:

`shipper · consignee · notify_party · port_of_loading · port_of_discharge · container_count · gross_weight_kg`

**The "same info, different labels" problem (core business challenge):** the SI and BL label
the same field differently. The system must map by meaning:

| Canonical field | Labels seen on SI/BL documents |
|---|---|
| shipper | `Shipper`, `Shipper/Exporter`, `Shipper (Principal or Seller)`, `SHIPPER` |
| consignee | `Consignee`, `Consignee (Non-Negotiable)`, `CONSIGNEE`, `To the Order of` |
| notify_party | `Notify Party`, `Notify`, `Notify Party/Intermediate Consignee`, `NOTIFY PARTY` |
| port_of_loading | `Port of Loading`, `Port of Loading (POL)`, `Load Port`, `POL`, `PORT OF LOADING` |
| port_of_discharge | `Port of Discharge`, `Port of Discharge (POD)`, `Discharge Port`, `POD`, `PORT OF DISCHARGE` |
| container_count | `No. of Containers`, `Total Containers`, `No. of Containers or Packages`, `Container Count` |
| gross_weight_kg | `Gross Weight (KG)`, `Gross Wt (kgs)`, `Gross Weight毛重(KGS)`, `GROSS WEIGHT` |

**Format reality:** ~78% of attachment pairs are plain text; ~22% are real binary formats —
PDFs (BL-instruction layout with a container table), Word `.docx` (bilingual English/Chinese
tables, e.g. `收货人`, `装货港`, `毛重`), and Excel `.xlsx` worksheets. A competitive solution
reads all of them (see §6, advanced stage).

### F3 — SI vs BL comparison

**As an** ops team member, **I want** the draft BL checked field-by-field against the SI (the
SI is the source of truth), **so that** wrong details are caught before the BL is released.

**Requirement:** compare the 7 fields and produce one of three business outcomes:

| Outcome | Meaning |
|---|---|
| **Match — "No mismatch detected"** | All 7 fields agree. Draft can proceed. |
| **Mismatch** | ≥1 field differs. Report exactly which fields, showing SI value vs BL value side by side. |
| **Cannot decide → human review** | Inputs unreadable/missing/wrong/blank — escalate with evidence, never guess. |

**Worked example — `email_004` (a real planted discrepancy):**

- Email: *"Attached are the SI and draft BL for OC 5ALT-01226 (COATED IVORY BOARD). Please
  check the details and confirm."* — attachments `email_004_SI.txt` + `email_004_BL.txt`.
- Extraction (note the label mismatch — `Consignee (Non-Negotiable)` on the SI vs
  `To the Order of` on the BL, same field):

  | Field | SI says | BL says | Result |
  |---|---|---|---|
  | shipper | APRIL FAR EAST (M) SDN BHD | APRIL FAR EAST (M) SDN BHD | match |
  | consignee | EAST BRIGHT FZ-LLC | **UAB NOVAKOPA** | **MISMATCH** |
  | notify_party | EAST BRIGHT FZ-LLC | **UAB NOVAKOPA** | **MISMATCH** |
  | port_of_loading | NANTONG, CHINA | NANTONG, CHINA | match |
  | port_of_discharge | KARACHI, PAKISTAN | KARACHI, PAKISTAN | match |
  | container_count | 6 x 40'HC | 6 x 40'HC | match |
  | gross_weight_kg | 131,058 KG | 131,058 KG | match |

- Correct output: **MISMATCH** on `consignee` + `notify_party` only — flagging extra fields
  or missing one both count against the score.

**Kinds of discrepancies planted in the data** (business-realistic drafting errors):

- Wrong party copied in: consignee/notify/shipper shows a *different real company's* name
  (e.g. UAB NOVAKOPA instead of EAST BRIGHT FZ-LLC)
- Wrong port: a different loading or discharge port entirely (e.g. BUATAN, INDONESIA instead
  of NANTONG, CHINA)
- Container count off by 1–2 (SI: 3 containers, BL: 4)
- Gross weight off by 500–2,000 kg (transposition/rounding-style error)

46 of the comparable pairs carry 1 or 2 such defects; the rest are clean.

### F4 — Discrepancy reporting

**As an** ops team member, **I want** a report that shows which email was checked, whether a
mismatch was found, and exactly what needs attention, **so that** I can act in seconds.

**Requirement:** the output makes it trivially easy to see, per email: the email ID, the
verdict, the differing fields with SI vs BL values side by side. If all seven fields match,
report **"No mismatch detected"** explicitly (a clean bill, not silence).

### F5 — Escalation & human review (reliability)

**As an** ops team member, **I want** the system to ask for help when it can't decide safely —
with the evidence attached — **so that** I trust its "OK" verdicts and never chase false alarms.

**Requirement:** when a doc-check request cannot be completed, mark it **NEEDS_REVIEW** with
a specific reason — never report a confident match/mismatch on bad input. Four business
reasons exist in the data (5 emails each):

| Review reason | When it happens | Real example |
|---|---|---|
| `wrong_doc_type` | The "BL" attachment is actually a Commercial Invoice, Packing List, or Certificate of Origin | `email_501`: body says *"the second attachment is a Commercial Invoice, not the draft BL"*; `email_501_BL.txt` is titled `COMMERCIAL INVOICE` and even ends with `*** THIS IS A COMMERCIAL INVOICE - NOT A SHIPPING INSTRUCTION ***` |
| `missing_attachment` | A comparison was explicitly requested but zero documents — or only the SI — arrived | `email_506`: *"Please compare the SI and draft BL for 070500263211 and confirm (attachments appear to have been dropped)."* — `attachments: []` |
| `unreadable` | File can't be read: scanned image-only PDF, empty file, or corrupt/garbled bytes | `email_511`: *"Attached SI and draft BL … for checking (the BL file will not open). Please advise."* — `email_511_BL.pdf` is a corrupt PDF |
| `missing_value` | SI/BL present but a required field is blank (`???`, `____`, `TBA`, `TBC`, `N/A`, empty) | `email_516`: *"Some SI fields were left blank by the customer"*; SI shows `Gross Weight毛重(KGS): N/A` |

**Critical business distinction:** a *request to send the draft BL* (no attachments, e.g.
`email_003`) is normal work-in-progress mail — **not** an escalation. Escalation is only for
emails that asked for a comparison but the inputs make it impossible. Crying wolf on routine
mail hurts the reliability score as much as missing a real problem.

### F6 — Whole-inbox result & self-evaluation

**As a** team, **I want** a single result covering every email and a way to benchmark our
accuracy, **so that** we can prove the system works.

**Requirement:** produce one record per email (all 520 IDs present), shaped like
`sample_submission.json`:

```json
"email_004": {
  "category": "BL_COMPARISON",
  "status": "MISMATCH",
  "review_reason": null,
  "has_defect": true,
  "defect_fields": ["consignee", "notify_party"]
}
```

- `category` ∈ 5 queues; `status` ∈ `OK | MISMATCH | NEEDS_REVIEW`;
  `review_reason` ∈ `wrong_doc_type | missing_attachment | unreadable | missing_value`
  (required when NEEDS_REVIEW); `has_defect` = true iff MISMATCH; `defect_fields` = exact
  list of differing canonical fields.
- Optional `decided_by: "rule"` per email lets the scoreboard report what share was resolved
  without AI calls (a cost/efficiency signal).
- Submit to `POST /submit` on the local server (or `inbox.submit(...)`) → returns a
  scoreboard without exposing answers. Unlimited resubmissions during development.

---

## 5. How Success Is Measured

### 5.1 Dataset scoreboard (objective)

`final_score = 0.50 × end_to_end + 0.30 × classification_macroF1 + 0.20 × defect_F1`

| Metric | Weight | Business meaning |
|---|---|---|
| **End-to-end** | 50% | Of the truly defective BLs: did we route the email correctly **and** flag the *exact* defect fields? The headline — it measures the full business outcome, not a stage. |
| **Classification macro-F1** | 30% | Did every email land in the right queue, treating all five queues equally (spam matters as much as doc-checks)? |
| **Defect F1** | 20% | On comparable pairs: precision/recall of "this BL has a defect" plus which fields. |
| **Reliability (diagnostic)** | reported | Escalation precision & recall on the 20 NEEDS_REVIEW cases — did we escalate exactly the cases that needed it? |

### 5.2 Judging rubrics (what actually wins the hackathon)

Both rounds score **Technical 70 + Product & Impact 30**:

- **Prelim** (deadline **22 Sep, 12:00**): System Design (15), **Working Core Prototype (25)**,
  Technology Integration (15), Technical Feasibility & Validation (15), Problem Understanding
  (10), Innovation (10), Practical Value (10).
- **Final** (pitch day **26 Sep**): **End-to-End Functionality (25)**, Architecture &
  Scalability (15), Technology Integration (15), Engineering Quality & Robustness (15),
  Solution Effectiveness & User Value (10), UX & Differentiation (10), Impact & Future
  Potential (10).

### 5.3 Hard rules that shape scope

- **AI must be a key component** — no-code submissions rejected; minimum is low-code; a
  semi-working prototype is strongly encouraged for prelims, a working one for finals.
- **Cloud infrastructure must be meaningfully integrated** (development, deployment or core
  function) — solutions without it "may receive significantly reduced scores".
- **Deliverables** (all mandatory, via Google Form): project description, **≤5-minute demo
  video** (unlisted/public YouTube or viewable Drive link; −1 mark per 30s over), public
  **GitHub repo** with setup README, **publicly accessible live prototype**, and **slide
  deck** covering architecture, implementation, challenges, roadmap.

---

## 6. Advanced Stage (where we differentiate)

The baseline (classify → extract from text → compare → report) is the common expectation.
The brief explicitly says the advanced stage is "where you can stand out":

| Advanced challenge | What changes | Our target feature |
|---|---|---|
| **PDF & Word attachments** | Extraction from tables and varied page layouts, incl. bilingual EN/中文 labels | Multi-format document reader: PDF text-layer parsing, DOCX table extraction, XLSX sheet reading |
| **Scanned documents** | Image-only PDFs with no text layer | OCR or vision-capable LLM to read and compare scanned SI/BL |
| **Messier inputs** | Varied labels, formatting noise, misleading subjects, missing attachments | Normalization layer that separates a *real* discrepancy from a *reading/formatting* issue |
| **Reliability & human review** | System can't decide dependably | Review queue UI: case, reason, source evidence shown to a human who confirms/corrects; visible failure handling with retries |

**Product ideas that map to rubric points:**

- **Work-queue dashboard** — the 5 queues as lists; doc-check queue shows verdict badges
  (✓ no mismatch / ⚠ mismatch fields / 🚩 needs review). (UX & Differentiation)
- **Side-by-side field diff view** per email (SI value | BL value | verdict) — the "report"
  the brief asks for. (Solution Effectiveness)
- **Human-in-the-loop review screen** — shows the extracted evidence + reason, lets a person
  confirm/correct, updates the report. (Reliability challenge, Innovation)
- **Audit trail & metrics** — processing status per email, retries, % resolved by rules vs AI
  (`decided_by`), accuracy scoreboard history. (Engineering Quality, Tech Feasibility)
- **Cloud deployment** — live prototype link is mandatory anyway; host the pipeline + UI
  (e.g., serverless API + hosted UI + LLM API for extraction/classification). (AI + cloud
  requirement, Architecture & Scalability)

---

## 7. Build Plan (phased)

**Phase 0 — Recon (hours 0–2).** Unpack bundle; run `loader.py` demo; manually read 10–15
emails across all categories and edge cases; stand up the Docker scoring server; submit the
all-GENERAL `sample_submission.json` to see the baseline scoreboard (~0 score).

**Phase 1 — MVP pipeline (prelim target).**
1. Ingest inbox (files or HTTP via `Inbox`).
2. Classifier → 5 queues (hybrid: rules for obvious cues + LLM fallback; emit `decided_by`).
3. For BL_COMPARISON with 2 attachments: parse `.txt` docs, extract 7 fields
   (label-synonym aware), compare, emit verdict + defect fields.
4. Emit `submission.json` for all 520 IDs; iterate against `/submit` until core flow is
   reliable end-to-end.
5. Minimal UI: queue list + per-email field-diff view.
*Prelim gate: demo video ≤5 min, repo, deployed link, slides.*

**Phase 2 — Advanced document handling.** Add PDF/DOCX/XLSX extraction (the ~22% of pairs
that aren't text); add NEEDS_REVIEW detection for all four reasons (wrong doc type, missing
attachments, unreadable files, blank fields) with evidence capture.

**Phase 3 — Reliability & polish (final target).** Human-review screen with confirm/correct;
scanned-PDF OCR or vision-LLM fallback; retries + visible failure states; accuracy/reliability
dashboard; deploy to cloud; record final demo; tighten slides (architecture, challenges,
roadmap).

---

## 8. Key Risks & Watch-items

- **Exact-field precision matters most** — end-to-end credit requires flagging the *exact*
  defect-field set. Over-flagging (e.g. calling `notify_party` a defect when only
  `consignee` differs) scores zero for that email.
- **Don't escalate routine "send me the BL" mail** — 91 emails have no attachments *by
  design*; only the 5 explicit "compare but docs missing" cases are NEEDS_REVIEW.
- **Misleading subjects** — classify on body+sender too, not subject alone.
- **Weight formatting** — `131,058 KG` vs `131058`; `6 x 40'HC` vs container counts phrased
  differently; normalize before comparing values.
- **Ground truth is private** — score via `/submit` only; treat disagreements by re-reading
  the source docs first (per the brief's advice), and record reasonable decisions.
- **Video clock** — 5:00 max; every 30s over costs 1 mark.

---

## 9. Appendix — Quick Facts

- **Dataset:** 520 emails (001–520); categories 220/125/75/60/40; verdicts 454 OK ·
  46 MISMATCH · 20 NEEDS_REVIEW; ~250 attachments (txt/pdf/docx/xlsx); bundle ==
  `data_v2` content.
- **Reference IDs for testing:** clean pair `email_001`; 2-field mismatch `email_004`;
  SI-in-body `email_007`; invoice query `email_002`; general `email_011`; spam `email_015`;
  "send BL" request `email_003`; edge cases `email_501` (wrong doc), `email_506` (missing),
  `email_511` (unreadable), `email_516` (missing value).
- **Timeline:** workshops 20–21 Sep · prelim submission **22 Sep 12:00** · finalists announced
  24 Sep · final pitch **26 Sep**.
- **Data access:** static bundle `sdoc-hackathon-bundle/` or `docker compose up --build` →
  `http://localhost:8080` (`/emails`, `/emails/{id}`, `/attachments/{path}`,
  `/sample_submission`, `POST /submit`).
