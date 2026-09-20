# Cloud Deployment, Demo Access & Live Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put SDOC Verifier on a public Google Cloud Run URL under a US$5 budget, with passcode-protected writes, a private scorer, live "try your own email" intake with retries, monitoring, and deploy-on-merge.

**Architecture:** The same three images run under docker compose and on Cloud Run. `sdoc-web` (Next.js standalone) proxies `/api/*` to `sdoc-api` (FastAPI) at request time and turns a reviewer cookie into an `X-Demo-Passcode` header. `sdoc-api` scales to zero and hands full pipeline runs to a Cloud Run Job (`sdoc-worker`, same image). It calls the IAM-private `sdoc-scorer` with a metadata-server ID token. Uploads live in a Cloud Storage bucket mounted at `/data/uploads`, so the existing file readers work unchanged.

**Tech Stack:** Python 3.13 + uv, FastAPI, SQLAlchemy async + Neon Postgres, httpx, pytest/pytest-asyncio, Next.js 15 + React 19 + pnpm 10, Docker, bash + gcloud, Google Cloud Run (services + jobs), Artifact Registry, Secret Manager, Cloud Storage, Cloud Monitoring, Cloud Billing budgets, GitHub Actions + Workload Identity Federation.

**Spec:** `docs/superpowers/specs/2026-09-20-cloud-deploy-design.md`

## Global Constraints

- **Repo / branch:** `C:\Users\aloys\Averis Hackathon\secret-hack`, branch `feat/cloud-deploy`. Run every command from the repo root in **Git Bash** unless a step says otherwise.
- **Commit identity:** repo-local config (set in Task 1). Every commit message ends with a blank line and `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. Subjects are imperative sentence case, matching history (e.g. "Add …", "Keep …").
- **Never push** until Task 21 and the user's explicit approval.
- **Test command (T):** `DATA_DIR=docs-provided/problem-statement/sdoc-hackathon-bundle uv run pytest api/tests -q -p no:cacheprovider --basetemp=.pytest-tmp`. The default pytest temp dir is blocked on this machine; `--basetemp` fixes that. Baseline: **64 passed**.
- **Lint (L):** `uv run ruff check api`. It must print `All checks passed!` at the end of every Python task. Ruff config: line length 120, rules `E,F,I,B,UP,SIM`, `B008` ignored. Use `uv run ruff check api --fix` for import order.
- **Web check (W):** `cd web && pnpm install --frozen-lockfile && pnpm exec tsc --noEmit && pnpm build; cd ..`
- **Tests** need no database and no network (the repo's convention). Test files insert the api dir on `sys.path` and import `app.*` / `pipeline.*` with `# noqa: E402`.
- **Python deps:** only one new runtime dependency, `python-multipart` (Task 16). Use `uv add`, which also updates `uv.lock`.
- **pnpm:** `10.34.5`, pinned via `packageManager`. Node 22.
- **Budget:** US$5. Every Cloud Run service scales to zero with request-based billing. Hard caps: web max 2, api max 2, scorer max 1, worker job 1 task / parallelism 1. No load balancer, no VPC connector.
- **Secrets:** the implementer never reads, prints, or copies `.env` or any secret value. `scripts/gcp/set-secrets.sh` and `scripts/gcp/neon-region.sh` are **run by the human operator** (the user).
- **Answer key:** `ground_truth.json` must never be committed again. It lives in git-ignored `secrets/` locally and in Secret Manager (`GROUND_TRUTH`) in the cloud.
- **Names:** services `sdoc-web`, `sdoc-api`, `sdoc-scorer`; job `sdoc-worker`; Artifact Registry repo `sdoc`; bucket `<PROJECT_ID>-sdoc-uploads`; service accounts `sdoc-web`, `sdoc-api`, `sdoc-scorer`, `sdoc-deployer`; secrets `NEON_DB_URI`, `OPENROUTER_API_KEY`, `DEMO_PASSCODE`, `GROUND_TRUTH`; reviewer cookie `sdoc_reviewer`; header `X-Demo-Passcode`; uploads run label `Uploads & retries`.

### Deliberate deviations from the spec (all small, all justified)

| Spec | Plan | Why |
|---|---|---|
| deployer `run.developer` | deployer `run.admin` | `--allow-unauthenticated` and invoker bindings need `run.services.setIamPolicy`, which `run.developer` lacks |
| uptime checks on web `/` and api `/health` | web `/healthz` and api `/livez` | `/` and `/health` query Neon every 5 min; that prevents Neon auto-suspend and can burn the Neon free-tier compute allowance. The process-level checks still keep both services warm |
| uptime/alert policy created by `bootstrap.sh` | separate `monitoring.sh`, run after the first deploy | uptime checks need the service hosts to exist |
| adhoc run label `adhoc` | `Uploads & retries`, finished at creation | the Runs page shows the label, and an unfinished run would disable the "Run inbox checks" button forever |
| no run error column | `runs.error` column + "Failed" badge | a worker that dies must be visible, not "Running" forever |
| — | `scripts/gcp/selftest.sh` in CI | offline tests for the bash scripts (syntax, region mapping, no credential leakage) |
| — | `api/tests/conftest.py` | a developer's `.env` must not change test outcomes (passcode, executor, assist flags) |
| budgets alert only | Task 18b adds a $10 kill switch (Pub/Sub → Cloud Function → unlink billing) | the user asked for a hard stop; armed at 2× the alert budget so it cannot fire during normal judging traffic |
| new project `sdoc-verifier-<hex>` | existing project **`averis-email-system`** (number `969206696114`), billing `015CE1-381F1A-582702`, region `asia-southeast1` | the project already exists with billing linked, and Neon is on `aws ap-southeast-1` |

---

## File Structure

**API (Python)**

| File | Responsibility |
|---|---|
| `api/app/core/config.py` (modify) | new settings: passcode, CORS, executor, GCP ids, scorer auth, uploads, log format |
| `api/app/core/logging.py` (create) | JSON log formatter, trace-header parsing, trace middleware, `configure_logging` |
| `api/app/main.py` (modify) | `/livez`, health fields, CORS from settings, logging + trace middleware |
| `api/app/api/deps.py` (modify) | `require_reviewer` dependency |
| `api/app/api/routes/auth.py` (create) | `GET /api/auth/check` |
| `api/app/api/routes/intake.py` (create) | `POST /api/intake` |
| `api/app/api/routes/emails.py` (modify) | `POST /api/emails/{id}/reprocess` |
| `api/app/api/routes/pipeline.py` (modify) | guards, executor hand-off, llm-assist → POST |
| `api/app/api/routes/review.py` (modify) | guard |
| `api/app/api/router.py` (modify) | mount auth + intake routers |
| `api/app/db/models.py` (modify) | `emails.source`, `runs.error` |
| `api/app/db/session.py` (modify) | idempotent `MIGRATIONS` after `create_all` |
| `api/app/repositories/emails.py` (modify) | `to_record`, dataset-only `list_all`, `create_upload`, upload deletion |
| `api/app/repositories/results.py` (modify) | `email_ids_for_run` |
| `api/app/repositories/runs.py` (modify) | `get_or_create`, `delete`, `fail`; `finish` clears error |
| `api/app/schemas/emails.py` (modify) | `ProcessOutcome` |
| `api/app/schemas/runs.py` (modify) | `RunView.error` |
| `api/app/services/gcp.py` (create) | metadata-server access + ID tokens |
| `api/app/services/executor.py` (create) | inline vs Cloud Run Job execution |
| `api/app/services/processing.py` (create) | process one email into the uploads run (timeout → FAILED) |
| `api/app/services/intake.py` (create) | upload validation, safe names, storage, record building |
| `api/pipeline/verdict.py` (modify) | `failed_result` |
| `api/pipeline/run.py` (modify) | resumable runs + per-email log lines |
| `api/pipeline/submission.py` (modify) | scorer auth header |
| `api/pipeline/worker.py` (create) | Cloud Run Job CLI: `run`, `seed [--reset]` |
| `api/Dockerfile`, `.dockerignore` (modify) | multi-stage, non-root, dataset baked in |
| `api/tests/conftest.py` + 10 new test files | see each task |

**Web (Next.js)**

| File | Responsibility |
|---|---|
| `web/next.config.ts` (modify) | `output: "standalone"`, no rewrites |
| `web/lib/server.ts` (create) | server-only `apiBase`, cookie name, `reviewerUnlocked` |
| `web/app/api/[...path]/route.ts` (create) | runtime API proxy + passcode header |
| `web/app/healthz/route.ts` (create) | liveness |
| `web/app/auth/reviewer/route.ts` (create) | unlock / lock reviewer mode |
| `web/app/components/Reviewer.tsx` (create) | provider, hook, sidebar panel, locked hint |
| `web/app/components/RetryButton.tsx` (create) | Retry / Reprocess |
| `web/app/intake/page.tsx`, `IntakeForm.tsx` (create) | live intake + sample kit |
| `web/public/robots.txt`, `web/public/samples/*` (create) | no indexing; 10 sample files |
| `layout.tsx`, `Navigation.tsx`, `ReviewActions.tsx`, `LlmAssist.tsx`, `RunControls.tsx`, `review/page.tsx`, `emails/[id]/page.tsx`, `runs/page.tsx`, `lib/api.ts`, `globals.css`, `package.json`, `Dockerfile` (modify) | wiring |

**Infra / docs**

| File | Responsibility |
|---|---|
| `docker-compose.yml` (modify) | optional `.env`, uploads volume, healthy-api dependency, scorer key from `secrets/` |
| `.github/workflows/ci.yml` (modify) | container smoke + script selftest |
| `.github/workflows/deploy.yml` (create) | deploy on merge via WIF |
| `scripts/gcp/*.sh`, `*.json` (create) | env parsing, shared names, region, bootstrap, secrets, deploy, smoke, reset, monitoring, selftest |
| `secrets/README.md`, `.gitattributes`, `.gitignore`, `.env.example` | hygiene |
| `docs/deploy.md` (create), `README.md` (modify) | runbook + setup docs |

---

### Task 1: Keep the answer key out of the repo

**Files:**
- Delete: `docs-provided/problem-statement/sdoc-hackathon-docker/data_v2/ground_truth.json`
- Create: `secrets/README.md`, `.gitattributes`
- Modify: `.gitignore`, `docker-compose.yml` (scorer volumes)

**Interfaces:**
- Produces: local answer key path `secrets/ground_truth.json` (git-ignored), used by compose (Task 12) and `set-secrets.sh` (Task 13).

- [ ] **Step 1: Set the repo-local commit identity (not global)**

```bash
git config user.name "AloysiusLimMingZhou"
git config user.email "153439916+AloysiusLimMingZhou@users.noreply.github.com"
```

- [ ] **Step 2: Confirm the problem exists (the failing check)**

Run: `git ls-files | grep -c ground_truth`
Expected: `1`

- [ ] **Step 3: Remove the key from git and ignore the secrets folder**

```bash
git rm -q docs-provided/problem-statement/sdoc-hackathon-docker/data_v2/ground_truth.json
```

Append to `.gitignore`:

```gitignore

# Private files that must never be committed (see secrets/README.md)
secrets/*
!secrets/README.md

# pytest scratch (tests run with --basetemp=.pytest-tmp)
.pytest-tmp/
```

Create `secrets/README.md`:

```markdown
# secrets/

Git-ignored. Files here must never be committed.

- `ground_truth.json` — the organizers' answer key. Only the local scorer uses
  it (`docker compose` mounts it at `/secrets/ground_truth.json`). Copy it from
  `data_v2/ground_truth.json` inside the organizer zip
  (`sdoc-hackathon-docker.zip`). In the cloud it lives in Secret Manager as
  `GROUND_TRUTH` and is only readable by the private scorer.
```

Create `.gitattributes`:

```gitattributes
# bash scripts must keep LF endings on Windows checkouts
*.sh text eol=lf
```

- [ ] **Step 4: Point the compose scorer at the local copy**

In `docker-compose.yml`, replace the scorer's `volumes:` block with:

```yaml
    volumes:
      - ./docs-provided/problem-statement/sdoc-hackathon-docker/data_v2:/data:ro
      # answer key stays out of git: see secrets/README.md
      - ./secrets/ground_truth.json:/secrets/ground_truth.json:ro
```

- [ ] **Step 5: Place the local key and verify it is ignored**

```bash
unzip -p "../sdoc-hackathon-docker.zip" data_v2/ground_truth.json > secrets/ground_truth.json
git ls-files | grep -c ground_truth || true
git check-ignore -v secrets/ground_truth.json
git status --short
```

Expected: the count prints `0`. `check-ignore` names the `.gitignore` rule `secrets/*`. `git status` shows `D  docs-provided/.../ground_truth.json`, `M .gitignore`, `M docker-compose.yml`, `?? .gitattributes`, `?? secrets/` (the README only). `secrets/ground_truth.json` is **not** listed.

- [ ] **Step 6: Commit**

```bash
git add -A .gitignore .gitattributes secrets/README.md docker-compose.yml docs-provided/problem-statement/sdoc-hackathon-docker/data_v2/ground_truth.json
git commit -m "Keep the answer key out of the public repo

The scorer reads it from git-ignored secrets/ locally and from Secret
Manager in the cloud. Scripts keep LF endings on Windows.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Settings, liveness, health report, CORS from env

**Files:**
- Modify: `api/app/core/config.py`, `api/app/main.py`, `.env.example`, `api/tests/test_health.py`
- Create: `api/tests/conftest.py`

**Interfaces:**
- Produces (on `settings`): `demo_passcode: str`, `cors_origins: str`, `run_executor: str` (`"inline"` | `"cloudrun-job"`), `gcp_project_id: str`, `gcp_region: str`, `worker_job: str` (default `"sdoc-worker"`), `scorer_auth: str` (`"none"` | `"gcp-id-token"`), `uploads_subdir: str` (default `"uploads"`), `log_format: str` (`"text"` | `"json"`), and properties `cors_origin_list -> list[str]` and `uploads_root -> Path`.
- Produces: `GET /livez -> {"ok": true}`. `/health` gains `writes_protected: bool` and `run_executor: str`.

- [ ] **Step 1: Add the test-isolation conftest**

Create `api/tests/conftest.py`:

```python
"""Test isolation: a developer's .env must not change how the suite behaves."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _baseline_settings(monkeypatch):
    monkeypatch.setattr(settings, "demo_passcode", "")
    monkeypatch.setattr(settings, "run_executor", "inline")
    monkeypatch.setattr(settings, "scorer_auth", "none")
    monkeypatch.setattr(settings, "log_format", "text")
    monkeypatch.setattr(settings, "enable_llm_classify", False)
    monkeypatch.setattr(settings, "enable_llm_fill", False)
    monkeypatch.setattr(settings, "enable_vision_ocr", False)
```

- [ ] **Step 2: Write the failing tests**

In `api/tests/test_health.py`, change the import line `from app.core.config import settings  # noqa: E402` to:

```python
from app.core.config import Settings, settings  # noqa: E402
```

Append:

```python
def test_livez_needs_nothing(client, monkeypatch):
    monkeypatch.setattr(db_session, "SessionLocal", None)
    r = client.get("/livez")

    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_reports_write_protection_and_run_executor(client, monkeypatch):
    async def reachable():
        return {"ok": True, "emails_ingested": 0}

    monkeypatch.setattr(main, "_database_health", reachable)
    monkeypatch.setattr(settings, "demo_passcode", "s3cret-pass")
    monkeypatch.setattr(settings, "run_executor", "cloudrun-job")
    r = client.get("/health")

    assert r.json()["writes_protected"] is True
    assert r.json()["run_executor"] == "cloudrun-job"
    assert "s3cret-pass" not in r.text


def test_writes_are_reported_open_without_a_passcode(client, monkeypatch):
    async def reachable():
        return {"ok": True, "emails_ingested": 0}

    monkeypatch.setattr(main, "_database_health", reachable)
    assert client.get("/health").json()["writes_protected"] is False


def test_cors_origins_and_uploads_root_come_from_settings(tmp_path):
    s = Settings(cors_origins="https://web.example, http://localhost:3000", data_dir=str(tmp_path))

    assert s.cors_origin_list == ["https://web.example", "http://localhost:3000"]
    assert s.uploads_root == tmp_path / "uploads"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `T` with `api/tests/test_health.py` in place of `api/tests`
Expected: FAIL. `/livez` returns 404, `writes_protected` raises KeyError, and `Settings` has no field `cors_origins`.

- [ ] **Step 4: Implement the settings**

In `api/app/core/config.py`, add after `enable_vision_ocr: bool = False`:

```python

    # demo access: an empty passcode leaves writes open (local dev only)
    demo_passcode: str = ""
    cors_origins: str = "http://localhost:3000"

    # where full pipeline runs execute: "inline" (api process) or
    # "cloudrun-job" (a Cloud Run Job execution per run)
    run_executor: str = "inline"
    gcp_project_id: str = ""
    gcp_region: str = ""
    worker_job: str = "sdoc-worker"

    # "gcp-id-token" when the scorer is an IAM-private Cloud Run service
    scorer_auth: str = "none"

    # live-intake files land in DATA_DIR/UPLOADS_SUBDIR/<email_id>/
    uploads_subdir: str = "uploads"
    log_format: str = "text"  # "json" => Cloud Logging structured lines
```

Add after the `resolved_data_dir` property:

```python

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def uploads_root(self) -> Path:
        return Path(self.resolved_data_dir) / self.uploads_subdir
```

- [ ] **Step 5: Implement `/livez`, the health fields, and CORS from settings**

In `api/app/main.py`, replace `allow_origins=["http://localhost:3000"],` with `allow_origins=settings.cors_origin_list,`.

Add before `@app.get("/health")`:

```python
@app.get("/livez")
async def livez():
    """Liveness only: the process is up. Never touches the database."""
    return {"ok": True}


```

In `health()`, add these two keys to `payload` directly after `"status": ...,`:

```python
        "writes_protected": bool(settings.demo_passcode),
        "run_executor": settings.run_executor,
```

- [ ] **Step 6: Document the new knobs**

Replace `.env.example` entirely with:

```dotenv
# Copy to .env — everything here has a working default except the secrets.

# --- required -------------------------------------------------------------
NEON_DB_URI=            # postgres connection string (Neon, sslmode=require)
OPENROUTER_API_KEY=     # only needed for the opt-in AI assists

# --- data -----------------------------------------------------------------
# Relative paths resolve from the repo root, not the working directory.
DATA_DIR=docs-provided/problem-statement/sdoc-hackathon-bundle
# UPLOADS_SUBDIR=uploads     # live-intake files land in DATA_DIR/UPLOADS_SUBDIR

# --- demo access ------------------------------------------------------------
# Empty => write actions are open (local dev). Always set it on a public deploy.
DEMO_PASSCODE=
# CORS_ORIGINS=http://localhost:3000

# --- AI assists (off => runs are fully deterministic) ---------------------
ENABLE_LLM_CLASSIFY=false   # model fallback when the rules find no cue
ENABLE_LLM_FILL=false       # model fill-in for fields the parser missed
ENABLE_VISION_OCR=false     # vision model on image-only PDFs

# --- models ---------------------------------------------------------------
# Comma-separated fallbacks; tried in order when the primary is dead or
# rate-limited. Responses are cached by request hash, so reruns are free.
# TEXT_MODEL=
# TEXT_MODEL_FALLBACKS=
# VISION_MODEL=
# VISION_MODEL_FALLBACKS=
# ENABLE_LLM_CACHE=true
# LLM_CACHE_DIR=.cache/llm

# --- pipeline runs ----------------------------------------------------------
# inline runs inside the api process; cloudrun-job hands each run to a
# Cloud Run Job execution (scripts/gcp/deploy.sh sets these).
# RUN_EXECUTOR=inline
# GCP_PROJECT_ID=
# GCP_REGION=
# WORKER_JOB=sdoc-worker

# --- services -------------------------------------------------------------
# SCORER_URL=http://localhost:8080   # api:  http://scorer:8000 under compose
# SCORER_AUTH=none                   # gcp-id-token when the scorer is IAM-private
# LOG_FORMAT=text                    # json => Cloud Logging structured lines
```

- [ ] **Step 7: Run the full suite and lint**

Run: `T` then `L`
Expected: `68 passed`, and `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add api/app/core/config.py api/app/main.py api/tests/conftest.py api/tests/test_health.py .env.example
git commit -m "Add deploy settings, a liveness probe and write-protection health

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Reviewer passcode on every write

**Files:**
- Modify: `api/app/api/deps.py`, `api/app/api/router.py`, `api/app/api/routes/pipeline.py`, `api/app/api/routes/review.py`, `web/app/emails/[id]/LlmAssist.tsx`
- Create: `api/app/api/routes/auth.py`, `api/tests/test_auth.py`

**Interfaces:**
- Consumes: `settings.demo_passcode` (Task 2).
- Produces: `require_reviewer(x_demo_passcode: str | None = Header(None)) -> None` in `app.api.deps`, which raises `HTTPException(401)`. `GET /api/auth/check` returns 204 when allowed and 401 otherwise. AI assist becomes `POST /api/pipeline/llm-assist/{email_id}`. **Rule for later tasks:** every new `POST/PUT/PATCH/DELETE` route under `/api` must declare `dependencies=[Depends(require_reviewer)]`; `test_every_write_route_requires_the_passcode` enforces it.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_auth.py`:

```python
"""Reviewer passcode: reads stay open, every write needs the passcode.

    uv run pytest api/tests/test_auth.py -v
"""
import sys
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main  # noqa: E402
from app.api.deps import require_reviewer  # noqa: E402
from app.core.config import settings  # noqa: E402

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@pytest.fixture
def client():
    return TestClient(main.app)


def test_open_when_no_passcode_is_configured(client):
    assert client.get("/api/auth/check").status_code == 204


@pytest.mark.parametrize("headers", [{}, {"X-Demo-Passcode": "wrong"}, {"X-Demo-Passcode": ""}])
def test_rejects_a_missing_or_wrong_passcode(client, monkeypatch, headers):
    monkeypatch.setattr(settings, "demo_passcode", "harbour-42")
    r = client.get("/api/auth/check", headers=headers)

    assert r.status_code == 401
    assert "passcode" in r.json()["detail"].lower()


def test_accepts_the_right_passcode(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_passcode", "harbour-42")
    assert client.get("/api/auth/check", headers={"X-Demo-Passcode": "harbour-42"}).status_code == 204


def _guarded(route: APIRoute) -> bool:
    return any(d.call is require_reviewer for d in route.dependant.dependencies)


def test_every_write_route_requires_the_passcode():
    writes = [r for r in main.app.routes
              if isinstance(r, APIRoute) and r.path.startswith("/api") and r.methods & WRITE_METHODS]
    assert writes, "expected write routes under /api"
    assert [r.path for r in writes if not _guarded(r)] == []


def test_model_assist_is_a_post():
    routes = {(r.path, m) for r in main.app.routes if isinstance(r, APIRoute) for m in r.methods}
    assert ("/api/pipeline/llm-assist/{email_id}", "POST") in routes
    assert ("/api/pipeline/llm-assist/{email_id}", "GET") not in routes


def test_a_write_without_the_passcode_is_refused_before_any_work(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_passcode", "harbour-42")
    assert client.post("/api/pipeline/run").status_code == 401
```

- [ ] **Step 2: Run to verify failure**

Run: `T` with `api/tests/test_auth.py`
Expected: FAIL with `ImportError: cannot import name 'require_reviewer'`.

- [ ] **Step 3: Implement the dependency**

Replace `api/app/api/deps.py` with:

```python
"""Shared API dependencies."""
import hmac
from collections.abc import AsyncIterator

from fastapi import Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..db.session import SessionLocal


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as s:
        yield s


def require_reviewer(x_demo_passcode: str | None = Header(default=None)) -> None:
    """Gate for writes and quota-spending calls. Open when no passcode is
    configured (local dev); otherwise X-Demo-Passcode must match."""
    expected = settings.demo_passcode
    if not expected:
        return
    if not x_demo_passcode or not hmac.compare_digest(x_demo_passcode.encode(), expected.encode()):
        raise HTTPException(401, "Reviewer passcode required. Unlock reviewer mode to make changes.")
```

Create `api/app/api/routes/auth.py`:

```python
from fastapi import APIRouter, Depends, Response

from ..deps import require_reviewer

router = APIRouter()


@router.get("/auth/check", status_code=204, dependencies=[Depends(require_reviewer)])
async def check_passcode() -> Response:
    """204 when the caller may write, 401 otherwise. The web app uses it to
    decide whether reviewer mode is unlocked."""
    return Response(status_code=204)
```

Replace `api/app/api/router.py` with:

```python
"""Top-level API router — routes are thin HTTP adapters over
repositories/services; no SQL or business logic lives here."""
from fastapi import APIRouter

from .routes import auth, emails, pipeline, review

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(emails.router)
api_router.include_router(pipeline.router)
api_router.include_router(review.router)
```

- [ ] **Step 4: Guard the existing write routes**

In `api/app/api/routes/pipeline.py`:
- Change `from ..deps import get_db  # noqa: E402` to `from ..deps import get_db, require_reviewer  # noqa: E402`.
- Change `@router.post("/pipeline/run", response_model=RunStarted)` to `@router.post("/pipeline/run", response_model=RunStarted, dependencies=[Depends(require_reviewer)])`.
- Change `@router.post("/export/submit")` to `@router.post("/export/submit", dependencies=[Depends(require_reviewer)])`.
- Change `@router.get("/pipeline/llm-assist/{email_id}")` to `@router.post("/pipeline/llm-assist/{email_id}", dependencies=[Depends(require_reviewer)])`.

In `api/app/api/routes/review.py`:
- Change `from ..deps import get_db` to `from ..deps import get_db, require_reviewer`.
- Change `@router.post("/review/{result_id}", response_model=ReviewOutcome)` to `@router.post("/review/{result_id}", response_model=ReviewOutcome, dependencies=[Depends(require_reviewer)])`.

In `web/app/emails/[id]/LlmAssist.tsx`, change:

```tsx
    try { setData(await request<Record<string, unknown>>(`/api/pipeline/llm-assist/${emailId}`)); }
```

to:

```tsx
    try { setData(await request<Record<string, unknown>>(`/api/pipeline/llm-assist/${emailId}`, { method: "POST" })); }
```

- [ ] **Step 5: Run tests and lint**

Run: `T` then `L`
Expected: `76 passed`; `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add api/app/api web/app/emails/[id]/LlmAssist.tsx api/tests/test_auth.py
git commit -m "Require a reviewer passcode for every write

Reads stay open for judges. AI assist becomes a POST because it spends
model quota.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Upload-aware data model and resumable runs

**Files:**
- Modify: `api/app/db/models.py`, `api/app/db/session.py`, `api/app/repositories/emails.py`, `api/app/repositories/results.py`, `api/app/repositories/runs.py`, `api/app/schemas/runs.py`, `api/pipeline/verdict.py`, `api/pipeline/run.py`, `api/app/api/routes/pipeline.py`, `api/tests/test_runs.py`
- Create: `api/tests/test_repositories.py`

**Interfaces:**
- Produces:
  - `Email.source` (`"dataset"` | `"upload"`) and `Run.error: str | None`; `session.MIGRATIONS: tuple[str, ...]`.
  - `emails_repo.to_record(email) -> dict` with keys `email_id, from, subject, body, attachments`.
  - `emails_repo.list_all_statement(email_ids: list[str] | None, source: str | None)`.
  - `emails_repo.list_all(s, email_ids=None, source="dataset")`.
  - `emails_repo.create_upload(s, record: dict) -> Email`.
  - `emails_repo.upload_delete_statements() -> list` (reviews, results, emails).
  - `emails_repo.delete_uploads(s) -> list[str]`.
  - `results_repo.email_ids_for_run(s, run_id) -> set[str]`.
  - `runs_repo.get_or_create(s, label) -> Run` (finished at creation).
  - `runs_repo.delete(s, run_id) -> None`.
  - `runs_repo.fail(s, run, error: str) -> None`. `runs_repo.finish` now also clears `error`.
  - `RunView.error: str | None`.
  - `pipeline.verdict.failed_result(email_id: str, error: BaseException) -> dict`.
  - `run_pipeline` skips emails that already have a result in the run.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_repositories.py`:

```python
"""Repository helpers and schema migrations, checked without a database."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import session as db_session  # noqa: E402
from app.repositories import emails as emails_repo  # noqa: E402


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_upload_cleanup_touches_only_uploaded_emails_in_fk_order():
    reviews, results, emails = (_sql(s) for s in emails_repo.upload_delete_statements())

    assert reviews.startswith("DELETE FROM reviews")
    assert results.startswith("DELETE FROM pipeline_results")
    assert emails.startswith("DELETE FROM emails")
    for sql in (reviews, results, emails):
        assert "emails.source = 'upload'" in sql


def test_full_runs_only_see_dataset_emails():
    sql = _sql(emails_repo.list_all_statement(["email_004"], "dataset"))
    assert "emails.source = 'dataset'" in sql
    assert "emails.email_id IN ('email_004')" in sql
    assert "source" not in _sql(emails_repo.list_all_statement(None, None))


def test_to_record_matches_the_inbox_json_shape():
    row = SimpleNamespace(email_id="upload_20260920_a1b2c3", sender="ops@example.com",
                          subject="Check", body="Hi", attachments=None)
    assert emails_repo.to_record(row) == {
        "email_id": "upload_20260920_a1b2c3", "from": "ops@example.com",
        "subject": "Check", "body": "Hi", "attachments": [],
    }


@pytest.mark.asyncio
async def test_init_db_adds_new_columns_idempotently(monkeypatch):
    executed = []

    class Conn:
        async def run_sync(self, fn):
            executed.append("create_all")

        async def execute(self, stmt):
            executed.append(str(stmt))

    class Begin:
        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(db_session, "engine", SimpleNamespace(begin=lambda: Begin()))
    await db_session.init_db()

    assert executed[0] == "create_all"
    assert all("IF NOT EXISTS" in sql for sql in executed[1:])
    assert any("emails ADD COLUMN IF NOT EXISTS source" in sql for sql in executed)
    assert any("runs ADD COLUMN IF NOT EXISTS error" in sql for sql in executed)
```

In `api/tests/test_runs.py`, add this line inside `test_run_publishes_progress_and_survives_bad_email`, directly after the `monkeypatch.setattr(run.runs_repo, "finish", finish)` line:

```python
    monkeypatch.setattr(run.results_repo, "email_ids_for_run", AsyncMock(return_value=set()))
```

Append to `api/tests/test_runs.py`:

```python
@pytest.mark.asyncio
async def test_run_resumes_without_duplicating_results(monkeypatch):
    row = SimpleNamespace(id=uuid.uuid4(), stats=None)
    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(run, "SessionLocal", lambda: session)
    monkeypatch.setattr(run.runs_repo, "get", AsyncMock(return_value=row))
    monkeypatch.setattr(run.runs_repo, "finish", AsyncMock())
    monkeypatch.setattr(run.results_repo, "email_ids_for_run", AsyncMock(return_value={"email_0"}))
    emails = [SimpleNamespace(email_id=f"email_{i}", sender="ops", subject="Check BL",
                              body="", attachments=[]) for i in range(2)]
    monkeypatch.setattr(run.emails_repo, "list_all", AsyncMock(return_value=emails))
    process = MagicMock(return_value={"email_id": "email_1", "status": "OK"})
    monkeypatch.setattr(run, "process_email", process)
    add = AsyncMock()
    monkeypatch.setattr(run.results_repo, "add", add)
    monkeypatch.setattr(run.results_repo, "stats_by_category_status", AsyncMock(return_value={}))

    await run.run_pipeline(run_id=str(row.id))

    assert process.call_count == 1
    assert process.call_args.args[0]["email_id"] == "email_1"
    add.assert_awaited_once()


def test_a_crash_becomes_a_visible_failed_result():
    from pipeline.verdict import failed_result

    r = failed_result("email_9", ValueError("bad pdf"))
    assert (r["status"], r["error"], r["defect_fields"]) == ("FAILED", "ValueError: bad pdf", [])
```

- [ ] **Step 2: Run to verify failure**

Run: `T` with `api/tests/test_repositories.py api/tests/test_runs.py`
Expected: FAIL. `upload_delete_statements`, `list_all_statement`, `to_record`, `email_ids_for_run` and `failed_result` are missing, and `MIGRATIONS` was not executed.

- [ ] **Step 3: Models and migrations**

In `api/app/db/models.py`, add to `class Email` after `ingested_at`:

```python
    source = Column(Text, nullable=False, server_default="dataset")  # 'dataset' | 'upload'
```

and to `class Run` after `score`:

```python
    error = Column(Text)  # set when a run dies before finishing
```

In `api/app/db/session.py`:
- Change `from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine` to two lines:

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
```

- Replace `init_db` with:

```python
# create_all never alters an existing table; additive columns land here.
MIGRATIONS = (
    "ALTER TABLE emails ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'dataset'",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS error TEXT",
)


async def init_db():
    if engine is None:
        return
    from . import models  # noqa: F401 - register tables

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for ddl in MIGRATIONS:
            await conn.execute(text(ddl))
```

- [ ] **Step 4: Repositories**

In `api/app/repositories/emails.py`:
- Change the import lines to:

```python
from sqlalchemy import delete, desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Email, PipelineResult, Review
```

- Replace `list_all` with:

```python
def to_record(email: Email) -> dict:
    """ORM row -> the dict the pipeline consumes (same keys as inbox JSON)."""
    return {
        "email_id": email.email_id,
        "from": email.sender,
        "subject": email.subject,
        "body": email.body,
        "attachments": email.attachments or [],
    }


def list_all_statement(email_ids: list[str] | None, source: str | None):
    stmt = select(Email).order_by(Email.email_id)
    if source is not None:
        stmt = stmt.where(Email.source == source)
    if email_ids:
        stmt = stmt.where(Email.email_id.in_(email_ids))
    return stmt


async def list_all(s: AsyncSession, email_ids: list[str] | None = None, source: str | None = "dataset"):
    """Batch runs see dataset emails only, so submissions stay exactly the
    scored inbox; uploads are processed one at a time on arrival."""
    return (await s.execute(list_all_statement(email_ids, source))).scalars().all()
```

- Append:

```python
async def create_upload(s: AsyncSession, record: dict) -> Email:
    row = Email(
        email_id=record["email_id"],
        sender=record["from"],
        subject=record["subject"],
        body=record["body"],
        attachments=record["attachments"],
        source="upload",
    )
    s.add(row)
    await s.flush()
    return row


def upload_delete_statements():
    """Reviews -> results -> emails (FK order), scoped to uploaded emails."""
    uploads = select(Email.email_id).where(Email.source == "upload")
    upload_results = select(PipelineResult.id).where(PipelineResult.email_id.in_(uploads))
    return [
        delete(Review).where(Review.result_id.in_(upload_results)),
        delete(PipelineResult).where(PipelineResult.email_id.in_(uploads)),
        delete(Email).where(Email.source == "upload"),
    ]


async def delete_uploads(s: AsyncSession) -> list[str]:
    """Remove every uploaded email with its results and reviews. Returns the
    ids so the caller can delete their files. The caller commits."""
    ids = list((await s.execute(select(Email.email_id).where(Email.source == "upload"))).scalars().all())
    for stmt in upload_delete_statements():
        await s.execute(stmt)
    return ids
```

In `api/app/repositories/results.py`, append:

```python
async def email_ids_for_run(s: AsyncSession, run_id: uuid.UUID) -> set[str]:
    rows = await s.execute(select(PipelineResult.email_id).where(PipelineResult.run_id == run_id))
    return set(rows.scalars().all())
```

Replace `api/app/repositories/runs.py` with:

```python
"""All Run queries."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Run


async def create(s: AsyncSession, label: str) -> Run:
    run = Run(label=label)
    s.add(run)
    await s.flush()
    return run


async def get_or_create(s: AsyncSession, label: str) -> Run:
    """Long-lived run collecting one-off results (uploads, retries). Marked
    finished at creation so it never shows as an in-progress batch."""
    run = (
        await s.execute(select(Run).where(Run.label == label).order_by(Run.started_at).limit(1))
    ).scalar_one_or_none()
    if run is None:
        run = Run(label=label, finished_at=datetime.now(UTC), stats={})
        s.add(run)
        await s.flush()
    return run


async def list_recent(s: AsyncSession, limit: int = 50):
    return (
        await s.execute(select(Run).order_by(desc(Run.started_at)).limit(limit))
    ).scalars().all()


async def get(s: AsyncSession, run_id: str | uuid.UUID) -> Run | None:
    if isinstance(run_id, str):
        run_id = uuid.UUID(run_id)
    return await s.get(Run, run_id)


async def delete(s: AsyncSession, run_id: str | uuid.UUID) -> None:
    run = await get(s, run_id)
    if run is not None:
        await s.delete(run)


async def finish(s: AsyncSession, run: Run, stats: dict) -> None:
    run.stats = stats
    run.error = None
    run.finished_at = func.now()


async def fail(s: AsyncSession, run: Run, error: str) -> None:
    run.error = error[:500]
    run.finished_at = datetime.now(UTC)


async def save_score(s: AsyncSession, run_id: str, score: dict) -> None:
    run = await get(s, run_id)
    if run:
        run.score = score
        await s.commit()
```

In `api/app/schemas/runs.py`, add `error: str | None = None` as the last field of `RunView`, and `error=r.error,` as the last argument in `RunView.from_orm_row`.

- [ ] **Step 5: Visible failures and resumable runs**

Append to `api/pipeline/verdict.py`:

```python
def failed_result(email_id: str, error: BaseException) -> dict:
    """A processing crash, kept as a visible FAILED result instead of lost."""
    return {
        "email_id": email_id, "category": "GENERAL", "decided_by": "rule",
        "status": "FAILED", "review_reason": None, "has_defect": False,
        "defect_fields": [], "si_fields": None, "bl_fields": None,
        "doc_types": None, "evidence": None,
        "error": f"{type(error).__name__}: {error}",
    }
```

Replace `api/pipeline/run.py` with:

```python
"""Batch runner: process emails through the pipeline and persist results.

Resumable: emails that already have a result in the run are skipped, so a
retried worker execution never duplicates rows.

    uv run python -m pipeline.run                 # all dataset emails
    uv run python -m pipeline.run email_004 ...   # subset
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.repositories import emails as emails_repo  # noqa: E402
from app.repositories import results as results_repo  # noqa: E402
from app.repositories import runs as runs_repo  # noqa: E402

from .verdict import failed_result, process_email  # noqa: E402

log = logging.getLogger("sdoc.pipeline")


async def run_pipeline(email_ids: list[str] | None = None, label: str | None = None,
                       run_id: str | None = None) -> str:
    async with SessionLocal() as s:
        run = await runs_repo.get(s, run_id) if run_id else await runs_repo.create(s, label or "manual")
        await s.commit()
        done = await results_repo.email_ids_for_run(s, run.id)
        emails = await emails_repo.list_all(s, email_ids)

        for email in emails:
            if email.email_id in done:
                continue
            rec = emails_repo.to_record(email)
            try:
                r = await asyncio.to_thread(process_email, rec, settings.resolved_data_dir)
            except Exception as e:
                r = failed_result(email.email_id, e)
            await results_repo.add(s, run.id, r)
            await s.flush()
            run.stats = await results_repo.stats_by_category_status(s, run.id)
            await s.commit()
            log.info("processed %s -> %s", email.email_id, r["status"],
                     extra={"run_id": str(run.id), "email_id": email.email_id})

        stats = await results_repo.stats_by_category_status(s, run.id)
        await runs_repo.finish(s, run, stats)
        await s.commit()
    return str(run.id)


if __name__ == "__main__":
    ids = [a for a in sys.argv[1:] if a.startswith("email_")]
    rid = asyncio.run(run_pipeline(email_ids=ids or None))
    print(f"run {rid} complete")
```

In `api/app/api/routes/pipeline.py`, in `llm_assist_email`, replace the whole `rec = { ... }` dict literal with:

```python
    rec = emails_repo.to_record(email)
```

- [ ] **Step 6: Run tests and lint**

Run: `T` then `L`
Expected: `82 passed`; `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add api/app/db api/app/repositories api/app/schemas/runs.py api/pipeline/verdict.py api/pipeline/run.py api/app/api/routes/pipeline.py api/tests/test_repositories.py api/tests/test_runs.py
git commit -m "Track uploaded emails and make runs resumable

Batch runs only see dataset emails, a retried run skips finished emails,
and a dead run records its error.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Structured logs for Cloud Logging

**Files:**
- Create: `api/app/core/logging.py`, `api/tests/test_logging.py`
- Modify: `api/app/main.py`

**Interfaces:**
- Produces: `JsonFormatter(project_id: str = "")`, `parse_trace_header(value: str | None) -> str | None`, `trace_id: ContextVar[str | None]`, `trace_middleware(request, call_next)`, and `configure_logging(fmt: str, project_id: str = "") -> None`, all in `app.core.logging`. Log records may carry `extra={"run_id": ..., "email_id": ...}`.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_logging.py`:

```python
"""JSON log lines that Cloud Logging understands, with request traces."""
import json
import logging
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.logging import (  # noqa: E402
    JsonFormatter,
    configure_logging,
    parse_trace_header,
    trace_id,
    trace_middleware,
)


def _record(msg="processed", **extra):
    record = logging.LogRecord("sdoc.pipeline", logging.INFO, __file__, 1, msg, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_lines_carry_severity_and_run_context():
    line = json.loads(JsonFormatter("proj").format(_record(run_id="r1", email_id="email_004")))
    assert line == {"severity": "INFO", "message": "processed", "logger": "sdoc.pipeline",
                    "run_id": "r1", "email_id": "email_004"}


def test_trace_is_linked_when_the_request_had_one():
    token = trace_id.set("abc123")
    try:
        line = json.loads(JsonFormatter("proj").format(_record()))
    finally:
        trace_id.reset(token)
    assert line["logging.googleapis.com/trace"] == "projects/proj/traces/abc123"


def test_exceptions_are_included():
    try:
        raise ValueError("bad pdf")
    except ValueError:
        record = _record()
        record.exc_info = sys.exc_info()
    assert "ValueError: bad pdf" in json.loads(JsonFormatter().format(record))["exception"]


@pytest.mark.parametrize("header,expected", [
    ("105445aa7843bc8bf206b12000100000/1;o=1", "105445aa7843bc8bf206b12000100000"),
    ("", None),
    (None, None),
])
def test_parse_trace_header(header, expected):
    assert parse_trace_header(header) == expected


def test_middleware_exposes_the_trace_to_the_request():
    app = FastAPI()
    app.middleware("http")(trace_middleware)

    @app.get("/probe")
    async def probe():
        return {"trace": trace_id.get()}

    r = TestClient(app).get("/probe", headers={"X-Cloud-Trace-Context": "t-42/7;o=1"})
    assert r.json() == {"trace": "t-42"}


def test_json_mode_routes_uvicorn_through_the_formatter():
    root, access = logging.getLogger(), logging.getLogger("uvicorn.access")
    saved = (root.handlers[:], root.level, access.handlers[:], access.propagate)
    try:
        configure_logging("json", "proj")
        assert isinstance(access.handlers[0].formatter, JsonFormatter)
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
    finally:
        root.handlers, access.handlers = saved[0], saved[2]
        root.setLevel(saved[1])
        access.propagate = saved[3]
```

- [ ] **Step 2: Run to verify failure**

Run: `T` with `api/tests/test_logging.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.logging'`.

- [ ] **Step 3: Implement**

Create `api/app/core/logging.py`:

```python
"""Logging setup: plain text locally, Cloud Logging JSON in the cloud.

Cloud Run ships each stdout line to Cloud Logging; a JSON line with
`severity` and `logging.googleapis.com/trace` becomes a structured entry
grouped with its request.
"""
import json
import logging
import sys
from contextvars import ContextVar

trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_CONTEXT_FIELDS = ("run_id", "email_id")


class JsonFormatter(logging.Formatter):
    def __init__(self, project_id: str = ""):
        super().__init__()
        self.project_id = project_id

    def format(self, record: logging.LogRecord) -> str:
        entry = {"severity": record.levelname, "message": record.getMessage(), "logger": record.name}
        for field in _CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                entry[field] = value
        trace = trace_id.get()
        if trace and self.project_id:
            entry["logging.googleapis.com/trace"] = f"projects/{self.project_id}/traces/{trace}"
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def parse_trace_header(value: str | None) -> str | None:
    """X-Cloud-Trace-Context: TRACE_ID/SPAN_ID;o=1 -> TRACE_ID"""
    if not value:
        return None
    return value.split("/", 1)[0].strip() or None


async def trace_middleware(request, call_next):
    token = trace_id.set(parse_trace_header(request.headers.get("x-cloud-trace-context")))
    try:
        return await call_next(request)
    finally:
        trace_id.reset(token)


def configure_logging(fmt: str, project_id: str = "") -> None:
    if fmt != "json":
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(project_id))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False
```

In `api/app/main.py`:
- Add the import `from .core.logging import configure_logging, trace_middleware` directly after `from .core.config import settings`.
- Directly after the imports, add:

```python
configure_logging(settings.log_format, settings.gcp_project_id)
```

- Directly after `app.include_router(api_router)`, add:

```python
app.middleware("http")(trace_middleware)
```

- [ ] **Step 4: Run tests and lint**

Run: `T` then `L`
Expected: `90 passed`; `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add api/app/core/logging.py api/app/main.py api/tests/test_logging.py
git commit -m "Emit Cloud Logging JSON with request traces

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Metadata-server tokens and the private scorer

**Files:**
- Create: `api/app/services/gcp.py`, `api/tests/test_scorer_auth.py`
- Modify: `api/pipeline/submission.py`

**Interfaces:**
- Produces: `gcp.METADATA_URL`, `async gcp.access_token(transport=None) -> str`, and `async gcp.id_token(audience: str, transport=None) -> str`. Both raise `httpx.HTTPError` on failure. Also `async submission.scorer_headers() -> dict[str, str]`.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_scorer_auth.py`:

```python
"""Service-to-service auth on Cloud Run, with the metadata server mocked."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings  # noqa: E402
from app.services import gcp  # noqa: E402
from pipeline import submission  # noqa: E402


@pytest.mark.asyncio
async def test_id_token_asks_the_metadata_server_for_the_audience():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["flavor"] = request.headers.get("Metadata-Flavor")
        return httpx.Response(200, text="id-token-123\n")

    token = await gcp.id_token("https://sdoc-scorer.example", transport=httpx.MockTransport(handler))

    assert token == "id-token-123"
    assert seen["url"].startswith(gcp.METADATA_URL + "/identity?audience=")
    assert "sdoc-scorer.example" in seen["url"]
    assert seen["flavor"] == "Google"


@pytest.mark.asyncio
async def test_access_token_reads_the_json_token():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"access_token": "ya29.x", "expires_in": 3599}))
    assert await gcp.access_token(transport=transport) == "ya29.x"


@pytest.mark.asyncio
async def test_metadata_errors_surface():
    with pytest.raises(httpx.HTTPStatusError):
        await gcp.access_token(transport=httpx.MockTransport(lambda r: httpx.Response(404)))


@pytest.mark.asyncio
async def test_no_auth_header_for_a_local_scorer():
    assert await submission.scorer_headers() == {}


@pytest.mark.asyncio
async def test_private_scorer_gets_an_id_token_for_its_own_url(monkeypatch):
    monkeypatch.setattr(settings, "scorer_auth", "gcp-id-token")
    monkeypatch.setattr(settings, "scorer_url", "https://sdoc-scorer-1.asia-southeast1.run.app")
    fetch = AsyncMock(return_value="tok")
    monkeypatch.setattr(submission.gcp, "id_token", fetch)

    assert await submission.scorer_headers() == {"Authorization": "Bearer tok"}
    fetch.assert_awaited_once_with("https://sdoc-scorer-1.asia-southeast1.run.app")
```

- [ ] **Step 2: Run to verify failure**

Run: `T` with `api/tests/test_scorer_auth.py`
Expected: FAIL with `ImportError: cannot import name 'gcp'`.

- [ ] **Step 3: Implement**

Create `api/app/services/gcp.py`:

```python
"""Google metadata-server tokens for service-to-service calls on Cloud Run.

No SDK needed: two GETs against the metadata server, which only exists
inside Google Cloud (tests inject an httpx transport).
"""
import httpx

METADATA_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default"
_HEADERS = {"Metadata-Flavor": "Google"}


async def access_token(transport: httpx.AsyncBaseTransport | None = None) -> str:
    """OAuth token for Google APIs (e.g. starting a Cloud Run Job)."""
    async with httpx.AsyncClient(transport=transport, timeout=5) as c:
        r = await c.get(f"{METADATA_URL}/token", headers=_HEADERS)
        r.raise_for_status()
        return r.json()["access_token"]


async def id_token(audience: str, transport: httpx.AsyncBaseTransport | None = None) -> str:
    """OIDC identity token for calling an IAM-private Cloud Run service."""
    async with httpx.AsyncClient(transport=transport, timeout=5) as c:
        r = await c.get(f"{METADATA_URL}/identity", params={"audience": audience}, headers=_HEADERS)
        r.raise_for_status()
        return r.text.strip()
```

In `api/pipeline/submission.py`:
- Add after `from app.repositories import runs as runs_repo  # noqa: E402`:

```python
from app.services import gcp  # noqa: E402
```

- Add before `async def submit`:

```python
async def scorer_headers() -> dict[str, str]:
    """Bearer ID token when the scorer is an IAM-private Cloud Run service."""
    if settings.scorer_auth != "gcp-id-token":
        return {}
    return {"Authorization": f"Bearer {await gcp.id_token(settings.scorer_url)}"}


```

- In `submit`, change `r = await c.post(f"{settings.scorer_url}/submit", json=sub)` to:

```python
        r = await c.post(f"{settings.scorer_url}/submit", json=sub, headers=await scorer_headers())
```

- [ ] **Step 4: Run tests and lint**

Run: `T` then `L`
Expected: `95 passed`; `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add api/app/services/gcp.py api/pipeline/submission.py api/tests/test_scorer_auth.py
git commit -m "Call the private scorer with a metadata-server ID token

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Hand full runs to a Cloud Run Job

**Files:**
- Create: `api/app/services/executor.py`, `api/tests/test_executor.py`
- Modify: `api/app/api/routes/pipeline.py`

**Interfaces:**
- Consumes: `gcp.access_token` (Task 6), `runs_repo.delete` (Task 4), settings (Task 2).
- Produces: `executor.ExecutorError(RuntimeError)`, `executor.WORKER_ARGS == ["-m", "pipeline.worker"]`, `executor.job_run_url() -> str`, `executor.job_run_body(run_id, email_ids) -> dict`, `async executor.trigger_worker_job(run_id, email_ids, transport=None)`, and `async executor.start_run(run_id, email_ids, background)`. Worker args contract (used by Task 8 and `deploy.sh`): the container command is `python`, and the args are `-m pipeline.worker run --run-id <id> [email_id ...]`.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_executor.py`:

```python
"""Where pipeline runs execute: in-process locally, a Cloud Run Job in the cloud."""
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main  # noqa: E402
from app.api.deps import get_db  # noqa: E402
from app.api.routes import pipeline as pipeline_routes  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services import executor  # noqa: E402


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setattr(settings, "run_executor", "cloudrun-job")
    monkeypatch.setattr(settings, "gcp_project_id", "sdoc-verifier-abc123")
    monkeypatch.setattr(settings, "gcp_region", "asia-southeast1")
    monkeypatch.setattr(settings, "worker_job", "sdoc-worker")


def _metadata_then(run_response):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "metadata.google.internal":
            return httpx.Response(200, json={"access_token": "ya29.test"})
        return run_response

    return calls, httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_inline_runs_in_a_background_task():
    background = MagicMock()
    await executor.start_run("run-1", ["email_004"], background)

    background.add_task.assert_called_once()
    assert background.add_task.call_args.kwargs == {"email_ids": ["email_004"], "run_id": "run-1"}


@pytest.mark.asyncio
async def test_cloud_hands_the_run_to_the_worker_job(cloud, monkeypatch):
    trigger = AsyncMock()
    monkeypatch.setattr(executor, "trigger_worker_job", trigger)
    background = MagicMock()

    await executor.start_run("run-1", None, background)

    trigger.assert_awaited_once_with("run-1", None)
    background.add_task.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_executor_is_an_error(monkeypatch):
    monkeypatch.setattr(settings, "run_executor", "carrier-pigeon")
    with pytest.raises(executor.ExecutorError, match="carrier-pigeon"):
        await executor.start_run("run-1", None, MagicMock())


@pytest.mark.asyncio
async def test_job_request_shape(cloud):
    calls, transport = _metadata_then(httpx.Response(200, json={"name": "operations/1"}))
    await executor.trigger_worker_job("run-1", ["email_004"], transport=transport)

    run_call = calls[-1]
    assert run_call.method == "POST"
    assert str(run_call.url) == ("https://run.googleapis.com/v2/projects/sdoc-verifier-abc123"
                                 "/locations/asia-southeast1/jobs/sdoc-worker:run")
    assert run_call.headers["Authorization"] == "Bearer ya29.test"
    assert json.loads(run_call.content) == {"overrides": {"containerOverrides": [
        {"args": ["-m", "pipeline.worker", "run", "--run-id", "run-1", "email_004"]}]}}


@pytest.mark.asyncio
async def test_job_refusal_becomes_an_executor_error(cloud):
    _, transport = _metadata_then(httpx.Response(403, json={"error": "denied"}))
    with pytest.raises(executor.ExecutorError, match="403"):
        await executor.trigger_worker_job("run-1", None, transport=transport)


@pytest.mark.asyncio
async def test_unreachable_metadata_becomes_an_executor_error(cloud):
    def boom(request):
        raise httpx.ConnectError("no metadata server here")

    with pytest.raises(executor.ExecutorError, match="unreachable"):
        await executor.trigger_worker_job("run-1", None, transport=httpx.MockTransport(boom))


@pytest.mark.asyncio
async def test_missing_cloud_settings_are_reported(monkeypatch):
    monkeypatch.setattr(settings, "gcp_project_id", "")
    with pytest.raises(executor.ExecutorError, match="GCP_PROJECT_ID"):
        await executor.trigger_worker_job("run-1", None)


def test_failed_hand_off_deletes_the_run_and_returns_502(monkeypatch):
    session = SimpleNamespace(commit=AsyncMock())

    async def fake_db():
        yield session

    main.app.dependency_overrides[get_db] = fake_db
    try:
        run_id = uuid.uuid4()
        monkeypatch.setattr(pipeline_routes.runs_repo, "create", AsyncMock(return_value=SimpleNamespace(id=run_id)))
        delete = AsyncMock()
        monkeypatch.setattr(pipeline_routes.runs_repo, "delete", delete)
        monkeypatch.setattr(pipeline_routes.executor, "start_run",
                            AsyncMock(side_effect=executor.ExecutorError("worker job refused the run (403)")))

        r = TestClient(main.app).post("/api/pipeline/run")

        assert r.status_code == 502
        assert "403" in r.json()["detail"]
        delete.assert_awaited_once_with(session, run_id)
    finally:
        main.app.dependency_overrides.clear()
```

- [ ] **Step 2: Run to verify failure**

Run: `T` with `api/tests/test_executor.py`
Expected: FAIL with `ImportError: cannot import name 'executor'`.

- [ ] **Step 3: Implement the executor**

Create `api/app/services/executor.py`:

```python
"""Where a pipeline run executes.

inline        FastAPI BackgroundTasks inside the api process (compose, dev).
cloudrun-job  One Cloud Run Job execution per run. On Cloud Run the api
              scales to zero and throttles CPU after responding, so a
              520-email run must not live inside it.
"""
import httpx
from fastapi import BackgroundTasks

from ..core.config import settings
from . import gcp

RUN_API = "https://run.googleapis.com/v2"
WORKER_ARGS = ["-m", "pipeline.worker"]


class ExecutorError(RuntimeError):
    """The run could not be handed to its executor."""


def job_run_url() -> str:
    return (f"{RUN_API}/projects/{settings.gcp_project_id}/locations/{settings.gcp_region}"
            f"/jobs/{settings.worker_job}:run")


def job_run_body(run_id: str, email_ids: list[str] | None) -> dict:
    args = [*WORKER_ARGS, "run", "--run-id", run_id, *(email_ids or [])]
    return {"overrides": {"containerOverrides": [{"args": args}]}}


async def trigger_worker_job(run_id: str, email_ids: list[str] | None,
                             transport: httpx.AsyncBaseTransport | None = None) -> None:
    if not (settings.gcp_project_id and settings.gcp_region and settings.worker_job):
        raise ExecutorError("GCP_PROJECT_ID, GCP_REGION and WORKER_JOB must be set for RUN_EXECUTOR=cloudrun-job")
    try:
        token = await gcp.access_token(transport)
        async with httpx.AsyncClient(transport=transport, timeout=20) as c:
            r = await c.post(job_run_url(), json=job_run_body(run_id, email_ids),
                             headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as e:
        raise ExecutorError(f"worker job unreachable ({type(e).__name__})") from e
    if r.status_code >= 300:
        raise ExecutorError(f"worker job refused the run ({r.status_code})")


async def start_run(run_id: str, email_ids: list[str] | None, background: BackgroundTasks) -> None:
    if settings.run_executor == "inline":
        from pipeline.run import run_pipeline

        background.add_task(run_pipeline, email_ids=email_ids, run_id=run_id)
    elif settings.run_executor == "cloudrun-job":
        await trigger_worker_job(run_id, email_ids)
    else:
        raise ExecutorError(f"unknown RUN_EXECUTOR {settings.run_executor!r}")
```

- [ ] **Step 4: Use it from the route**

Replace `api/app/api/routes/pipeline.py` with:

```python
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from pipeline.submission import build_submission, submit  # noqa: E402
from pipeline.verdict import llm_assist  # noqa: E402

from ...core.config import settings  # noqa: E402
from ...repositories import emails as emails_repo  # noqa: E402
from ...repositories import results as results_repo  # noqa: E402
from ...repositories import runs as runs_repo  # noqa: E402
from ...schemas.runs import RunDetail, RunStarted, RunView  # noqa: E402
from ...services import executor  # noqa: E402
from ..deps import get_db, require_reviewer  # noqa: E402

router = APIRouter()


@router.post("/pipeline/run", response_model=RunStarted, dependencies=[Depends(require_reviewer)])
async def start_run(
    background: BackgroundTasks,
    email_ids: list[str] | None = None,
    label: str | None = None,
    s: AsyncSession = Depends(get_db),
):
    run = await runs_repo.create(s, label or "manual")
    await s.commit()
    try:
        await executor.start_run(str(run.id), email_ids, background)
    except executor.ExecutorError as e:
        # no orphan "running forever" rows when the hand-off fails
        await runs_repo.delete(s, run.id)
        await s.commit()
        raise HTTPException(502, f"Could not start the run: {e}") from e
    return RunStarted(run_id=str(run.id), started=True, email_ids=email_ids or "all")


@router.get("/runs", response_model=list[RunView])
async def list_runs(s: AsyncSession = Depends(get_db)):
    return [RunView.from_orm_row(r) for r in await runs_repo.list_recent(s)]


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: uuid.UUID, s: AsyncSession = Depends(get_db)):
    run = await runs_repo.get(s, run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    n = await results_repo.count_for_run(s, run_id)
    detail = RunDetail(**RunView.from_orm_row(run).model_dump(), results=n)
    return detail


@router.get("/export/submission")
async def export_submission(run_id: str):
    try:
        sub = await build_submission(run_id)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return JSONResponse(sub)


@router.post("/export/submit", dependencies=[Depends(require_reviewer)])
async def submit_run(run_id: str):
    try:
        return await submit(run_id)
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@router.post("/pipeline/llm-assist/{email_id}", dependencies=[Depends(require_reviewer)])
async def llm_assist_email(email_id: str, s: AsyncSession = Depends(get_db)):
    """On-demand AI view of an email (classification + extraction/OCR).
    Demo endpoint — results are returned, never persisted."""
    email = await emails_repo.get_by_id(s, email_id)
    if email is None:
        raise HTTPException(404, "no such email")
    rec = emails_repo.to_record(email)
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(llm_assist, rec, settings.resolved_data_dir)
```

- [ ] **Step 5: Run tests and lint**

Run: `T` then `L`
Expected: `103 passed`; `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add api/app/services/executor.py api/app/api/routes/pipeline.py api/tests/test_executor.py
git commit -m "Hand full runs to a Cloud Run Job when running in the cloud

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Worker CLI (run, seed, reset)

**Files:**
- Create: `api/pipeline/worker.py`, `api/tests/test_worker.py`

**Interfaces:**
- Consumes: `run_pipeline` (Task 4), `ingest`, `submit`, `emails_repo.delete_uploads`, `runs_repo.create/get/fail` (Task 4), `configure_logging` (Task 5), `settings.uploads_root` (Task 2).
- Produces: CLI `python -m pipeline.worker run --run-id <id> [email_id ...]` and `python -m pipeline.worker seed [--reset]`, plus the functions `parse_args(argv)`, `async run_command(run_id, email_ids) -> str`, `async mark_failed(run_id, error)`, `remove_upload_files(uploads_root: Path, email_ids: list[str])`, `async reset_uploads() -> list[str]`, `async seed(reset: bool) -> str` and `main(argv=None) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_worker.py`:

```python
"""Cloud Run Job entrypoint: run, seed, reset — without a database."""
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings  # noqa: E402
from pipeline import worker  # noqa: E402


def _session(monkeypatch):
    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)
    return session


def test_parse_run_and_seed_args():
    run = worker.parse_args(["run", "--run-id", "abc", "email_004", "email_005"])
    assert (run.command, run.run_id, run.email_ids) == ("run", "abc", ["email_004", "email_005"])
    seed = worker.parse_args(["seed", "--reset"])
    assert (seed.command, seed.reset) == ("seed", True)
    assert worker.parse_args(["seed"]).reset is False


@pytest.mark.asyncio
async def test_a_failed_run_is_marked_and_the_job_fails(monkeypatch):
    monkeypatch.setattr(worker, "run_pipeline", AsyncMock(side_effect=RuntimeError("db gone")))
    mark = AsyncMock()
    monkeypatch.setattr(worker, "mark_failed", mark)

    with pytest.raises(RuntimeError):
        await worker.run_command("rid", [])

    assert mark.await_args.args[0] == "rid"


@pytest.mark.asyncio
async def test_mark_failed_records_the_error(monkeypatch):
    session = _session(monkeypatch)
    row = SimpleNamespace(finished_at=None)
    monkeypatch.setattr(worker.runs_repo, "get", AsyncMock(return_value=row))
    fail = AsyncMock()
    monkeypatch.setattr(worker.runs_repo, "fail", fail)

    await worker.mark_failed("rid", RuntimeError("db gone"))

    fail.assert_awaited_once_with(session, row, "RuntimeError: db gone")
    session.commit.assert_awaited_once()


def test_upload_cleanup_never_leaves_the_uploads_folder(tmp_path):
    root = tmp_path / "uploads"
    (root / "upload_a").mkdir(parents=True)
    (root / "upload_a" / "si.txt").write_text("x")
    (root / "upload_keep").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    worker.remove_upload_files(root, ["upload_a", "../outside", ".", ""])

    assert not (root / "upload_a").exists()
    assert (root / "upload_keep").exists() and outside.exists() and root.exists()


@pytest.mark.asyncio
async def test_reset_removes_only_uploaded_emails(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "uploads" / "upload_a").mkdir(parents=True)
    (tmp_path / "uploads" / "upload_keep").mkdir()
    session = _session(monkeypatch)
    monkeypatch.setattr(worker.emails_repo, "delete_uploads", AsyncMock(return_value=["upload_a"]))

    assert await worker.reset_uploads() == ["upload_a"]

    assert not (tmp_path / "uploads" / "upload_a").exists()
    assert (tmp_path / "uploads" / "upload_keep").exists()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_seed_resets_runs_and_survives_a_scorer_outage(monkeypatch):
    _session(monkeypatch)
    monkeypatch.setattr(worker, "init_db", AsyncMock())
    monkeypatch.setattr(worker, "ingest", AsyncMock(return_value=520))
    run_id = uuid.uuid4()
    monkeypatch.setattr(worker.runs_repo, "create", AsyncMock(return_value=SimpleNamespace(id=run_id)))
    run_command = AsyncMock()
    monkeypatch.setattr(worker, "run_command", run_command)
    reset = AsyncMock()
    monkeypatch.setattr(worker, "reset_uploads", reset)
    monkeypatch.setattr(worker, "submit", AsyncMock(side_effect=ConnectionError("scorer down")))

    assert await worker.seed(reset=True) == str(run_id)

    reset.assert_awaited_once()
    run_command.assert_awaited_once_with(str(run_id), [])
```

- [ ] **Step 2: Run to verify failure**

Run: `T` with `api/tests/test_worker.py`
Expected: FAIL with `ImportError: cannot import name 'worker'`.

- [ ] **Step 3: Implement**

Create `api/pipeline/worker.py`:

```python
"""Cloud Run Job entrypoint for batch pipeline work.

    python -m pipeline.worker run --run-id <uuid> [email_id ...]
    python -m pipeline.worker seed [--reset]

`run` finishes a run the api created (the api hands it over instead of
running it in-process). `seed` loads the dataset, runs every email and scores
the run; `--reset` first removes uploaded emails, their files and reviews.
"""
import argparse
import asyncio
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.config import settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402
from app.repositories import emails as emails_repo  # noqa: E402
from app.repositories import runs as runs_repo  # noqa: E402

from .ingest import ingest  # noqa: E402
from .run import run_pipeline  # noqa: E402
from .submission import submit  # noqa: E402

log = logging.getLogger("sdoc.worker")


async def mark_failed(run_id: str, error: BaseException) -> None:
    async with SessionLocal() as s:
        run = await runs_repo.get(s, run_id)
        if run is not None and run.finished_at is None:
            await runs_repo.fail(s, run, f"{type(error).__name__}: {error}")
            await s.commit()


async def run_command(run_id: str, email_ids: list[str]) -> str:
    try:
        return await run_pipeline(run_id=run_id, email_ids=email_ids or None)
    except Exception as e:
        log.exception("run failed", extra={"run_id": run_id})
        await mark_failed(run_id, e)
        raise


def remove_upload_files(uploads_root: Path, email_ids: list[str]) -> None:
    """Delete each upload folder; ids that would escape the root are ignored."""
    root = uploads_root.resolve()
    for email_id in email_ids:
        target = (root / email_id).resolve()
        if target.parent == root:
            shutil.rmtree(target, ignore_errors=True)


async def reset_uploads() -> list[str]:
    async with SessionLocal() as s:
        ids = await emails_repo.delete_uploads(s)
        await s.commit()
    remove_upload_files(settings.uploads_root, ids)
    log.info("reset removed %d uploaded emails", len(ids))
    return ids


async def seed(reset: bool) -> str:
    await init_db()
    if reset:
        await reset_uploads()
    count = await ingest()
    log.info("ingested %d dataset emails", count)
    async with SessionLocal() as s:
        run = await runs_repo.create(s, "seed")
        await s.commit()
        run_id = str(run.id)
    await run_command(run_id, [])
    try:
        board = await submit(run_id)
        log.info("scored seed run: final_score=%s", board.get("final_score"), extra={"run_id": run_id})
    except Exception:
        # scoring is evaluation, not processing: a missing scorer never fails a seed
        log.warning("scoring skipped", exc_info=True, extra={"run_id": run_id})
    return run_id


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m pipeline.worker")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="finish a run created by the api")
    run.add_argument("--run-id", required=True)
    run.add_argument("email_ids", nargs="*")
    seed_cmd = sub.add_parser("seed", help="ingest the dataset, run everything, score")
    seed_cmd.add_argument("--reset", action="store_true", help="remove uploaded emails first")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_logging(settings.log_format, settings.gcp_project_id)
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "run":
        asyncio.run(run_command(args.run_id, args.email_ids))
    else:
        asyncio.run(seed(args.reset))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests, lint, and a CLI smoke check**

Run: `T` then `L`, then `cd api && uv run python -m pipeline.worker --help; cd ..`
Expected: `109 passed`; `All checks passed!`; usage text listing `{run,seed}`.

- [ ] **Step 5: Commit**

```bash
git add api/pipeline/worker.py api/tests/test_worker.py
git commit -m "Add the worker job CLI for runs, seeding and demo reset

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Production API image

**Prerequisite:** Docker Desktop is running (`docker info` prints a server version).

**Files:**
- Modify: `api/Dockerfile`, `.dockerignore`

**Interfaces:**
- Produces: an image that serves on port 8000 as uid 10001, with the dataset at `/data/{inbox,attachments}`, a writable `/data/uploads`, and working directory `/app/api` (so `python -m pipeline.worker` resolves). There is no ENTRYPOINT, so the worker job overrides the command.

- [ ] **Step 1: Show the current image is unfit (the failing check)**

Run: `docker build -q -f api/Dockerfile -t sdoc-api:before . && docker run --rm --entrypoint sh sdoc-api:before -c 'id -u; ls /data 2>&1 | head -1'`
Expected: `0` (root) and `ls: cannot access '/data'` (no dataset baked in).

- [ ] **Step 2: Rewrite the Dockerfile**

Replace `api/Dockerfile` with:

```dockerfile
# syntax=docker/dockerfile:1
# --- build: resolve locked dependencies into a venv ---------------------------
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# --- runtime: slim python, non-root, dataset baked in -------------------------
FROM python:3.13-slim-bookworm AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    LLM_CACHE_DIR=/tmp/llm-cache
RUN useradd --uid 10001 --create-home app
WORKDIR /app/api
COPY --from=build /app/.venv /app/.venv
COPY api/ /app/api/
COPY docs-provided/problem-statement/sdoc-hackathon-bundle/inbox /data/inbox
COPY docs-provided/problem-statement/sdoc-hackathon-bundle/attachments /data/attachments
# compose mounts a volume here; Cloud Run mounts the uploads bucket here
RUN mkdir -p /data/uploads && chown app:app /data/uploads
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/livez').status == 200 else 1)"]
CMD ["uvicorn", "app.main:app", "--app-dir", "/app/api", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
```

Replace `.dockerignore` with:

```gitignore
# api image context (repo root). The web image uses web/ as its own context.
.git
.github
.venv
.env
.cache
.pytest-tmp
**/__pycache__
web
data
secrets
docs
plans
scripts
# only the participant bundle is baked into the image (at /data)
docs-provided/*
!docs-provided/problem-statement
docs-provided/problem-statement/*
!docs-provided/problem-statement/sdoc-hackathon-bundle
```

- [ ] **Step 3: Build and verify**

```bash
docker build -f api/Dockerfile -t sdoc-api:local .
docker run --rm sdoc-api:local sh -c 'id -u; ls /data/inbox | wc -l; ls /data/attachments | wc -l; test -w /data/uploads && echo uploads-writable'
docker run --rm sdoc-api:local python -m pipeline.worker --help | head -1
docker run -d --name sdoc-api-smoke -p 8000:8000 sdoc-api:local
for i in $(seq 1 30); do curl -fs localhost:8000/livez >/dev/null && break; sleep 1; done
curl -s localhost:8000/livez; echo
curl -s localhost:8000/health | python -c "import json,sys; h=json.load(sys.stdin); print(h['data_dir'], h['writes_protected'])"
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/api/auth/check
docker rm -f sdoc-api-smoke
```

Expected, in order: `10001`, `520`, `250`, `uploads-writable`; `usage: python -m pipeline.worker ...`; `{"ok":true}`; `{'path': '/data', 'present': True} False`; `204`.

- [ ] **Step 4: Commit**

```bash
git add api/Dockerfile .dockerignore
git commit -m "Build a slim non-root API image with the dataset baked in

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Runtime API proxy and standalone web image

**Files:**
- Create: `web/lib/server.ts`, `web/app/api/[...path]/route.ts`, `web/app/healthz/route.ts`, `web/public/robots.txt`
- Modify: `web/next.config.ts`, `web/package.json`, `web/Dockerfile`, `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `REVIEWER_COOKIE = "sdoc_reviewer"` and `apiBase(): string` in `@/lib/server`. Every browser `/api/*` request is forwarded to `${API_URL}/api/*` at request time, with `X-Demo-Passcode` taken from the cookie. `GET /healthz` returns `{"ok":true}`. The image listens on 3000 as the `node` user.

- [ ] **Step 1: Reproduce defect D1 (the failing check)**

```bash
cd web && pnpm install --frozen-lockfile && pnpm build >/dev/null && node -e "console.log(JSON.stringify(require('./.next/routes-manifest.json').rewrites.afterFiles))"; cd ..
```

Expected: a rewrite whose `destination` is `http://localhost:8000/api/:path*`. That value is baked in at build time.

- [ ] **Step 2: Remove the rewrite; standalone output**

Replace `web/next.config.ts` with:

```ts
import type { NextConfig } from "next";

// Browser API calls go through app/api/[...path]/route.ts, which reads
// API_URL per request. (rewrites() would bake the destination in at build.)
const nextConfig: NextConfig = {
  output: "standalone",
};
export default nextConfig;
```

- [ ] **Step 3: Server helpers, proxy, health route**

Create `web/lib/server.ts`:

```ts
// Server-only helpers for route handlers and server components. Never
// import this from a "use client" file: API_URL is a server-side setting.
export const REVIEWER_COOKIE = "sdoc_reviewer";

export function apiBase(): string {
  return process.env.API_URL || "http://localhost:8000";
}
```

Create `web/app/api/[...path]/route.ts`:

```ts
import type { NextRequest } from "next/server";
import { apiBase, REVIEWER_COOKIE } from "@/lib/server";

// Same-origin proxy: the browser only ever talks to this app. API_URL is
// read per request, so one image works under compose and on Cloud Run.
export const dynamic = "force-dynamic";

const PASS_REQUEST = ["content-type", "accept"];
const PASS_RESPONSE = ["content-type", "content-disposition", "cache-control"];
const TIMEOUT_MS = 120_000; // above intake's 90 s processing budget

async function proxy(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const target = `${apiBase()}/api/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  for (const name of PASS_REQUEST) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const passcode = request.cookies.get(REVIEWER_COOKIE)?.value;
  if (passcode) headers.set("x-demo-passcode", passcode);
  const hasBody = !["GET", "HEAD"].includes(request.method);
  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(TIMEOUT_MS),
      ...(hasBody ? { duplex: "half" } : {}),
    } as RequestInit);
    const out = new Headers();
    for (const name of PASS_RESPONSE) {
      const value = upstream.headers.get(name);
      if (value) out.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers: out });
  } catch (err) {
    const timedOut = err instanceof Error && (err.name === "TimeoutError" || err.name === "AbortError");
    return Response.json(
      { detail: timedOut ? "The API did not respond in time. Please try again." : "The API is unreachable right now." },
      { status: timedOut ? 504 : 502 },
    );
  }
}

export { proxy as DELETE, proxy as GET, proxy as PATCH, proxy as POST, proxy as PUT };
```

Create `web/app/healthz/route.ts`:

```ts
// Liveness for Docker and uptime checks: no API or database call.
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ ok: true });
}
```

Create `web/public/robots.txt`:

```text
User-agent: *
Disallow: /
```

- [ ] **Step 4: Pin pnpm and rewrite the Dockerfile**

In `web/package.json`, add this line directly after `"version": "0.1.0",`:

```json
  "packageManager": "pnpm@10.34.5",
```

In `.github/workflows/ci.yml`, delete these two lines under `- uses: pnpm/action-setup@v4`. The action errors when `version` and `packageManager` are both set.

```yaml
        with:
          version: 10
```

Replace `web/Dockerfile` with:

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine AS base
RUN npm install -g pnpm@10.34.5
WORKDIR /app

FROM base AS deps
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM base AS build
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

# --- runtime: standalone server only, non-root --------------------------------
FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build --chown=node:node /app/public ./public
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1:3000/healthz >/dev/null || exit 1
CMD ["node", "server.js"]
```

- [ ] **Step 5: Type-check and build; confirm no rewrite is baked in**

Run: `W`, then `cd web && node -e "console.log(JSON.stringify(require('./.next/routes-manifest.json').rewrites))"; cd ..`
Expected: tsc and build succeed. The rewrites print as `[]` or all-empty arrays, with no `localhost:8000`.

- [ ] **Step 6: Prove the proxy reads API_URL at runtime (fixes D1)**

```bash
cd web
node -e 'require("http").createServer((q, r) => { r.setHeader("content-type", "application/json"); r.end(JSON.stringify({ method: q.method, url: q.url, passcode: q.headers["x-demo-passcode"] || null })); }).listen(9999)' &
STUB=$!
PORT=3999 API_URL=http://127.0.0.1:9999 node .next/standalone/server.js &
WEB=$!
for i in $(seq 1 30); do curl -fs localhost:3999/healthz >/dev/null && break; sleep 1; done
curl -s localhost:3999/healthz; echo
curl -s -X POST -b "sdoc_reviewer=pw" "localhost:3999/api/pipeline/run?label=x"; echo
kill $WEB $STUB
cd ..
```

Expected: `{"ok":true}`, then `{"method":"POST","url":"/api/pipeline/run?label=x","passcode":"pw"}`. If a port is still busy afterwards, run in PowerShell: `Get-NetTCPConnection -LocalPort 3999,9999 -State Listen | % { Stop-Process -Id $_.OwningProcess -Force }`.

- [ ] **Step 7: Build and check the image**

```bash
docker build -t sdoc-web:local web
docker run -d --name sdoc-web-smoke -p 3000:3000 -e API_URL=http://127.0.0.1:9 sdoc-web:local
for i in $(seq 1 30); do curl -fs localhost:3000/healthz >/dev/null && break; sleep 1; done
curl -s localhost:3000/healthz; echo
docker exec sdoc-web-smoke id -u
curl -s -o /dev/null -w '%{http_code}\n' localhost:3000/api/emails
docker rm -f sdoc-web-smoke
docker image ls sdoc-web:local --format '{{.Size}}'
```

Expected: `{"ok":true}`; `1000`; `502` (the API is deliberately unreachable, and the proxy reports it cleanly). The image size is well under 300 MB.

- [ ] **Step 8: Commit**

```bash
git add web/next.config.ts web/lib/server.ts "web/app/api/[...path]/route.ts" web/app/healthz/route.ts web/public/robots.txt web/package.json web/Dockerfile .github/workflows/ci.yml
git commit -m "Proxy API calls at request time and ship a standalone web image

The rewrite baked localhost:8000 into the build, so browser actions
failed under compose. The route handler reads API_URL per request and
forwards the reviewer passcode.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Reviewer mode in the web app

**Files:**
- Create: `web/app/auth/reviewer/route.ts`, `web/app/components/Reviewer.tsx`
- Modify: `web/lib/server.ts`, `web/app/layout.tsx`, `web/app/components/Navigation.tsx`, `web/app/emails/[id]/ReviewActions.tsx`, `web/app/emails/[id]/LlmAssist.tsx`, `web/app/runs/RunControls.tsx`, `web/app/globals.css`

**Interfaces:**
- Consumes: `GET /api/auth/check` (Task 3), `REVIEWER_COOKIE`/`apiBase` (Task 10).
- Produces: `reviewerUnlocked(passcode?: string): Promise<boolean>` in `@/lib/server`. `POST /auth/reviewer {passcode}` sets the cookie and returns 200 (400/401/502 on failure); `DELETE /auth/reviewer` clears it. From `app/components/Reviewer.tsx`: `ReviewerProvider({unlocked, hasPasscode, children})`, `useReviewer(): {unlocked, hasPasscode}`, `ReviewerPanel()`, `LockedHint({action})`.

- [ ] **Step 1: Server-side unlock check**

Append to `web/lib/server.ts`:

```ts

/** 204 from /api/auth/check means this caller may write. */
export async function reviewerUnlocked(passcode: string | undefined): Promise<boolean> {
  try {
    const r = await fetch(`${apiBase()}/api/auth/check`, {
      headers: passcode ? { "x-demo-passcode": passcode } : {},
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    return r.status === 204;
  } catch {
    return false;
  }
}
```

- [ ] **Step 2: Unlock / lock route**

Create `web/app/auth/reviewer/route.ts`:

```ts
import { NextResponse, type NextRequest } from "next/server";
import { apiBase, REVIEWER_COOKIE } from "@/lib/server";

export const dynamic = "force-dynamic";
const TWELVE_HOURS = 60 * 60 * 12;

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const passcode = typeof body?.passcode === "string" ? body.passcode.trim() : "";
  if (!passcode) return NextResponse.json({ detail: "Enter the reviewer passcode." }, { status: 400 });
  let check: Response;
  try {
    check = await fetch(`${apiBase()}/api/auth/check`, {
      headers: { "x-demo-passcode": passcode },
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    return NextResponse.json({ detail: "The API is unreachable right now." }, { status: 502 });
  }
  if (check.status === 401) return NextResponse.json({ detail: "That passcode is not correct." }, { status: 401 });
  if (check.status !== 204) return NextResponse.json({ detail: `Could not verify the passcode (${check.status}).` }, { status: 502 });
  const response = NextResponse.json({ unlocked: true });
  response.cookies.set(REVIEWER_COOKIE, passcode, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: TWELVE_HOURS,
  });
  return response;
}

export async function DELETE() {
  const response = NextResponse.json({ unlocked: false });
  response.cookies.delete(REVIEWER_COOKIE);
  return response;
}
```

- [ ] **Step 3: Reviewer context, panel, hint**

Create `web/app/components/Reviewer.tsx`:

```tsx
"use client";
import { useRouter } from "next/navigation";
import { createContext, useContext, useState } from "react";

type Reviewer = { unlocked: boolean; hasPasscode: boolean };
const ReviewerContext = createContext<Reviewer>({ unlocked: false, hasPasscode: false });

export function ReviewerProvider({ unlocked, hasPasscode, children }: Reviewer & { children: React.ReactNode }) {
  return <ReviewerContext.Provider value={{ unlocked, hasPasscode }}>{children}</ReviewerContext.Provider>;
}

export function useReviewer() {
  return useContext(ReviewerContext);
}

export function LockedHint({ action }: { action: string }) {
  const { unlocked } = useReviewer();
  return unlocked ? null : <p className="locked-hint">Unlock reviewer mode in the sidebar to {action}.</p>;
}

export function ReviewerPanel() {
  const { unlocked, hasPasscode } = useReviewer();
  const router = useRouter();
  const [passcode, setPasscode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function unlock(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const r = await fetch("/auth/reviewer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ passcode }) });
      if (!r.ok) { const body = await r.json().catch(() => null); throw new Error(body?.detail ?? "Could not unlock reviewer mode."); }
      setPasscode(""); router.refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not unlock reviewer mode."); }
    finally { setBusy(false); }
  }
  async function lock() {
    setBusy(true);
    await fetch("/auth/reviewer", { method: "DELETE" }).catch(() => null);
    setBusy(false); router.refresh();
  }
  if (unlocked && !hasPasscode) return <div className="reviewer-panel"><span><span className="status-dot" />Open access</span><small>No reviewer passcode is configured.</small></div>;
  if (unlocked) return <div className="reviewer-panel"><span><span className="status-dot" />Reviewer mode on</span><button className="ghost" onClick={lock} disabled={busy}>Lock</button></div>;
  return <form className="reviewer-panel" onSubmit={unlock}><label htmlFor="reviewer-passcode">Reviewer mode</label><input id="reviewer-passcode" type="password" autoComplete="current-password" placeholder="Passcode" value={passcode} onChange={e => setPasscode(e.target.value)} maxLength={200}/><button disabled={busy || !passcode}>{busy ? "Checking…" : "Unlock"}</button>{error && <small className="error" role="alert">{error}</small>}</form>;
}
```

- [ ] **Step 4: Provide it from the layout and show it in the sidebar**

Replace `web/app/layout.tsx` with:

```tsx
import { cookies } from "next/headers";
import { REVIEWER_COOKIE, reviewerUnlocked } from "@/lib/server";
import "./globals.css";
import Navigation from "./components/Navigation";
import { ReviewerProvider } from "./components/Reviewer";

export const metadata = { title: "SDOC · Document operations", description: "Review shipping documents with source evidence and clear, field-level decisions." };

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const passcode = (await cookies()).get(REVIEWER_COOKIE)?.value;
  const unlocked = await reviewerUnlocked(passcode);
  return <html lang="en"><body><ReviewerProvider unlocked={unlocked} hasPasscode={Boolean(passcode)}><a className="skip-link" href="#main">Skip to content</a><Navigation /><div className="workspace"><header className="topbar"><span>Shipping operations <span className="muted">/ Document verification</span></span><span className="badge dim">SI → Draft BL</span></header><main id="main">{children}</main><footer>SDOC Verifier <span>AI-assisted reading. Deterministic comparison. Human oversight.</span></footer></div></ReviewerProvider></body></html>;
}
```

In `web/app/components/Navigation.tsx`:
- Add `import { ReviewerPanel } from "./Reviewer";` after the `usePathname` import.
- Insert `<ReviewerPanel />` directly before `<div className="sidebar-note">`.

- [ ] **Step 5: Lock the write controls**

Replace `web/app/emails/[id]/ReviewActions.tsx` with:

```tsx
"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { COMPARE_FIELDS, request } from "@/lib/api";
import { FIELDS } from "@/lib/labels";
import { LockedHint, useReviewer } from "../../components/Reviewer";

export default function ReviewActions({ resultId, status, defectFields, canCompare }: { resultId: string; status: string; defectFields: string[]; canCompare: boolean }) {
  const router = useRouter();
  const { unlocked } = useReviewer();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [fields, setFields] = useState(defectFields);
  const [reviewer, setReviewer] = useState("");
  const locked = busy || !unlocked;
  async function act(action: string, payload?: Record<string, unknown>) {
    setBusy(true); setMessage(""); setError("");
    try {
      await request(`/api/review/${resultId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, payload, reviewer: reviewer.trim() || "ops" }) });
      setMessage(action === "confirm" ? "Verdict confirmed. Confirmation keeps the current status." : "Changes saved. The verdict has been updated.");
      router.refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not save the review."); }
    finally { setBusy(false); }
  }
  return <section className="panel review-form"><h2>Reviewer decision</h2><p className="muted">Confirm the finding or correct it after checking the source documents.</p><LockedHint action="record a decision"/><div className="filters"><input aria-label="Reviewer name" placeholder="Reviewer name (optional)" value={reviewer} onChange={e => setReviewer(e.target.value)} maxLength={100}/></div><div className="actions"><button disabled={locked} onClick={() => act("confirm")}>Confirm verdict</button>{status !== "OK" && <button className="ghost" disabled={locked} onClick={() => act("override_status", {status:"OK",review_reason:null})}>Mark clear</button>}{status !== "NEEDS_REVIEW" && <button className="ghost" disabled={locked} onClick={() => act("override_status", {status:"NEEDS_REVIEW",review_reason:"manual_flag"})}>Escalate to review</button>}</div>
    {canCompare && <details><summary>Correct the mismatch fields</summary><p className="muted">Select the fields that differ. Saving no fields marks the result clear.</p><div className="field-options">{COMPARE_FIELDS.map(f => <label key={f}><input type="checkbox" checked={fields.includes(f)} disabled={locked} onChange={e => setFields(previous => e.target.checked ? [...previous,f] : previous.filter(v => v !== f))}/>{FIELDS[f]}</label>)}</div><button className="ghost" disabled={locked} onClick={() => act("override_fields", {defect_fields:fields})}>Save field corrections</button></details>}
    <div aria-live="polite" className="feedback">{busy ? "Saving review…" : message && <span className="success">{message}</span>}</div>{error && <p className="error" role="alert">{error}</p>}
  </section>;
}
```

Replace `web/app/emails/[id]/LlmAssist.tsx` with:

```tsx
"use client";
import { useState } from "react";
import { request } from "@/lib/api";
import { LockedHint, useReviewer } from "../../components/Reviewer";
export default function LlmAssist({ emailId }: { emailId: string }) {
  const { unlocked } = useReviewer();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function run() {
    setBusy(true); setError(""); setData(null);
    try { setData(await request<Record<string, unknown>>(`/api/pipeline/llm-assist/${emailId}`, { method: "POST" })); }
    catch (err) { setError(err instanceof Error ? err.message : "AI assist is unavailable."); }
    finally { setBusy(false); }
  }
  return <section className="panel"><div className="eyebrow">A second reading</div><h2 style={{marginTop:8}}>AI assist</h2><p className="muted">Ask the model to classify and extract details. Suggestions do not change the saved verdict.</p><button className="ghost" style={{marginTop:16}} onClick={run} disabled={busy || !unlocked}>{busy ? "Reading with AI…" : data ? "Run again" : "Run AI assist"}</button><LockedHint action="run the models"/>{error && <p role="alert" className="error">{error}</p>}{data && <details open><summary>Model response</summary><pre>{JSON.stringify(data,null,2)}</pre></details>}</section>;
}
```

Replace `web/app/runs/RunControls.tsx` with:

```tsx
"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { request, Run } from "@/lib/api";
import { LockedHint, useReviewer } from "../components/Reviewer";
export default function RunControls({ running }: { running: boolean }) {
  const router = useRouter();
  const { unlocked } = useReviewer();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [started, setStarted] = useState<string | null>(null);
  useEffect(() => {
    if (!running && !started) return;
    const timer = setInterval(async () => {
      router.refresh();
      if (started) {
        try {
          const run = await request<Run>(`/api/runs/${started}`);
          if (run.finished_at) setStarted(null);
        } catch { setError("Progress is temporarily unavailable. Refresh to check the run."); }
      }
    }, 2500);
    return () => clearInterval(timer);
  }, [running, started, router]);
  async function start() {
    setBusy(true); setError("");
    try {
      const result = await request<{run_id:string}>("/api/pipeline/run?label=Workspace%20run", {method:"POST"});
      setStarted(result.run_id); router.refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not start the run."); }
    finally { setBusy(false); }
  }
  return <div><button onClick={start} disabled={busy || running || !!started || !unlocked}>{busy ? "Starting…" : running || started ? "Processing inbox…" : "Run inbox checks"}</button><LockedHint action="start a run"/>{error && <p className="error" role="alert">{error}</p>}<p className="muted" style={{fontSize:11}}>{running || started ? "Results refresh every few seconds." : "Uses the AI switches configured on the server."}</p></div>;
}
```

Append to `web/app/globals.css`:

```css
.reviewer-panel { display:grid; gap:8px; margin:18px 10px 0; padding:14px 12px; border:1px solid #31504b; border-radius:9px; font-size:12px; color:#d2e2df; }
.reviewer-panel label { font-size:10px; letter-spacing:1.4px; text-transform:uppercase; color:#7ea69e; }
.reviewer-panel input { background:#16383a; border-color:#31504b; color:white; }
.reviewer-panel small { color:#89aaa1; }
.reviewer-panel .error { color:#ffb4a8; }
.locked-hint { font-size:12px; color:var(--warn); margin:10px 0 0; }
```

- [ ] **Step 6: Type-check and build**

Run: `W`
Expected: tsc and build succeed.

- [ ] **Step 7: Verify unlock / lock against a stub API**

```bash
cd web
node -e 'require("http").createServer((q, r) => { if (q.url.startsWith("/api/auth/check")) { r.statusCode = q.headers["x-demo-passcode"] === "pw" ? 204 : 401; return r.end(); } r.end("{}"); }).listen(9999)' &
STUB=$!
PORT=3999 API_URL=http://127.0.0.1:9999 node .next/standalone/server.js &
WEB=$!
for i in $(seq 1 30); do curl -fs localhost:3999/healthz >/dev/null && break; sleep 1; done
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:3999/auth/reviewer -H 'content-type: application/json' -d '{"passcode":"nope"}'
curl -s -D - -o /dev/null -X POST localhost:3999/auth/reviewer -H 'content-type: application/json' -d '{"passcode":"pw"}' | grep -i '^set-cookie'
curl -s -D - -o /dev/null -X DELETE localhost:3999/auth/reviewer | grep -i '^set-cookie'
kill $WEB $STUB
cd ..
```

Expected: `401`. Then `set-cookie: sdoc_reviewer=pw; Path=/; Max-Age=43200; ... HttpOnly; SameSite=lax`. Then a `set-cookie: sdoc_reviewer=; ... Expires=Thu, 01 Jan 1970` line.

- [ ] **Step 8: Commit**

```bash
git add web/lib/server.ts web/app/auth web/app/components web/app/layout.tsx "web/app/emails/[id]/ReviewActions.tsx" "web/app/emails/[id]/LlmAssist.tsx" web/app/runs/RunControls.tsx web/app/globals.css
git commit -m "Add reviewer mode: browse freely, unlock to make changes

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: Compose parity and CI container smoke

**Files:**
- Modify: `docker-compose.yml`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the images from Tasks 9 and 10; `/livez`, `/healthz`, `/api/auth/check`.

- [ ] **Step 1: Rewrite compose**

Replace `docker-compose.yml` with:

```yaml
# SDOC Verifier — web + api + provided scorer (dev/eval).
#   docker compose up --build
# web -> http://localhost:3000   api -> http://localhost:8000   scorer -> :8080
# Same images as Cloud Run; the dataset is baked into the api image.
services:
  api:
    build:
      context: .
      dockerfile: api/Dockerfile
    env_file:
      - path: .env                 # NEON_DB_URI, OPENROUTER_API_KEY, DEMO_PASSCODE
        required: false
    environment:
      DATA_DIR: /data
      SCORER_URL: http://scorer:8000
      CORS_ORIGINS: http://localhost:3000
    volumes:
      - uploads:/data/uploads      # Cloud Run mounts a Cloud Storage bucket here
    ports:
      - "8000:8000"

  web:
    build: ./web
    environment:
      API_URL: http://api:8000     # read per request by the /api proxy and SSR
    ports:
      - "3000:3000"
    depends_on:
      api:
        condition: service_healthy

  scorer:                          # provided eval server; dev-only dependency
    build: ./docs-provided/problem-statement/sdoc-hackathon-docker/server
    volumes:
      - ./docs-provided/problem-statement/sdoc-hackathon-docker/data_v2:/data:ro
      # answer key stays out of git: see secrets/README.md
      - ./secrets/ground_truth.json:/secrets/ground_truth.json:ro
    ports:
      - "8080:8000"

volumes:
  uploads:
```

- [ ] **Step 2: Verify compose end to end (no .env needed)**

```bash
docker compose config -q && echo compose-ok
docker compose up --build -d api web
for i in $(seq 1 60); do curl -fs localhost:3000/healthz >/dev/null && break; sleep 2; done
curl -s localhost:8000/livez; echo
curl -s localhost:3000/healthz; echo
curl -s -o /dev/null -w '%{http_code}\n' localhost:3000/api/auth/check
docker compose down
```

Expected: `compose-ok`; `{"ok":true}` twice; `204`. The last line proves browser-side API calls now work through compose (D1 fixed). With no `.env` the database is unconfigured, which is fine here.

- [ ] **Step 3: Add the container smoke job to CI**

Append this job to `.github/workflows/ci.yml` (under `jobs:`, after `web:`):

```yaml
  images:
    name: container smoke
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: build images
        run: |
          docker build -f api/Dockerfile -t sdoc-api:ci .
          docker build -t sdoc-web:ci web
      - name: api boots with the dataset baked in
        run: |
          docker network create smoke
          docker run -d --name api --network smoke -p 8000:8000 sdoc-api:ci
          for i in $(seq 1 30); do curl -fs localhost:8000/livez && break; sleep 1; done
          curl -fs localhost:8000/livez
          curl -s localhost:8000/health | python3 -c "import json,sys; h=json.load(sys.stdin); assert h['data_dir']['present'], h"
      - name: web proxies to the api at runtime
        run: |
          docker run -d --name web --network smoke -p 3000:3000 -e API_URL=http://api:8000 sdoc-web:ci
          for i in $(seq 1 30); do curl -fs localhost:3000/healthz && break; sleep 1; done
          curl -fs localhost:3000/healthz
          test "$(curl -s -o /dev/null -w '%{http_code}' localhost:3000/api/auth/check)" = 204
```

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .github/workflows/ci.yml
git commit -m "Run the cloud images under compose and smoke-test them in CI

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: GCP scripts with an offline selftest

**Files:**
- Create: `scripts/gcp/selftest.sh`, `scripts/gcp/lib-env.sh`, `scripts/gcp/common.sh`, `scripts/gcp/neon-region.sh`, `scripts/gcp/bootstrap.sh`, `scripts/gcp/set-secrets.sh`, `scripts/gcp/deploy.sh`, `scripts/gcp/smoke.sh`, `scripts/gcp/demo-reset.sh`, `scripts/gcp/ar-cleanup-policy.json`, `scripts/gcp/uploads-lifecycle.json`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces:
  - `env_value NAME FILE` (from `lib-env.sh`).
  - From `common.sh` (requires `PROJECT_ID`, `REGION`): `$AR_REPO`, `$AR_HOST`, `$AR_PATH`, `$BUCKET`, `$WORKER_JOB`, `$WEB_SA`, `$API_SA`, `$SCORER_SA`, `$DEPLOYER_SA`, `${SECRETS[@]}`, `$PY`, and the functions `project_number`, `service_url NAME`, `gapi METHOD URL [JSON]` and `find_channel EMAIL`.
  - Every script is run as `bash scripts/gcp/<name>.sh` with `PROJECT_ID`/`REGION` exported.

- [ ] **Step 1: Write the failing selftest**

Create `scripts/gcp/selftest.sh`:

```bash
#!/usr/bin/env bash
# Offline checks for scripts/gcp: syntax, region mapping, no credential
# leakage, URL helper, JSON files. No gcloud, no network. Runs in CI.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

for f in "$HERE"/*.sh; do bash -n "$f" || fail "syntax: $f"; done

check_region() { # check_region DOTENV_LINE EXPECTED_NEON EXPECTED_GCP
  printf '%s\n' "$1" > "$TMP/.env"
  local out
  out="$(bash "$HERE/neon-region.sh" "$TMP/.env")"
  [[ "$out" == *"neon: $2"* ]] || fail "neon label for [$1]: $out"
  [[ "$out" == *"gcp:  $3"* ]] || fail "gcp region for [$1]: $out"
  [[ "$out" != *hunter2* && "$out" != *alice* && "$out" != *ep-* ]] || fail "leaked connection details: $out"
}
check_region 'NEON_DB_URI=postgresql://alice:hunter2@ep-cool-darkness-123456-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require' "aws ap-southeast-1" asia-southeast1
check_region 'NEON_DB_URI="postgresql://alice:hunter2@ep-x-1.us-east-2.aws.neon.tech/db"   # main branch' "aws us-east-2" us-east5
check_region 'NEON_DB_URI=postgresql://alice:hunter2@ep-x-1.c-2.us-east-1.aws.neon.tech/db' "aws us-east-1" us-east4
check_region 'NEON_DB_URI=postgres://alice:hunter2@ep-x-1.eastus2.azure.neon.tech/db' "azure eastus2" us-east4

url="$(PROJECT_ID=p REGION=asia-southeast1 PROJECT_NUMBER=123 bash -c "source '$HERE/common.sh'; service_url sdoc-web")"
[[ "$url" == "https://sdoc-web-123.asia-southeast1.run.app" ]] || fail "service_url: $url"

for j in "$HERE"/*.json; do
  python3 -m json.tool "$j" >/dev/null 2>&1 || python -m json.tool "$j" >/dev/null || fail "json: $j"
done
echo "scripts/gcp selftest OK"
```

- [ ] **Step 2: Run to verify failure**

Run: `bash scripts/gcp/selftest.sh`
Expected: FAIL, because `neon-region.sh` does not exist. On Windows, if `mktemp` is denied, prefix with `TMPDIR="$PWD/.pytest-tmp"`.

- [ ] **Step 3: Shared helpers and the region script**

Create `scripts/gcp/lib-env.sh`:

```bash
# env_value NAME FILE — NAME's value in a dotenv file: unquoted, without an
# inline " # comment". Prints nothing if absent. Callers must never echo it.
env_value() {
  local line
  line="$(grep -E "^[[:space:]]*$1=" "$2" | tail -n 1)" || true
  line="${line#*=}"
  line="${line%%[[:space:]]#*}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  line="${line#[\"\']}"
  line="${line%[\"\']}"
  printf '%s' "$line"
}
```

Create `scripts/gcp/common.sh`:

```bash
# Shared names and helpers for scripts/gcp/*.sh — source it, don't run it.
: "${PROJECT_ID:?set PROJECT_ID (e.g. sdoc-verifier-a1b2c3)}"
: "${REGION:?set REGION (from neon-region.sh, e.g. asia-southeast1)}"

# Scope every gcloud call to this project without touching the user's
# global gcloud configuration.
export CLOUDSDK_CORE_PROJECT="$PROJECT_ID"

AR_REPO=sdoc
AR_HOST="$REGION-docker.pkg.dev"
AR_PATH="$AR_HOST/$PROJECT_ID/$AR_REPO"
BUCKET="$PROJECT_ID-sdoc-uploads"
WORKER_JOB=sdoc-worker
WEB_SA="sdoc-web@$PROJECT_ID.iam.gserviceaccount.com"
API_SA="sdoc-api@$PROJECT_ID.iam.gserviceaccount.com"
SCORER_SA="sdoc-scorer@$PROJECT_ID.iam.gserviceaccount.com"
DEPLOYER_SA="sdoc-deployer@$PROJECT_ID.iam.gserviceaccount.com"
SECRETS=(NEON_DB_URI OPENROUTER_API_KEY DEMO_PASSCODE GROUND_TRUTH)

# a python that actually runs (Windows ships a python3 stub that doesn't)
PY=""
for candidate in python3 python; do
  if "$candidate" -c "import sys" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
[[ -n "$PY" ]] || { echo "python is required" >&2; exit 1; }

project_number() {
  if [[ -n "${PROJECT_NUMBER:-}" ]]; then echo "$PROJECT_NUMBER"; return; fi
  gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)'
}

# Cloud Run's deterministic URL: https://<service>-<project-number>.<region>.run.app
service_url() { echo "https://$1-$(project_number).$REGION.run.app"; }

# Authenticated Google REST call: gapi METHOD URL [JSON_BODY]
gapi() {
  local args=(-fsS -X "$1" -H "Authorization: Bearer $(gcloud auth print-access-token)")
  if [[ $# -ge 3 ]]; then args+=(-H "Content-Type: application/json" --data "$3"); fi
  curl "${args[@]}" "$2"
}

# The email notification channel for an address (empty if none yet)
find_channel() {
  gapi GET "https://monitoring.googleapis.com/v3/projects/$PROJECT_ID/notificationChannels" |
    "$PY" -c 'import json,sys; e=sys.argv[1]; print(next((c["name"] for c in json.load(sys.stdin).get("notificationChannels", []) if c.get("labels", {}).get("email_address") == e), ""))' "$1"
}
```

Create `scripts/gcp/neon-region.sh`:

```bash
#!/usr/bin/env bash
# Print the Neon provider/region and the matching Cloud Run region.
# Reads NEON_DB_URI from a dotenv file but prints ONLY region labels —
# never the host, user or password.   OPERATOR-RUN.
#   bash scripts/gcp/neon-region.sh [.env]
set -euo pipefail
source "$(dirname "$0")/lib-env.sh"
ENV_FILE="${1:-.env}"
[[ -f "$ENV_FILE" ]] || { echo "no such file: $ENV_FILE" >&2; exit 1; }

uri="$(env_value NEON_DB_URI "$ENV_FILE")"
[[ -n "$uri" ]] || { echo "NEON_DB_URI is not set in $ENV_FILE" >&2; exit 1; }
host="${uri#*@}"
host="${host%%[:/?]*}"   # ep-name-123[-pooler].[c-N.]<region>.<provider>.neon.tech
unset uri
rest="${host#*.}"
unset host
region="${rest%%.*}"
if [[ "$region" =~ ^c-[0-9]+$ ]]; then rest="${rest#*.}"; region="${rest%%.*}"; fi
provider="${rest#*.}"
provider="${provider%%.*}"

case "$provider/$region" in
  aws/ap-southeast-1) gcp=asia-southeast1 ;;
  aws/ap-southeast-2) gcp=australia-southeast1 ;;
  aws/us-east-1)      gcp=us-east4 ;;
  aws/us-east-2)      gcp=us-east5 ;;
  aws/us-west-2)      gcp=us-west1 ;;
  aws/eu-central-1)   gcp=europe-west3 ;;
  aws/eu-west-2)      gcp=europe-west2 ;;
  aws/sa-east-1)      gcp=southamerica-east1 ;;
  azure/eastus2)      gcp=us-east4 ;;
  *)                  gcp=asia-southeast1 ;;
esac
echo "neon: $provider $region"
echo "gcp:  $gcp"
```

Create `scripts/gcp/ar-cleanup-policy.json`:

```json
[
  {"name": "keep-3-newest", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 3}},
  {"name": "delete-older", "action": {"type": "Delete"}, "condition": {"tagState": "any", "olderThan": "1d"}}
]
```

Create `scripts/gcp/uploads-lifecycle.json`:

```json
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 30}}]}
```

- [ ] **Step 4: Bootstrap (idempotent; no secret values)**

Create `scripts/gcp/bootstrap.sh`:

```bash
#!/usr/bin/env bash
# One-time, re-runnable GCP setup. Everything scales to zero under a US$5
# budget. Creates secret containers only — values come from set-secrets.sh.
#   PROJECT_ID=sdoc-verifier-a1b2c3 REGION=asia-southeast1 \
#   BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX ALERT_EMAIL=you@example.com \
#     bash scripts/gcp/bootstrap.sh
set -euo pipefail
cd "$(dirname "$0")"
: "${BILLING_ACCOUNT:?set BILLING_ACCOUNT (gcloud billing accounts list)}"
: "${ALERT_EMAIL:?set ALERT_EMAIL (budget + uptime alerts)}"
GITHUB_REPO="${GITHUB_REPO:-applejuice8/secret-hack}"
source ./common.sh
quiet() { "$@" >/dev/null 2>&1; }
step() { echo "==> $*"; }

step "project $PROJECT_ID"
quiet gcloud projects describe "$PROJECT_ID" || gcloud projects create "$PROJECT_ID" --name="SDOC Verifier"
gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT" >/dev/null
PROJECT_NUMBER="$(project_number)"

step "APIs"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com iam.googleapis.com iamcredentials.googleapis.com \
  sts.googleapis.com storage.googleapis.com monitoring.googleapis.com \
  billingbudgets.googleapis.com cloudresourcemanager.googleapis.com

step "Artifact Registry '$AR_REPO' (keeps the 3 newest images)"
quiet gcloud artifacts repositories describe "$AR_REPO" --location="$REGION" ||
  gcloud artifacts repositories create "$AR_REPO" --repository-format=docker --location="$REGION"
gcloud artifacts repositories set-cleanup-policies "$AR_REPO" --location="$REGION" \
  --policy=ar-cleanup-policy.json --no-dry-run >/dev/null

step "uploads bucket gs://$BUCKET (private, 30-day expiry)"
quiet gcloud storage buckets describe "gs://$BUCKET" ||
  gcloud storage buckets create "gs://$BUCKET" --location="$REGION" \
    --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update "gs://$BUCKET" --lifecycle-file=uploads-lifecycle.json >/dev/null

step "service accounts"
for sa in sdoc-web sdoc-api sdoc-scorer sdoc-deployer; do
  quiet gcloud iam service-accounts describe "$sa@$PROJECT_ID.iam.gserviceaccount.com" ||
    gcloud iam service-accounts create "$sa" --display-name="$sa"
done

step "secret containers (values: set-secrets.sh)"
for s in "${SECRETS[@]}"; do
  quiet gcloud secrets describe "$s" || gcloud secrets create "$s" --replication-policy=automatic
done
bind_secret() {
  gcloud secrets add-iam-policy-binding "$1" --member="serviceAccount:$2" \
    --role=roles/secretmanager.secretAccessor >/dev/null
}
for s in NEON_DB_URI OPENROUTER_API_KEY DEMO_PASSCODE; do bind_secret "$s" "$API_SA"; done
bind_secret GROUND_TRUTH "$SCORER_SA"

step "IAM"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$API_SA" \
  --role=roles/storage.objectUser >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$API_SA" \
  --role=roles/logging.logWriter --condition=None >/dev/null
gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" --location="$REGION" \
  --member="serviceAccount:$DEPLOYER_SA" --role=roles/artifactregistry.writer >/dev/null
# run.admin, not run.developer: deploys set invoker bindings (setIamPolicy)
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$DEPLOYER_SA" \
  --role=roles/run.admin --condition=None >/dev/null
for sa in "$WEB_SA" "$API_SA" "$SCORER_SA"; do
  gcloud iam service-accounts add-iam-policy-binding "$sa" --member="serviceAccount:$DEPLOYER_SA" \
    --role=roles/iam.serviceAccountUser >/dev/null
done

step "GitHub OIDC for $GITHUB_REPO@main (no JSON keys)"
quiet gcloud iam workload-identity-pools describe github --location=global ||
  gcloud iam workload-identity-pools create github --location=global --display-name="GitHub Actions"
quiet gcloud iam workload-identity-pools providers describe github-actions --location=global --workload-identity-pool=github ||
  gcloud iam workload-identity-pools providers create-oidc github-actions --location=global \
    --workload-identity-pool=github --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository=='$GITHUB_REPO' && assertion.ref=='refs/heads/main'"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$GITHUB_REPO" >/dev/null

step "alert channel for $ALERT_EMAIL"
CHANNEL="$(find_channel "$ALERT_EMAIL")"
if [[ -z "$CHANNEL" ]]; then
  body="$("$PY" -c 'import json,sys; print(json.dumps({"type": "email", "displayName": "SDOC alerts", "labels": {"email_address": sys.argv[1]}}))' "$ALERT_EMAIL")"
  CHANNEL="$(gapi POST "https://monitoring.googleapis.com/v3/projects/$PROJECT_ID/notificationChannels" "$body" |
    "$PY" -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
fi

step "budget US\$5 (alerts at 50/90/100% actual + 100% forecast)"
if ! gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" --format="value(displayName)" | grep -qx "sdoc-verifier"; then
  gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" --display-name="sdoc-verifier" \
    --budget-amount=5USD --filter-projects="projects/$PROJECT_NUMBER" \
    --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0 \
    --threshold-rule=percent=1.0,basis=forecasted-spend \
    --notifications-rule-monitoring-notification-channels="$CHANNEL" >/dev/null
fi

cat <<EOF

Bootstrap complete. Next:
  1. bash scripts/gcp/set-secrets.sh .env     (operator only)
  2. bash scripts/gcp/deploy.sh
  3. bash scripts/gcp/demo-reset.sh           (first seed)
  4. bash scripts/gcp/smoke.sh

GitHub repo variables for .github/workflows/deploy.yml (repo admin):
  GCP_PROJECT_ID=$PROJECT_ID
  GCP_PROJECT_NUMBER=$PROJECT_NUMBER
  GCP_REGION=$REGION
  GCP_WIF_PROVIDER=projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github-actions
  GCP_DEPLOYER_SA=$DEPLOYER_SA
EOF
```

- [ ] **Step 5: Secrets (operator), deploy, smoke, reset**

Create `scripts/gcp/set-secrets.sh`:

```bash
#!/usr/bin/env bash
# OPERATOR ONLY. Pushes secret values into Secret Manager without printing
# them: NEON_DB_URI and OPENROUTER_API_KEY from a dotenv file, the reviewer
# passcode typed (hidden) or generated, the answer key from secrets/.
#   PROJECT_ID=... REGION=... bash scripts/gcp/set-secrets.sh [.env]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/scripts/gcp/common.sh"
source "$ROOT/scripts/gcp/lib-env.sh"
ENV_FILE="${1:-$ROOT/.env}"
[[ -f "$ENV_FILE" ]] || { echo "no such file: $ENV_FILE" >&2; exit 1; }

push() { # push SECRET  (value on stdin)
  gcloud secrets versions add "$1" --data-file=- >/dev/null
  echo "  $1: new version added"
}

for name in NEON_DB_URI OPENROUTER_API_KEY; do
  value="$(env_value "$name" "$ENV_FILE")"
  [[ -n "$value" ]] || { echo "$name is empty in $ENV_FILE" >&2; exit 1; }
  printf '%s' "$value" | push "$name"
  unset value
done

read -rsp "Reviewer passcode for judges (leave blank to generate one): " passcode
echo
if [[ -z "$passcode" ]]; then
  passcode="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(9))')"
  echo "  generated passcode: $passcode   <- give this to judges in the submission form"
fi
printf '%s' "$passcode" | push DEMO_PASSCODE
unset passcode

GT="$ROOT/secrets/ground_truth.json"
[[ -f "$GT" ]] || { echo "missing $GT (see secrets/README.md)" >&2; exit 1; }
"$PY" -c 'import json,sys; sys.stdout.write(json.dumps(json.load(open(sys.argv[1])), separators=(",", ":")))' "$GT" | push GROUND_TRUTH
echo "Done. Redeploy (scripts/gcp/deploy.sh) so running services pick up the new values."
```

Create `scripts/gcp/deploy.sh`:

```bash
#!/usr/bin/env bash
# Build, push and deploy: scorer -> worker job -> api -> web. Used by people and CI.
#   PROJECT_ID=... REGION=... [IMAGE_TAG=...] bash scripts/gcp/deploy.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
source scripts/gcp/common.sh
TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
PROJECT_NUMBER="$(project_number)"
export PROJECT_NUMBER
API_URL="$(service_url sdoc-api)"
WEB_URL="$(service_url sdoc-web)"
SCORER_URL="$(service_url sdoc-scorer)"

gcloud auth configure-docker "$AR_HOST" --quiet >/dev/null
build_push() { # build_push NAME CONTEXT [docker build args...]
  local image="$AR_PATH/$1:$TAG"
  docker build -t "$image" "${@:3}" "$2"
  docker push "$image"
}
build_push api . -f api/Dockerfile
build_push web web
build_push scorer docs-provided/problem-statement/sdoc-hackathon-docker/server

# Cloud Storage volume flags: replace on update, plain add on first create.
set_uploads_flags() { # set_uploads_flags services|jobs NAME
  UPLOADS=(--add-volume "name=uploads,type=cloud-storage,bucket=$BUCKET,mount-options=uid=10001;gid=10001"
           --add-volume-mount "volume=uploads,mount-path=/data/uploads")
  if gcloud run "$1" describe "$2" --region "$REGION" >/dev/null 2>&1; then
    UPLOADS=(--clear-volumes --clear-volume-mounts "${UPLOADS[@]}")
  fi
}

echo "==> sdoc-scorer (private)"
gcloud run deploy sdoc-scorer --image "$AR_PATH/scorer:$TAG" --region "$REGION" \
  --service-account "$SCORER_SA" --no-allow-unauthenticated --port 8000 \
  --cpu 1 --memory 512Mi --min-instances 0 --max-instances 1 --cpu-throttling \
  --set-secrets "/secrets/ground_truth.json=GROUND_TRUTH:latest" --quiet
gcloud run services add-iam-policy-binding sdoc-scorer --region "$REGION" \
  --member "serviceAccount:$API_SA" --role roles/run.invoker --quiet >/dev/null

API_ENV="RUN_EXECUTOR=cloudrun-job,GCP_PROJECT_ID=$PROJECT_ID,GCP_REGION=$REGION,WORKER_JOB=$WORKER_JOB,SCORER_URL=$SCORER_URL,SCORER_AUTH=gcp-id-token,LOG_FORMAT=json,CORS_ORIGINS=$WEB_URL"
API_SECRETS="NEON_DB_URI=NEON_DB_URI:latest,OPENROUTER_API_KEY=OPENROUTER_API_KEY:latest,DEMO_PASSCODE=DEMO_PASSCODE:latest"

echo "==> $WORKER_JOB (job)"
set_uploads_flags jobs "$WORKER_JOB"
gcloud run jobs deploy "$WORKER_JOB" --image "$AR_PATH/api:$TAG" --region "$REGION" \
  --service-account "$API_SA" --command python --args=-m,pipeline.worker,seed \
  --tasks 1 --parallelism 1 --max-retries 1 --task-timeout 1800s --cpu 1 --memory 1Gi \
  --set-env-vars "$API_ENV" --set-secrets "$API_SECRETS" "${UPLOADS[@]}" --quiet
gcloud run jobs add-iam-policy-binding "$WORKER_JOB" --region "$REGION" \
  --member "serviceAccount:$API_SA" --role roles/run.jobsExecutorWithOverrides --quiet >/dev/null

echo "==> sdoc-api"
set_uploads_flags services sdoc-api
gcloud run deploy sdoc-api --image "$AR_PATH/api:$TAG" --region "$REGION" \
  --service-account "$API_SA" --allow-unauthenticated --port 8000 \
  --cpu 1 --memory 1Gi --min-instances 0 --max-instances 2 --concurrency 40 --timeout 300 \
  --cpu-throttling --cpu-boost --execution-environment gen2 \
  --set-env-vars "$API_ENV" --set-secrets "$API_SECRETS" "${UPLOADS[@]}" --quiet

echo "==> sdoc-web"
gcloud run deploy sdoc-web --image "$AR_PATH/web:$TAG" --region "$REGION" \
  --service-account "$WEB_SA" --allow-unauthenticated --port 3000 \
  --cpu 1 --memory 512Mi --min-instances 0 --max-instances 2 --concurrency 80 \
  --cpu-throttling --cpu-boost --set-env-vars "API_URL=$API_URL" --quiet

echo
echo "web: $WEB_URL"
echo "api: $API_URL"
```

Create `scripts/gcp/smoke.sh`:

```bash
#!/usr/bin/env bash
# Post-deploy checks against the live URLs. Fails loudly.
#   PROJECT_ID=... REGION=... bash scripts/gcp/smoke.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"
PROJECT_NUMBER="$(project_number)"
export PROJECT_NUMBER
WEB_URL="$(service_url sdoc-web)"
API_URL="$(service_url sdoc-api)"
fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$@"; }

for i in 1 2 3; do [[ "$(code "$WEB_URL/")" == 200 ]] && break; sleep 5; done
[[ "$(code "$WEB_URL/")" == 200 ]] || fail "web / is not 200"
health="$(curl -s --max-time 60 "$API_URL/health")"
"$PY" -c '
import json, sys
h = json.loads(sys.argv[1])
assert h["writes_protected"] is True, "writes are NOT protected (DEMO_PASSCODE empty?)"
assert h["data_dir"]["present"], "dataset missing from the image"
assert h["database"]["ok"], "database unreachable"
assert h["run_executor"] == "cloudrun-job", "api is not using the worker job"
' "$health" || fail "api /health (see above)"
[[ "$(code -X POST "$API_URL/api/pipeline/run")" == 401 ]] || fail "unauthenticated run was not refused"
[[ "$(code -X POST "$WEB_URL/api/pipeline/run")" == 401 ]] || fail "web proxy did not reach the api"
n="$(curl -s --max-time 60 "$API_URL/api/emails" | "$PY" -c 'import json,sys; print(len(json.load(sys.stdin)))')"
(( n >= 520 )) || fail "expected at least 520 emails, got $n (seed with demo-reset.sh)"
echo "smoke OK: $WEB_URL"
```

Create `scripts/gcp/demo-reset.sh`:

```bash
#!/usr/bin/env bash
# Remove uploads + their reviews, reload the dataset, run every email, score.
# Also the first-time seed.
#   PROJECT_ID=... REGION=... bash scripts/gcp/demo-reset.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"
gcloud run jobs execute "$WORKER_JOB" --region "$REGION" --args=-m,pipeline.worker,seed,--reset --wait
```

- [ ] **Step 6: Run the selftest**

Run: `bash scripts/gcp/selftest.sh`
Expected: `scripts/gcp selftest OK`

- [ ] **Step 7: Run it in CI**

In `.github/workflows/ci.yml`, job `api`, add this step directly after `- run: uv run ruff check api`:

```yaml
      - run: bash scripts/gcp/selftest.sh
```

- [ ] **Step 8: Commit**

```bash
git add scripts/gcp .github/workflows/ci.yml
git update-index --chmod=+x scripts/gcp/*.sh
git commit -m "Add GCP bootstrap, secrets, deploy, smoke and reset scripts

Idempotent, budget-capped, and credential-free for everyone but the
operator. An offline selftest runs in CI.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 14: First cloud deploy (checkpoint: live URL)

This task is operational. Steps marked **OPERATOR** are run by the user; the implementer must not run them or read their output files. Stop and hand over at each OPERATOR step.

**Interfaces:**
- Produces: a live `WEB_URL` / `API_URL`, a seeded and scored database, and the five GitHub variable values printed by bootstrap.

- [ ] **Step 1: Pre-flight (implementer)**

```bash
docker info --format '{{.ServerVersion}}'
gcloud auth list --format="value(account)" --filter=status:ACTIVE
gcloud billing accounts list --format="value(name,open)"
test -f secrets/ground_truth.json && echo key-present
```

Expected: a Docker version, the user's account, at least one open billing account, `key-present`.

- [ ] **Step 2: OPERATOR — put the rotated `.env` at the repo root**

The `.env` must hold `NEON_DB_URI` and `OPENROUTER_API_KEY`. Both were exposed in chat on 2026-09-20 and **must be rotated first** (Neon: reset the `neondb_owner` password; OpenRouter: delete and recreate the key). The implementer never reads this file.

Region is already known and needs no script run: Neon is on `aws ap-southeast-1`, so `REGION=asia-southeast1`. (`neon-region.sh` still exists for other environments and is covered by the selftest.)

- [ ] **Step 3: Confirm the target before creating anything**

These are already verified and need no new project:

```bash
gcloud projects describe averis-email-system --format="value(projectId,projectNumber)"   # averis-email-system  969206696114
gcloud billing projects describe averis-email-system --format="value(billingAccountName,billingEnabled)"  # billingAccounts/015CE1-381F1A-582702  True
```

```bash
export PROJECT_ID=averis-email-system REGION=asia-southeast1 \
       BILLING_ACCOUNT=015CE1-381F1A-582702 ALERT_EMAIL=<confirm with the user>
```

Ask the user only for `ALERT_EMAIL`, and confirm that bootstrap will add Cloud Run, Artifact Registry, Secret Manager, Storage, Monitoring and budget resources to this **existing** project. Note the spend is capped by scale-to-zero, instance limits, a US$5 alert budget and (Task 18b) a $10 kill switch. **Proceed only on an explicit yes.**

- [ ] **Step 4: Bootstrap**

```bash
export PROJECT_ID=<confirmed id> REGION=<gcp region> BILLING_ACCOUNT=<confirmed account> ALERT_EMAIL=<confirmed email>
bash scripts/gcp/bootstrap.sh
```

Expected: every `==>` step completes, then the "GitHub repo variables" block. Save that block for Task 19.

- [ ] **Step 5: OPERATOR — populate secrets**

```bash
bash scripts/gcp/set-secrets.sh .env
```

Expected: four `new version added` lines. The operator keeps the passcode for the submission form.

- [ ] **Step 6: Deploy**

Run: `bash scripts/gcp/deploy.sh`
Expected: three images pushed, then `web: https://sdoc-web-<n>.<region>.run.app` and `api: …`.
If the job deploy rejects the Cloud Storage volume ("requires the second generation execution environment"), add `--execution-environment gen2` to the `gcloud run jobs deploy` line in `deploy.sh`, commit that fix, and rerun.

- [ ] **Step 7: Seed, then smoke**

Run: `bash scripts/gcp/demo-reset.sh`, then `bash scripts/gcp/smoke.sh`
Expected: the job execution completes successfully (about 1–3 min), then `smoke OK: https://sdoc-web-…`.
Check the job logs for the score line:

```bash
gcloud logging read 'resource.type="cloud_run_job" AND jsonPayload.message:"scored seed run"' --limit 1 --format='value(jsonPayload.message)'
```

Expected: `scored seed run: final_score=1.0`, or the current score.

- [ ] **Step 8: Manual check in a private browser window**

Open `WEB_URL`. The dashboard lists the emails. Open `email_004`: the consignee and notify-party mismatch shows side by side. The Review queue lists escalations. Write buttons show "Unlock reviewer mode…". Unlock with the passcode, then confirm one case.

- [ ] **Step 9: Commit any fixes made during this task**

If `deploy.sh` needed the gen2 fix:

```bash
git add scripts/gcp/deploy.sh
git commit -m "Run the worker job on the second-generation runtime

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 15: Reprocess one email (visible, retryable failures)

**Files:**
- Create: `api/app/services/processing.py`, `api/tests/test_processing.py`
- Modify: `api/app/schemas/emails.py`, `api/app/api/routes/emails.py`

**Interfaces:**
- Consumes: `failed_result`, `process_email`, `runs_repo.get_or_create`, `results_repo.add/stats_by_category_status`, and `emails_repo.to_record` (Task 4); `require_reviewer` (Task 3).
- Produces: `processing.ADHOC_RUN_LABEL = "Uploads & retries"`, `processing.PROCESS_TIMEOUT_S = 90` and `async processing.process_one(s, record: dict, data_dir: str) -> dict`, which always persists a result and returns it. Also `ProcessOutcome{email_id, status, category}` and `POST /api/emails/{email_id}/reprocess -> ProcessOutcome` (404 if the email is unknown).

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_processing.py`:

```python
"""One-off processing (uploads, retries): results always land, failures show."""
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main  # noqa: E402
from app.api.deps import get_db  # noqa: E402
from app.api.routes import emails as emails_routes  # noqa: E402
from app.services import processing  # noqa: E402

RECORD = {"email_id": "upload_20260920_a1b2c3", "from": "ops@example.com",
          "subject": "Check", "body": "", "attachments": []}


@pytest.fixture
def adhoc(monkeypatch):
    run = SimpleNamespace(id=uuid.uuid4(), stats=None)
    get_or_create = AsyncMock(return_value=run)
    monkeypatch.setattr(processing.runs_repo, "get_or_create", get_or_create)
    add = AsyncMock()
    monkeypatch.setattr(processing.results_repo, "add", add)
    monkeypatch.setattr(processing.results_repo, "stats_by_category_status",
                        AsyncMock(return_value={"BL_COMPARISON:OK": 1}))
    session = SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())
    return SimpleNamespace(run=run, add=add, session=session, get_or_create=get_or_create)


@pytest.mark.asyncio
async def test_result_lands_in_the_uploads_run(monkeypatch, adhoc):
    monkeypatch.setattr(processing, "process_email", MagicMock(
        return_value={"email_id": RECORD["email_id"], "status": "OK", "category": "BL_COMPARISON"}))

    out = await processing.process_one(adhoc.session, RECORD, "/data")

    assert out["status"] == "OK"
    adhoc.get_or_create.assert_awaited_once_with(adhoc.session, "Uploads & retries")
    adhoc.add.assert_awaited_once_with(adhoc.session, adhoc.run.id, out)
    assert adhoc.run.stats == {"BL_COMPARISON:OK": 1}
    adhoc.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_crash_is_stored_as_failed(monkeypatch, adhoc):
    monkeypatch.setattr(processing, "process_email", MagicMock(side_effect=ValueError("bad pdf")))

    out = await processing.process_one(adhoc.session, RECORD, "/data")

    assert (out["status"], out["error"]) == ("FAILED", "ValueError: bad pdf")
    adhoc.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_slow_email_times_out_as_failed(monkeypatch, adhoc):
    monkeypatch.setattr(processing, "PROCESS_TIMEOUT_S", 0.05)
    monkeypatch.setattr(processing, "process_email", lambda *args: time.sleep(0.3))

    out = await processing.process_one(adhoc.session, RECORD, "/data")

    assert out["status"] == "FAILED"
    assert out["error"].startswith("TimeoutError: processing exceeded")


@pytest.fixture
def api(monkeypatch):
    session = SimpleNamespace(commit=AsyncMock())

    async def fake_db():
        yield session

    main.app.dependency_overrides[get_db] = fake_db
    yield SimpleNamespace(client=TestClient(main.app), session=session)
    main.app.dependency_overrides.clear()


def test_reprocess_unknown_email_is_404(api, monkeypatch):
    monkeypatch.setattr(emails_routes.emails_repo, "get_by_id", AsyncMock(return_value=None))
    assert api.client.post("/api/emails/email_999/reprocess").status_code == 404


def test_reprocess_returns_the_new_verdict(api, monkeypatch):
    email = SimpleNamespace(email_id="email_004", sender="ops", subject="Check", body="", attachments=[])
    monkeypatch.setattr(emails_routes.emails_repo, "get_by_id", AsyncMock(return_value=email))
    process = AsyncMock(return_value={"status": "MISMATCH", "category": "BL_COMPARISON"})
    monkeypatch.setattr(emails_routes, "process_one", process)

    r = api.client.post("/api/emails/email_004/reprocess")

    assert r.status_code == 200
    assert r.json() == {"email_id": "email_004", "status": "MISMATCH", "category": "BL_COMPARISON"}
    assert process.await_args.args[1]["email_id"] == "email_004"
```

- [ ] **Step 2: Run to verify failure**

Run: `T` with `api/tests/test_processing.py`
Expected: FAIL with `ImportError: cannot import name 'processing'`.

- [ ] **Step 3: Implement**

Create `api/app/services/processing.py`:

```python
"""One-off processing outside batch runs: live intake and reprocess.

Every attempt stores a result — a crash or timeout becomes a visible FAILED
row that a reviewer can retry, never a silent loss.
"""
import asyncio

from pipeline.verdict import failed_result, process_email
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ..repositories import results as results_repo
from ..repositories import runs as runs_repo

ADHOC_RUN_LABEL = "Uploads & retries"
PROCESS_TIMEOUT_S = 90


async def process_one(s: AsyncSession, record: dict, data_dir: str) -> dict:
    try:
        result = await asyncio.wait_for(run_in_threadpool(process_email, record, data_dir), timeout=PROCESS_TIMEOUT_S)
    except TimeoutError:
        result = failed_result(record["email_id"], TimeoutError(f"processing exceeded {PROCESS_TIMEOUT_S} s"))
    except Exception as e:
        result = failed_result(record["email_id"], e)
    run = await runs_repo.get_or_create(s, ADHOC_RUN_LABEL)
    await results_repo.add(s, run.id, result)
    await s.flush()
    run.stats = await results_repo.stats_by_category_status(s, run.id)
    await s.commit()
    return result
```

Append to `api/app/schemas/emails.py`:

```python


class ProcessOutcome(BaseModel):
    email_id: str
    status: str
    category: str
```

In `api/app/api/routes/emails.py`:
- Replace the import block with:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...repositories import emails as emails_repo
from ...repositories import results as results_repo
from ...schemas.emails import EmailDetail, EmailListItem, ProcessOutcome, ResultDetail
from ...services.processing import process_one
from ..deps import get_db, require_reviewer
```

- In `attachment_preview`, delete the now-redundant inner line `from ...core.config import settings`.
- Append:

```python


@router.post("/emails/{email_id}/reprocess", response_model=ProcessOutcome,
             dependencies=[Depends(require_reviewer)])
async def reprocess_email(email_id: str, s: AsyncSession = Depends(get_db)):
    """Retry one email; the new result becomes the latest everywhere."""
    email = await emails_repo.get_by_id(s, email_id)
    if email is None:
        raise HTTPException(404, f"no such email: {email_id}")
    result = await process_one(s, emails_repo.to_record(email), settings.resolved_data_dir)
    return ProcessOutcome(email_id=email_id, status=result["status"], category=result["category"])
```

- [ ] **Step 4: Run tests and lint**

Run: `T` then `L`
Expected: `114 passed` (`test_every_write_route_requires_the_passcode` now also covers `/reprocess`); `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add api/app/services/processing.py api/app/schemas/emails.py api/app/api/routes/emails.py api/tests/test_processing.py
git commit -m "Let reviewers reprocess an email; crashes and timeouts stay visible

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 16: Live intake API

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (via `uv add`), `api/app/api/router.py`
- Create: `api/app/services/intake.py`, `api/app/api/routes/intake.py`, `api/tests/test_intake.py`

**Interfaces:**
- Consumes: `process_one`, `ProcessOutcome` (Task 15); `emails_repo.create_upload` (Task 4); `settings.uploads_subdir`, `settings.resolved_data_dir` (Task 2).
- Produces: in `app.services.intake`, the constants `MAX_FILES=4`, `MAX_FILE_BYTES=5 MiB`, `MAX_TOTAL_BYTES=10 MiB`, `MAX_SENDER=200`, `MAX_SUBJECT=300`, `MAX_BODY=20000`, `ALLOWED_SUFFIXES`, and `IntakeError(ValueError)`, `IntakeFile(name, data)`, `safe_filename(raw, taken) -> str`, `check_content(name, data)`, `validate_submission(sender, subject, body, uploads) -> list[IntakeFile]`, `new_email_id(now=None, token=None) -> str`, `save_files(data_dir, subdir, email_id, files) -> list[str]`, `build_record(email_id, sender, subject, body, attachments) -> dict`. The endpoint is `POST /api/intake` (multipart fields `sender`, `subject`, `body`, `files[]`), returning `201 ProcessOutcome`, or `422 {"detail": str}` on invalid input.

- [ ] **Step 1: Add the multipart dependency**

Run: `uv add python-multipart`
Expected: `pyproject.toml` gains `python-multipart>=…` and `uv.lock` updates.

- [ ] **Step 2: Write the failing tests**

Create `api/tests/test_intake.py`:

```python
"""Live intake: validation, safe storage, and the upload -> verdict round trip."""
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main  # noqa: E402
from app.api.deps import get_db  # noqa: E402
from app.api.routes import intake as intake_routes  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services import intake  # noqa: E402

PDF = b"%PDF-1.4\n%fake\n"
OK_UPLOADS = [("clean_SI.txt", b"Shipper: ACME"), ("clean_BL.pdf", PDF)]
FORM = {"sender": "ops@example.com", "subject": "TO CONFIRM DOCS", "body": "Please compare the SI and BL."}


def test_ids_are_dated_and_random():
    assert intake.new_email_id(datetime(2026, 9, 20), "a1b2c3") == "upload_20260920_a1b2c3"
    assert re.fullmatch(r"upload_\d{8}_[0-9a-f]{6}", intake.new_email_id())


@pytest.mark.parametrize("raw,expected", [
    ("SI.txt", "SI.txt"),
    ("../../etc/passwd.txt", "passwd.txt"),
    ("C:\\Users\\ops\\Draft BL (v2).PDF", "Draft_BL_v2_.pdf"),
    ("...", "attachment"),
    ("a" * 200 + ".docx", "a" * 75 + ".docx"),
])
def test_filenames_are_reduced_to_a_safe_basename(raw, expected):
    assert intake.safe_filename(raw, set()) == expected


def test_duplicate_names_get_a_suffix():
    taken: set[str] = set()
    assert [intake.safe_filename("SI.txt", taken) for _ in range(3)] == ["SI.txt", "SI-2.txt", "SI-3.txt"]


def test_valid_submission_passes():
    files = intake.validate_submission("ops@example.com", "Check docs", "Please compare", OK_UPLOADS)
    assert [f.name for f in files] == ["clean_SI.txt", "clean_BL.pdf"]


@pytest.mark.parametrize("uploads,message", [
    ([("a.exe", b"MZ")], "not allowed"),
    ([("fake.pdf", b"hello")], "not a PDF"),
    ([("sheet.xlsx", b"hello")], "not a valid xlsx"),
    ([("notes.txt", b"\xff\xfe\xfa")], "not UTF-8"),
    ([("big.txt", b"x" * (intake.MAX_FILE_BYTES + 1))], "larger than 5 MB"),
    ([(f"f{i}.txt", b"x") for i in range(intake.MAX_FILES + 1)], "at most 4"),
])
def test_bad_files_are_rejected_with_a_reason(uploads, message):
    with pytest.raises(intake.IntakeError, match=message):
        intake.validate_submission("ops@example.com", "Check", "", uploads)


def test_total_size_is_capped():
    chunk = b"x" * (intake.MAX_FILE_BYTES - 10)
    with pytest.raises(intake.IntakeError, match="10 MB"):
        intake.validate_submission("ops@example.com", "Check", "", [(f"f{i}.txt", chunk) for i in range(3)])


@pytest.mark.parametrize("sender,subject,body,message", [
    ("", "Check", "", "sender"),
    ("ops@example.com", " ", "", "subject"),
    ("ops@example.com", "x" * 301, "", "subject"),
    ("ops@example.com", "Check", "x" * 20_001, "body"),
])
def test_text_fields_are_bounded(sender, subject, body, message):
    with pytest.raises(intake.IntakeError, match=message):
        intake.validate_submission(sender, subject, body, [])


def test_files_are_saved_under_the_email_folder(tmp_path):
    files = intake.validate_submission("ops@example.com", "Check", "", OK_UPLOADS)
    paths = intake.save_files(tmp_path, "uploads", "upload_20260920_a1b2c3", files)

    assert paths == ["uploads/upload_20260920_a1b2c3/clean_SI.txt", "uploads/upload_20260920_a1b2c3/clean_BL.pdf"]
    assert (tmp_path / paths[1]).read_bytes() == PDF


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    session = SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())

    async def fake_db():
        yield session

    main.app.dependency_overrides[get_db] = fake_db
    create = AsyncMock()
    monkeypatch.setattr(intake_routes.emails_repo, "create_upload", create)
    process = AsyncMock(return_value={"status": "MISMATCH", "category": "BL_COMPARISON"})
    monkeypatch.setattr(intake_routes, "process_one", process)
    yield SimpleNamespace(client=TestClient(main.app), create=create, process=process, root=tmp_path)
    main.app.dependency_overrides.clear()


def _files(uploads):
    return [("files", (name, data, "application/octet-stream")) for name, data in uploads]


def test_upload_is_stored_processed_and_returned(api):
    r = api.client.post("/api/intake", data=FORM, files=_files(OK_UPLOADS))

    assert r.status_code == 201, r.text
    body = r.json()
    assert re.fullmatch(r"upload_\d{8}_[0-9a-f]{6}", body["email_id"])
    assert (body["status"], body["category"]) == ("MISMATCH", "BL_COMPARISON")
    record = api.create.await_args.args[1]
    assert record["attachments"] == [f"uploads/{body['email_id']}/clean_SI.txt",
                                     f"uploads/{body['email_id']}/clean_BL.pdf"]
    assert (api.root / record["attachments"][1]).read_bytes() == PDF
    assert api.process.await_args.args[1] is record


def test_a_processing_failure_is_still_created_and_visible(api):
    api.process.return_value = {"status": "FAILED", "category": "GENERAL"}
    r = api.client.post("/api/intake", data=FORM, files=_files(OK_UPLOADS))
    assert (r.status_code, r.json()["status"]) == (201, "FAILED")


def test_invalid_upload_is_a_422_and_nothing_is_stored(api):
    r = api.client.post("/api/intake", data=FORM, files=_files([("x.exe", b"MZ")]))

    assert r.status_code == 422
    assert "not allowed" in r.json()["detail"]
    api.create.assert_not_awaited()
    assert not (api.root / "uploads").exists()


def test_intake_needs_the_passcode(api, monkeypatch):
    monkeypatch.setattr(settings, "demo_passcode", "harbour-42")
    assert api.client.post("/api/intake", data=FORM).status_code == 401
```

- [ ] **Step 3: Run to verify failure**

Run: `T` with `api/tests/test_intake.py`
Expected: FAIL with `ImportError: cannot import name 'intake'`.

- [ ] **Step 4: Implement the service**

Create `api/app/services/intake.py`:

```python
"""Live intake: validate an uploaded email + attachments and store them
where the pipeline readers already look (DATA_DIR/uploads/<email_id>/)."""
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

MAX_FILES = 4
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024
MAX_SENDER = 200
MAX_SUBJECT = 300
MAX_BODY = 20_000
MAX_NAME = 80
ALLOWED_SUFFIXES = {".txt", ".pdf", ".docx", ".xlsx"}
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class IntakeError(ValueError):
    """Invalid submission; the message is shown to the user as-is."""


@dataclass(frozen=True)
class IntakeFile:
    name: str
    data: bytes


def safe_filename(raw: str, taken: set[str]) -> str:
    """Basename only, [A-Za-z0-9._-], at most 80 chars, lower-case extension,
    unique within one submission."""
    base = PurePosixPath(raw.replace("\\", "/")).name
    cleaned = _UNSAFE.sub("_", base).strip("._") or "attachment"
    suffix = PurePosixPath(cleaned).suffix.lower()
    stem = cleaned[: len(cleaned) - len(suffix)] if suffix else cleaned
    stem = stem[: MAX_NAME - len(suffix)]
    name = f"{stem}{suffix}"
    n = 2
    while name.lower() in taken:
        name = f"{stem[: MAX_NAME - len(suffix) - 3]}-{n}{suffix}"
        n += 1
    taken.add(name.lower())
    return name


def check_content(name: str, data: bytes) -> None:
    """The bytes must match the extension (no renamed executables)."""
    suffix = PurePosixPath(name).suffix
    if suffix == ".pdf" and not data.startswith(b"%PDF-"):
        raise IntakeError(f"{name} is not a PDF file.")
    if suffix in {".docx", ".xlsx"} and not data.startswith(b"PK\x03\x04"):
        raise IntakeError(f"{name} is not a valid {suffix[1:]} file.")
    if suffix == ".txt":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise IntakeError(f"{name} is not UTF-8 text.") from None


def validate_submission(sender: str, subject: str, body: str,
                        uploads: list[tuple[str, bytes]]) -> list[IntakeFile]:
    if not sender.strip() or len(sender) > MAX_SENDER:
        raise IntakeError(f"Enter a sender address (up to {MAX_SENDER} characters).")
    if not subject.strip() or len(subject) > MAX_SUBJECT:
        raise IntakeError(f"Enter a subject (up to {MAX_SUBJECT} characters).")
    if len(body) > MAX_BODY:
        raise IntakeError(f"The body is limited to {MAX_BODY:,} characters.")
    if len(uploads) > MAX_FILES:
        raise IntakeError(f"Attach at most {MAX_FILES} files.")
    taken: set[str] = set()
    files: list[IntakeFile] = []
    total = 0
    for raw_name, data in uploads:
        name = safe_filename(raw_name, taken)
        if len(data) > MAX_FILE_BYTES:
            raise IntakeError(f"{name} is larger than 5 MB.")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise IntakeError("Attachments are limited to 10 MB in total.")
        if PurePosixPath(name).suffix not in ALLOWED_SUFFIXES:
            raise IntakeError(f"{name} is not allowed: use .txt, .pdf, .docx or .xlsx.")
        check_content(name, data)
        files.append(IntakeFile(name, data))
    return files


def new_email_id(now: datetime | None = None, token: str | None = None) -> str:
    return f"upload_{(now or datetime.now(UTC)):%Y%m%d}_{token or secrets.token_hex(3)}"


def save_files(data_dir: Path, subdir: str, email_id: str, files: list[IntakeFile]) -> list[str]:
    """Write each file once (Cloud Storage FUSE has no atomic rename) and
    return paths relative to DATA_DIR, the form the pipeline readers use."""
    folder = Path(data_dir) / subdir / email_id
    folder.mkdir(parents=True, exist_ok=False)
    paths = []
    for f in files:
        (folder / f.name).write_bytes(f.data)
        paths.append(f"{subdir}/{email_id}/{f.name}")
    return paths


def build_record(email_id: str, sender: str, subject: str, body: str, attachments: list[str]) -> dict:
    """Same shape as an inbox JSON record."""
    return {"email_id": email_id, "from": sender, "subject": subject, "body": body, "attachments": attachments}
```

- [ ] **Step 5: Implement the route and mount it**

Create `api/app/api/routes/intake.py`:

```python
"""Live intake: a person submits an email + attachments and gets a verdict."""
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ...core.config import settings
from ...repositories import emails as emails_repo
from ...schemas.emails import ProcessOutcome
from ...services import intake
from ...services.processing import process_one
from ..deps import get_db, require_reviewer

router = APIRouter()


@router.post("/intake", status_code=201, response_model=ProcessOutcome, dependencies=[Depends(require_reviewer)])
async def create_intake(
    sender: str = Form(""),
    subject: str = Form(""),
    body: str = Form(""),
    files: list[UploadFile] | None = File(None),
    s: AsyncSession = Depends(get_db),
):
    uploads = files or []
    if len(uploads) > intake.MAX_FILES:
        raise HTTPException(422, f"Attach at most {intake.MAX_FILES} files.")
    raw = [(f.filename or "attachment", await f.read(intake.MAX_FILE_BYTES + 1)) for f in uploads]
    try:
        clean = intake.validate_submission(sender, subject, body, raw)
    except intake.IntakeError as e:
        raise HTTPException(422, str(e)) from e
    email_id = intake.new_email_id()
    paths = await run_in_threadpool(
        intake.save_files, Path(settings.resolved_data_dir), settings.uploads_subdir, email_id, clean
    )
    record = intake.build_record(email_id, sender.strip(), subject.strip(), body, paths)
    await emails_repo.create_upload(s, record)
    result = await process_one(s, record, settings.resolved_data_dir)
    return ProcessOutcome(email_id=email_id, status=result["status"], category=result["category"])
```

In `api/app/api/router.py`, change `from .routes import auth, emails, pipeline, review` to `from .routes import auth, emails, intake, pipeline, review`, and add `api_router.include_router(intake.router)` after the emails router line.

- [ ] **Step 6: Run tests and lint**

Run: `T` then `L`
Expected: `138 passed`; `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock api/app/services/intake.py api/app/api/routes/intake.py api/app/api/router.py api/tests/test_intake.py
git commit -m "Accept live email submissions with validated attachments

Files land where the readers already look, so the pipeline runs on them
unchanged.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 17: Intake page, sample kit, Retry, failed runs

**Files:**
- Create: `web/public/samples/*` (10 files), `web/app/intake/page.tsx`, `web/app/intake/IntakeForm.tsx`, `web/app/components/RetryButton.tsx`, `api/tests/test_sample_kit.py`
- Modify: `web/app/components/Navigation.tsx`, `web/app/review/page.tsx`, `web/app/emails/[id]/page.tsx`, `web/app/runs/page.tsx`, `web/lib/api.ts`, `web/app/globals.css`

**Interfaces:**
- Consumes: `POST /api/intake` (Task 16), `POST /api/emails/{id}/reprocess` (Task 15), `Run.error` (Task 4), `useReviewer` and `LockedHint` (Task 11).
- Produces: the `/intake` page, the static `/samples/<file>` files, and `RetryButton({emailId, label?})`.

- [ ] **Step 1: Write the failing sample-kit test**

Create `api/tests/test_sample_kit.py`:

```python
"""The downloadable sample kit on /intake must keep producing the verdicts
the page promises."""
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.verdict import process_email  # noqa: E402

PUBLIC = Path(__file__).resolve().parents[2] / "web" / "public"


def _email(prefix, si="txt", bl="txt"):
    return {"email_id": f"upload_{prefix}", "from": "docs@shipper.example",
            "subject": "TO CONFIRM DOCS - sample shipment",
            "body": "Please compare the attached SI and draft BL and confirm.",
            "attachments": [f"samples/{prefix}_SI.{si}", f"samples/{prefix}_BL.{bl}"]}


@pytest.mark.parametrize("prefix,si,bl,status,reason", [
    ("clean-txt", "txt", "txt", "OK", None),
    ("pdf-pair", "pdf", "pdf", "OK", None),
    ("excel-word", "xlsx", "docx", "OK", None),
    ("scanned", "pdf", "pdf", "NEEDS_REVIEW", "unreadable"),
    ("wrong-doc", "txt", "txt", "NEEDS_REVIEW", "wrong_doc_type"),
])
def test_sample_kit_verdicts(prefix, si, bl, status, reason):
    r = process_email(_email(prefix, si, bl), str(PUBLIC))
    assert (r["category"], r["status"], r["review_reason"]) == ("BL_COMPARISON", status, reason)


def test_editing_the_bl_weight_creates_exactly_one_mismatch(tmp_path):
    kit = tmp_path / "samples"
    kit.mkdir()
    shutil.copy(PUBLIC / "samples" / "clean-txt_SI.txt", kit)
    bl = (PUBLIC / "samples" / "clean-txt_BL.txt").read_text(encoding="utf-8")
    (kit / "clean-txt_BL.txt").write_text(bl.replace("21,577 KG", "22,577 KG"), encoding="utf-8")

    r = process_email(_email("clean-txt"), str(tmp_path))

    assert (r["status"], r["defect_fields"]) == ("MISMATCH", ["gross_weight_kg"])
```

Run: `T` with `api/tests/test_sample_kit.py`
Expected: FAIL (the sample files do not exist, so the documents come back unreadable or missing).

- [ ] **Step 2: Create the sample kit**

```bash
B=docs-provided/problem-statement/sdoc-hackathon-bundle/attachments
S=web/public/samples
mkdir -p "$S"
cp "$B/email_001_SI.txt"  "$S/clean-txt_SI.txt"
cp "$B/email_001_BL.txt"  "$S/clean-txt_BL.txt"
cp "$B/email_059_SI.pdf"  "$S/pdf-pair_SI.pdf"
cp "$B/email_059_BL.pdf"  "$S/pdf-pair_BL.pdf"
cp "$B/email_055_SI.xlsx" "$S/excel-word_SI.xlsx"
cp "$B/email_055_BL.docx" "$S/excel-word_BL.docx"
cp "$B/email_512_SI.pdf"  "$S/scanned_SI.pdf"
cp "$B/email_512_BL.pdf"  "$S/scanned_BL.pdf"
cp "$B/email_501_SI.txt"  "$S/wrong-doc_SI.txt"
cp "$B/email_501_BL.txt"  "$S/wrong-doc_BL.txt"
```

Run: `T` with `api/tests/test_sample_kit.py`
Expected: `6 passed`.

- [ ] **Step 3: Retry button, run errors, navigation**

Create `web/app/components/RetryButton.tsx`:

```tsx
"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { request } from "@/lib/api";
import { useReviewer } from "./Reviewer";

export default function RetryButton({ emailId, label = "Retry" }: { emailId: string; label?: string }) {
  const router = useRouter();
  const { unlocked } = useReviewer();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function retry() {
    setBusy(true); setError("");
    try { await request(`/api/emails/${emailId}/reprocess`, { method: "POST" }); router.refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not reprocess this email."); }
    finally { setBusy(false); }
  }
  return <span className="retry"><button className="ghost" onClick={retry} disabled={busy || !unlocked} title={unlocked ? undefined : "Unlock reviewer mode to reprocess"}>{busy ? "Processing…" : label}</button>{error && <small className="error" role="alert">{error}</small>}</span>;
}
```

In `web/lib/api.ts`, add `error: string | null;` as the last field of `type Run`.

In `web/app/review/page.tsx`:
- Add `import RetryButton from "../components/RetryButton";` after the StatusBadge import.
- Replace `<td><Link className="text-link" href={`/emails/${r.email_id}`}>Inspect documents →</Link></td>` with:

```tsx
<td><div className="actions"><Link className="text-link" href={`/emails/${r.email_id}`}>Inspect documents →</Link>{r.status === "FAILED" && <RetryButton emailId={r.email_id}/>}</div></td>
```

In `web/app/emails/[id]/page.tsx`:
- Add `import RetryButton from "../../components/RetryButton";` after the StatusBadge import.
- Replace `<StatusBadge status={r?.status ?? null}/></div>` (the end of the `page-heading` div) with:

```tsx
<div className="actions"><StatusBadge status={r?.status ?? null}/><RetryButton emailId={e.email_id} label="Reprocess"/></div></div>
```

In `web/app/runs/page.tsx`, replace:

```tsx
<td><span className={`badge ${r.finished_at ? "ok" : "warn"}`}>{r.finished_at ? "Complete" : "Running"}</span></td>
```

with:

```tsx
<td><span className={`badge ${r.error ? "bad" : r.finished_at ? "ok" : "warn"}`}>{r.error ? "Failed" : r.finished_at ? "Complete" : "Running"}</span>{r.error && <small>{r.error}</small>}</td>
```

In `web/app/components/Navigation.tsx`, change the nav array from:

```tsx
[["/", "Overview", "◫"], ["/inbox", "Inbox", "▤"], ["/review", "Human review", "◎"], ["/runs", "Pipeline runs", "↗"]]
```

to:

```tsx
[["/", "Overview", "◫"], ["/inbox", "Inbox", "▤"], ["/review", "Human review", "◎"], ["/intake", "Try your own", "＋"], ["/runs", "Pipeline runs", "↗"]]
```

- [ ] **Step 4: Intake page**

Create `web/app/intake/IntakeForm.tsx`:

```tsx
"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { request } from "@/lib/api";
import { LockedHint, useReviewer } from "../components/Reviewer";

const EXAMPLE = {
  sender: "docs@shipper.example",
  subject: "TO CONFIRM DOCS - sample shipment",
  body: "Hi team,\n\nPlease compare the attached SI and draft BL and confirm before we finalise.\n\nThanks",
};

export default function IntakeForm() {
  const router = useRouter();
  const { unlocked } = useReviewer();
  const [sender, setSender] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    const form = new FormData();
    form.set("sender", sender); form.set("subject", subject); form.set("body", body);
    files.forEach(f => form.append("files", f));
    try {
      const out = await request<{ email_id: string }>("/api/intake", { method: "POST", body: form });
      router.push(`/emails/${out.email_id}`);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not process this email."); setBusy(false); }
  }
  return <form className="panel intake-form" onSubmit={submit}>
    <div className="actions"><button type="button" className="ghost" onClick={() => { setSender(EXAMPLE.sender); setSubject(EXAMPLE.subject); setBody(EXAMPLE.body); }}>Fill example text</button></div>
    <label>From<input required value={sender} onChange={e => setSender(e.target.value)} maxLength={200} placeholder="sender@company.com"/></label>
    <label>Subject<input required value={subject} onChange={e => setSubject(e.target.value)} maxLength={300}/></label>
    <label>Body<textarea rows={6} value={body} onChange={e => setBody(e.target.value)} maxLength={20000}/></label>
    <label>Attachments (up to 4 · .txt .pdf .docx .xlsx · 5 MB each)<input type="file" multiple accept=".txt,.pdf,.docx,.xlsx" onChange={e => setFiles(Array.from(e.target.files ?? []).slice(0, 4))}/></label>
    {files.length > 0 && <p className="muted">{files.map(f => f.name).join(" · ")}</p>}
    <LockedHint action="submit an email"/>
    <div className="actions"><button disabled={busy || !unlocked}>{busy ? "Checking documents…" : "Check this email"}</button></div>
    {error && <p className="error" role="alert">{error}</p>}
  </form>;
}
```

Create `web/app/intake/page.tsx`:

```tsx
import IntakeForm from "./IntakeForm";
export const dynamic = "force-dynamic";

const SAMPLES = [
  { title: "Matching text pair", note: "Everything agrees. Edit a weight or port in the BL to create a mismatch.", files: ["clean-txt_SI.txt", "clean-txt_BL.txt"] },
  { title: "PDF pair", note: "Text-layer PDFs with a container table.", files: ["pdf-pair_SI.pdf", "pdf-pair_BL.pdf"] },
  { title: "Excel SI + Word BL", note: "Different formats and bilingual labels.", files: ["excel-word_SI.xlsx", "excel-word_BL.docx"] },
  { title: "Scanned PDFs", note: "No text layer, so it is escalated as unreadable. Then use Run AI assist to read it with the vision model.", files: ["scanned_SI.pdf", "scanned_BL.pdf"] },
  { title: "Wrong document", note: "The “BL” is a different document type, so it is escalated for review.", files: ["wrong-doc_SI.txt", "wrong-doc_BL.txt"] },
];

export default function IntakePage() {
  return <>
    <div className="page-heading"><div><div className="eyebrow">Live intake</div><h1>Try it with your own email.</h1><p>Submit a message with an SI and a draft BL. It runs through the same pipeline as the inbox and opens the result.</p></div></div>
    <div className="grid2"><IntakeForm/><section className="panel"><h2>Sample kit</h2><p className="muted">No shipping documents to hand? Download a pair and attach both files.</p><div className="sample-list">{SAMPLES.map(s => <div key={s.title}><strong>{s.title}</strong><small className="muted">{s.note}</small><div>{s.files.map(f => <a key={f} className="text-link" href={`/samples/${f}`} download>{f}</a>)}</div></div>)}</div></section></div>
  </>;
}
```

Append to `web/app/globals.css`:

```css
.intake-form { display:grid; gap:14px; }
.intake-form label { display:grid; gap:6px; font-size:12px; font-weight:600; }
.sample-list { display:grid; gap:16px; margin-top:14px; }
.sample-list small { display:block; margin:3px 0 6px; font-size:11px; }
.sample-list a { margin-right:14px; font-size:12px; }
.retry { display:inline-flex; gap:8px; align-items:center; }
```

- [ ] **Step 5: Verify**

Run: `W`, then `T`, then `L`
Expected: web build succeeds; `144 passed`; `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add web/public/samples web/app/intake web/app/components/RetryButton.tsx web/app/components/Navigation.tsx web/app/review/page.tsx "web/app/emails/[id]/page.tsx" web/app/runs/page.tsx web/lib/api.ts web/app/globals.css api/tests/test_sample_kit.py
git commit -m "Add the try-your-own intake page, sample kit and retry actions

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Redeploy and check intake live**

```bash
bash scripts/gcp/deploy.sh && bash scripts/gcp/smoke.sh
```

Then, in the browser on `WEB_URL`: unlock, go to **Try your own**, press **Fill example text**, and attach `clean-txt_SI.txt` plus a copy of `clean-txt_BL.txt` with `21,577` changed to `22,577`. Submit. Expected: the email page shows `MISMATCH` on Gross weight.
If the submit fails with a permission error on `/data/uploads`, the bucket mount options were rejected. Change `mount-options=uid=10001;gid=10001` in `deploy.sh` to `mount-options=file-mode=777;dir-mode=777`, redeploy, and commit the fix ("Make the uploads mount writable for the app user").

---

### Task 18: Uptime checks and alerting

**Files:**
- Create: `scripts/gcp/monitoring.sh`

**Interfaces:**
- Consumes: `gapi`, `find_channel`, `project_number` from `common.sh`; the channel created by bootstrap.
- Produces: two uptime checks (`sdoc-web` → `/healthz`, `sdoc-api-livez` → `/livez`), every 5 min from 3 regions, and alert policy `SDOC uptime` sending to `ALERT_EMAIL`.

- [ ] **Step 1: Write the script**

Create `scripts/gcp/monitoring.sh`:

```bash
#!/usr/bin/env bash
# Uptime checks every 5 min from 3 regions on web /healthz and api /livez.
# They also keep the scale-to-zero services warm, without waking Neon.
# One alert policy emails ALERT_EMAIL when either check keeps failing.
#   PROJECT_ID=... REGION=... ALERT_EMAIL=... bash scripts/gcp/monitoring.sh
set -euo pipefail
cd "$(dirname "$0")"
: "${ALERT_EMAIL:?set ALERT_EMAIL}"
source ./common.sh
MON="https://monitoring.googleapis.com/v3/projects/$PROJECT_ID"
PROJECT_NUMBER="$(project_number)"
export PROJECT_NUMBER

uptime_id() { # uptime_id DISPLAY_NAME -> check id or ""
  gapi GET "$MON/uptimeCheckConfigs" |
    "$PY" -c 'import json,sys; n=sys.argv[1]; print(next((c["name"].rsplit("/",1)[-1] for c in json.load(sys.stdin).get("uptimeCheckConfigs", []) if c["displayName"] == n), ""))' "$1"
}

ensure_uptime() { # ensure_uptime DISPLAY_NAME HOST PATH -> check id
  local id body
  id="$(uptime_id "$1")"
  if [[ -z "$id" ]]; then
    body="$("$PY" -c '
import json, sys
name, host, path, project = sys.argv[1:5]
print(json.dumps({
    "displayName": name,
    "monitoredResource": {"type": "uptime_url", "labels": {"project_id": project, "host": host}},
    "httpCheck": {"path": path, "port": 443, "useSsl": True, "validateSsl": True},
    "period": "300s", "timeout": "10s",
    "selectedRegions": ["ASIA_PACIFIC", "EUROPE", "USA_VIRGINIA"],
}))' "$1" "$2" "$3" "$PROJECT_ID")"
    id="$(gapi POST "$MON/uptimeCheckConfigs" "$body" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["name"].rsplit("/",1)[-1])')"
  fi
  echo "$id"
}

WEB_CHECK="$(ensure_uptime sdoc-web "sdoc-web-$PROJECT_NUMBER.$REGION.run.app" /healthz)"
API_CHECK="$(ensure_uptime sdoc-api-livez "sdoc-api-$PROJECT_NUMBER.$REGION.run.app" /livez)"
CHANNEL="$(find_channel "$ALERT_EMAIL")"
[[ -n "$CHANNEL" ]] || { echo "no alert channel for $ALERT_EMAIL; run bootstrap.sh first" >&2; exit 1; }

has_policy="$(gapi GET "$MON/alertPolicies" | "$PY" -c 'import json,sys; print(any(p["displayName"] == "SDOC uptime" for p in json.load(sys.stdin).get("alertPolicies", [])))')"
if [[ "$has_policy" != "True" ]]; then
  policy="$("$PY" -c '
import json, sys
web, api, channel = sys.argv[1:4]
def down(check_id, label):
    return {"displayName": f"{label} failing", "conditionThreshold": {
        "filter": ("metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" "
                   f"AND resource.type=\"uptime_url\" AND metric.label.check_id=\"{check_id}\""),
        "aggregations": [{"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_NEXT_OLDER",
                          "crossSeriesReducer": "REDUCE_COUNT_FALSE", "groupByFields": ["resource.label.*"]}],
        "comparison": "COMPARISON_GT", "thresholdValue": 1, "duration": "600s",
        "trigger": {"count": 1}}}
print(json.dumps({"displayName": "SDOC uptime", "combiner": "OR",
                  "conditions": [down(web, "web"), down(api, "api")],
                  "notificationChannels": [channel]}))' "$WEB_CHECK" "$API_CHECK" "$CHANNEL")"
  gapi POST "$MON/alertPolicies" "$policy" >/dev/null
fi
echo "uptime checks: $WEB_CHECK, $API_CHECK -> alert policy 'SDOC uptime' -> $ALERT_EMAIL"
```

- [ ] **Step 2: Selftest (syntax) and apply**

Run: `bash scripts/gcp/selftest.sh`, then `bash scripts/gcp/monitoring.sh` with `PROJECT_ID`, `REGION` and `ALERT_EMAIL` exported.
Expected: `selftest OK`; then `uptime checks: sdoc-web-…, sdoc-api-livez-… -> alert policy 'SDOC uptime' -> <email>`. Run it a second time: the same output, and nothing is duplicated (idempotent).

- [ ] **Step 3: Commit**

```bash
git add scripts/gcp/monitoring.sh
git commit -m "Add uptime checks that keep the demo warm and alert on outages

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 18b: Billing kill switch (hard stop at $10)

Requested by the user on top of the spec's alert-only budget. It is armed at **$10**, double the alert budget, because unlinking billing takes the whole demo down and needs a manual relink. Budget data lags real spend by hours, so this is a backstop, not a rate limiter.

**Files:**
- Create: `scripts/gcp/killswitch/main.py`, `scripts/gcp/killswitch/requirements.txt`, `scripts/gcp/killswitch.sh`, `api/tests/test_killswitch.py`

**Interfaces:**
- Consumes: `common.sh` names; the budget from Task 13.
- Produces: Pub/Sub topic `budget-alerts`, budget `sdoc-verifier-killswitch` ($10 → Pub/Sub), service account `sdoc-killswitch` with `roles/billing.projectManager`, and Cloud Function (gen2) `sdoc-billing-killswitch` running `stop_billing`. The decision logic lives in `should_stop(payload: dict) -> bool` so it is testable without GCP.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_killswitch.py`:

```python
"""The billing kill switch fires only when reported cost reaches the budget.

The function itself runs on Cloud Functions; only its decision rule is
imported here, so the test needs no GCP libraries.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "scripts" / "gcp" / "killswitch" / "main.py"


def _load():
    spec = importlib.util.spec_from_file_location("killswitch_main", SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["killswitch_main"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("payload,expected", [
    ({"costAmount": 10.0, "budgetAmount": 10.0}, True),
    ({"costAmount": 12.5, "budgetAmount": 10.0}, True),
    ({"costAmount": 9.99, "budgetAmount": 10.0}, False),
    ({"costAmount": 0, "budgetAmount": 10.0}, False),
    ({}, False),
    ({"costAmount": "not-a-number", "budgetAmount": 10.0}, False),
    ({"costAmount": 10.0, "budgetAmount": 0}, False),
])
def test_only_a_real_overrun_stops_billing(payload, expected):
    assert _load().should_stop(payload) is expected
```

Note: `main.py` must keep its GCP imports inside the functions that use them, so importing the module is side-effect free.

- [ ] **Step 2: Run to verify failure**

Run: `T` with `api/tests/test_killswitch.py`
Expected: FAIL — `scripts/gcp/killswitch/main.py` does not exist.

- [ ] **Step 3: Write the function**

Create `scripts/gcp/killswitch/main.py`:

```python
"""Unlink the billing account when the kill-switch budget is reached.

Triggered by Pub/Sub messages from a Cloud Billing budget. Budget updates
arrive continuously, most of them well under budget, so the decision rule is
kept separate and tested in api/tests/test_killswitch.py.

WARNING: unlinking billing stops every service in the project at once.
Recovery is manual — see docs/deploy.md.
"""
import base64
import json
import logging
import os

import functions_framework

TARGET_PROJECT_ID = os.environ.get("TARGET_PROJECT_ID", "")
log = logging.getLogger("killswitch")


def should_stop(payload: dict) -> bool:
    """True only when reported cost has reached a positive budget."""
    try:
        cost = float(payload.get("costAmount", 0))
        budget = float(payload.get("budgetAmount", 0))
    except (TypeError, ValueError):
        return False
    return budget > 0 and cost >= budget


def _disable_billing(project_id: str) -> str:
    from googleapiclient import discovery

    billing = discovery.build("cloudbilling", "v1", cache_discovery=False)
    name = f"projects/{project_id}"
    try:
        if not billing.projects().getBillingInfo(name=name).execute().get("billingEnabled"):
            return "billing was already disabled"
    except Exception:  # keep going: the unlink itself is what matters
        log.warning("could not read billing info; attempting the unlink anyway", exc_info=True)
    billing.projects().updateBillingInfo(name=name, body={"billingAccountName": ""}).execute()
    return "billing disabled"


@functions_framework.cloud_event
def stop_billing(cloud_event) -> str:
    payload = json.loads(base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8"))
    if not should_stop(payload):
        return f"under budget: {payload.get('costAmount')} of {payload.get('budgetAmount')}"
    if not TARGET_PROJECT_ID:
        raise RuntimeError("TARGET_PROJECT_ID is not set")
    outcome = _disable_billing(TARGET_PROJECT_ID)
    log.error("KILL SWITCH: %s for %s (cost %s of %s)", outcome, TARGET_PROJECT_ID,
              payload.get("costAmount"), payload.get("budgetAmount"))
    return outcome
```

Create `scripts/gcp/killswitch/requirements.txt`:

```text
functions-framework==3.*
google-api-python-client==2.*
```

- [ ] **Step 4: Run the test**

Run: `T` with `api/tests/test_killswitch.py`
Expected: `7 passed`. If `functions_framework` is not installed locally, the import fails — in that case run `uv run --with functions-framework pytest api/tests/test_killswitch.py -q -p no:cacheprovider --basetemp=.pytest-tmp` and add that note to the step, since CI installs only the project's own dependencies.

- [ ] **Step 5: Write the deploy script**

Create `scripts/gcp/killswitch.sh`:

```bash
#!/usr/bin/env bash
# Hard stop: a $10 budget publishes to Pub/Sub and a Cloud Function unlinks
# the billing account. Armed at 2x the $5 alert budget, because this takes the
# whole demo down and recovery is manual (docs/deploy.md).
#   PROJECT_ID=... REGION=... BILLING_ACCOUNT=... bash scripts/gcp/killswitch.sh
set -euo pipefail
cd "$(dirname "$0")"
: "${BILLING_ACCOUNT:?set BILLING_ACCOUNT}"
KILL_BUDGET_USD="${KILL_BUDGET_USD:-10}"
source ./common.sh
quiet() { "$@" >/dev/null 2>&1; }
KILL_SA="sdoc-killswitch@$PROJECT_ID.iam.gserviceaccount.com"
TOPIC=budget-alerts
PROJECT_NUMBER="$(project_number)"

echo "==> APIs"
gcloud services enable pubsub.googleapis.com cloudfunctions.googleapis.com \
  cloudbuild.googleapis.com eventarc.googleapis.com

echo "==> topic $TOPIC"
quiet gcloud pubsub topics describe "$TOPIC" || gcloud pubsub topics create "$TOPIC"

echo "==> service account + billing permission"
quiet gcloud iam service-accounts describe "$KILL_SA" ||
  gcloud iam service-accounts create sdoc-killswitch --display-name="sdoc-killswitch"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$KILL_SA" \
  --role=roles/billing.projectManager --condition=None >/dev/null
# Cloud Build needs to build the function image in a fresh project
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role=roles/cloudbuild.builds.builder --condition=None >/dev/null

echo "==> function sdoc-billing-killswitch"
gcloud functions deploy sdoc-billing-killswitch \
  --gen2 --region="$REGION" --runtime=python312 --source=./killswitch \
  --entry-point=stop_billing --trigger-topic="$TOPIC" \
  --service-account="$KILL_SA" --set-env-vars="TARGET_PROJECT_ID=$PROJECT_ID" \
  --max-instances=1 --memory=256Mi --quiet

echo "==> budget sdoc-verifier-killswitch (US\$$KILL_BUDGET_USD -> $TOPIC)"
if ! gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" --format="value(displayName)" | grep -qx "sdoc-verifier-killswitch"; then
  gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" \
    --display-name="sdoc-verifier-killswitch" --budget-amount="${KILL_BUDGET_USD}USD" \
    --filter-projects="projects/$PROJECT_NUMBER" --threshold-rule=percent=1.0 \
    --all-updates-rule-pubsub-topic="projects/$PROJECT_ID/topics/$TOPIC" >/dev/null
fi

cat <<EOF

Kill switch armed: billing is unlinked automatically if reported spend on
$PROJECT_ID reaches US\$$KILL_BUDGET_USD. Budget data lags by hours.
Recovery: relink billing (console -> Billing -> link account), then
  bash scripts/gcp/deploy.sh
Disarm:  gcloud functions delete sdoc-billing-killswitch --region=$REGION
EOF
```

- [ ] **Step 6: Verify syntax, then arm it**

Run: `bash scripts/gcp/selftest.sh`, then `bash scripts/gcp/killswitch.sh` with `PROJECT_ID`, `REGION` and `BILLING_ACCOUNT` exported.
Expected: `selftest OK`; the function deploys (the first build takes 1–3 min) and the script prints "Kill switch armed".
If the build fails with a Cloud Build or Artifact Registry permission error, wait a minute for the IAM grant to propagate and rerun; the script is idempotent.

- [ ] **Step 7: Prove it without spending anything**

Publish a fake under-budget message and confirm the function declines to act:

```bash
gcloud pubsub topics publish budget-alerts --message='{"costAmount":1.0,"budgetAmount":10.0}'
sleep 30
gcloud functions logs read sdoc-billing-killswitch --region="$REGION" --limit=10 | grep -i "under budget"
gcloud billing projects describe "$PROJECT_ID" --format="value(billingEnabled)"
```

Expected: a log line `under budget: 1.0 of 10.0`, and `billingEnabled` still `True`.
**Do not publish a message at or over the budget** — that really would disable billing.

- [ ] **Step 8: Commit**

```bash
git add scripts/gcp/killswitch scripts/gcp/killswitch.sh api/tests/test_killswitch.py
git commit -m "Add a $10 billing kill switch behind the alert budget

Unlinks billing if reported spend reaches twice the alert budget. Armed
high on purpose: it stops the whole demo and recovery is manual.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 19: Deploy on merge

**Files:**
- Create: `.github/workflows/deploy.yml`

**Interfaces:**
- Consumes: `deploy.sh`, `smoke.sh` (Task 13); the repo variables printed by bootstrap (Task 14).

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy

on:
  push:
    branches: [main]
  workflow_dispatch:

concurrency:
  group: deploy-production
  cancel-in-progress: false

permissions:
  contents: read
  id-token: write      # GitHub OIDC -> Workload Identity Federation, no keys

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: uv sync --frozen
      - run: uv run pytest api/tests -q
        env:
          DATA_DIR: docs-provided/problem-statement/sdoc-hackathon-bundle

  deploy:
    needs: test
    if: vars.GCP_PROJECT_ID != ''
    runs-on: ubuntu-latest
    env:
      PROJECT_ID: ${{ vars.GCP_PROJECT_ID }}
      PROJECT_NUMBER: ${{ vars.GCP_PROJECT_NUMBER }}
      REGION: ${{ vars.GCP_REGION }}
      IMAGE_TAG: ${{ github.sha }}
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ vars.GCP_WIF_PROVIDER }}
          service_account: ${{ vars.GCP_DEPLOYER_SA }}
      - uses: google-github-actions/setup-gcloud@v2
      - run: bash scripts/gcp/deploy.sh
      - run: bash scripts/gcp/smoke.sh
```

- [ ] **Step 2: Validate the YAML locally**

Run: `uv run python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/deploy.yml')); print('yaml-ok')"`
Expected: `yaml-ok`. If PyYAML is missing, use `uv run --with pyyaml python -c ...`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "Deploy to Cloud Run on every merge to main

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Hand the variables to the repo admin**

The user does not have admin on `applejuice8/secret-hack`. Give Colin (the repo owner) these commands, filled with the bootstrap output:

```bash
gh variable set GCP_PROJECT_ID     -R applejuice8/secret-hack -b "<value>"
gh variable set GCP_PROJECT_NUMBER -R applejuice8/secret-hack -b "<value>"
gh variable set GCP_REGION         -R applejuice8/secret-hack -b "<value>"
gh variable set GCP_WIF_PROVIDER   -R applejuice8/secret-hack -b "<value>"
gh variable set GCP_DEPLOYER_SA    -R applejuice8/secret-hack -b "<value>"
```

Until they are set, the `deploy` job is skipped, and `deploy.sh` from a laptop remains the way to deploy.

---

### Task 20: Runbook, README, and live acceptance

**Files:**
- Create: `docs/deploy.md`
- Modify: `README.md`

- [ ] **Step 1: Write the runbook**

Create `docs/deploy.md`:

````markdown
# Deploying SDOC Verifier to Google Cloud Run

Runbook for the public demo. Design and budget rationale:
[`docs/superpowers/specs/2026-09-20-cloud-deploy-design.md`](superpowers/specs/2026-09-20-cloud-deploy-design.md).

## What runs where

| Piece | Cloud Run resource | Access |
|---|---|---|
| `sdoc-web` | service (Next.js standalone) | public |
| `sdoc-api` | service (FastAPI) | public URL; writes need the reviewer passcode |
| `sdoc-scorer` | service (provided scorer) | private: only `sdoc-api` may call it |
| `sdoc-worker` | job (api image) | started by `sdoc-api` per run, or by an operator |

Also: Artifact Registry `sdoc` (keeps 3 images), Secret Manager (`NEON_DB_URI`,
`OPENROUTER_API_KEY`, `DEMO_PASSCODE`, `GROUND_TRUTH`), bucket
`<project>-sdoc-uploads` mounted at `/data/uploads` (30-day expiry), uptime checks
and an alert policy, and a US$5 budget.

## Prerequisites

- `gcloud` logged in, on a billing account you administer
- Docker running, Python 3 on PATH, bash (Git Bash on Windows)
- The team's `.env` at the repo root, and `secrets/ground_truth.json` (see `secrets/README.md`)

## One-time setup

```bash
bash scripts/gcp/neon-region.sh .env          # prints the matching GCP region
export PROJECT_ID=sdoc-verifier-<6 hex> REGION=<gcp region> \
       BILLING_ACCOUNT=<id> ALERT_EMAIL=<email>
bash scripts/gcp/bootstrap.sh                 # project, APIs, IAM, bucket, budget
bash scripts/gcp/set-secrets.sh .env          # operator only; asks for the passcode
bash scripts/gcp/deploy.sh                    # build, push, deploy everything
bash scripts/gcp/demo-reset.sh                # first seed: ingest, run, score
bash scripts/gcp/smoke.sh                     # must print "smoke OK"
bash scripts/gcp/monitoring.sh                # uptime checks + alert policy
```

Then a repo admin sets the five GitHub variables that `bootstrap.sh` printed
(`gh variable set …`), and every merge to `main` deploys through
`.github/workflows/deploy.yml`.

## Everyday operations

| Task | Command |
|---|---|
| Deploy by hand | `bash scripts/gcp/deploy.sh && bash scripts/gcp/smoke.sh` |
| Disarm the kill switch | `gcloud functions delete sdoc-billing-killswitch --region "$REGION"` |
| Recover after it fired | relink billing in the console, then `bash scripts/gcp/deploy.sh` |
| Reset the demo | `bash scripts/gcp/demo-reset.sh` |
| Rotate the passcode | `bash scripts/gcp/set-secrets.sh .env` then `deploy.sh` |
| Recent errors | `gcloud logging read 'resource.type="cloud_run_revision" AND severity>=WARNING' --limit 50` |
| Worker logs | `gcloud logging read 'resource.type="cloud_run_job"' --limit 50` |

## Rollback

```bash
gcloud run revisions list --service sdoc-web --region "$REGION"
gcloud run services update-traffic sdoc-web --region "$REGION" --to-revisions=<REVISION>=100
```

Do the same for `sdoc-api`. For the job:
`gcloud run jobs update sdoc-worker --region "$REGION" --image <previous image>`.

## Costs

| Item | Setting | Expected |
|---|---|---|
| web, api | min 0 / max 2 instances, request-based billing | inside the free tier |
| scorer | min 0 / max 1 | cents |
| worker job | 1 task, ~1–3 min per run | cents |
| Artifact Registry | 3 images kept | around the 0.5 GB free allowance |
| Secret Manager, Storage, Monitoring | 4 secrets, tiny bucket, 2 uptime checks | cents |

Expected spend through judging: **under US$1**. The US$5 budget only sends
alerts; the instance caps are what actually bound spend.

A second budget at US$10 is a hard stop: it publishes to the `budget-alerts`
topic, and the `sdoc-billing-killswitch` function unlinks the billing account,
which stops every service at once. It is armed at twice the alert budget on
purpose, and budget data lags real spend by hours, so treat it as a backstop
rather than a rate limiter. Recovery is manual: relink billing, then redeploy.

## Teardown

`gcloud projects delete "$PROJECT_ID"` stops all billing. The project can be
restored for 30 days.

## Troubleshooting

| Symptom | Fix |
|---|---|
| deploy: secret "has no versions" | run `set-secrets.sh` |
| job deploy: volume needs gen2 | add `--execution-environment gen2` to the jobs line in `deploy.sh` |
| intake: permission denied on `/data/uploads` | change the bucket `mount-options` in `deploy.sh` to `file-mode=777;dir-mode=777` |
| smoke: "writes are NOT protected" | `DEMO_PASSCODE` is empty: rerun `set-secrets.sh`, then `deploy.sh` |
| UI: "Could not start the run" (502) | rerun `deploy.sh` (re-grants `run.jobsExecutorWithOverrides`) |
| runs never get a score | `gcloud run services get-iam-policy sdoc-scorer --region "$REGION"` must list `sdoc-api` as `run.invoker` |
````

- [ ] **Step 2: Update the README**

In `README.md` section 1, replace the three service rows (`web`, `api`, `scorer`) of the service table with:

```markdown
| `web` | node:22-alpine, Next.js standalone, non-root | 3000 | Dashboard, inbox, diff view, review queue, intake, runs; proxies `/api/*` at request time |
| `api` | python:3.13-slim (uv-built venv), non-root, dataset baked in | 8000 | Pipeline, REST API, Neon access; the same image runs the worker job |
| `scorer` | python:3.12-slim (provided) | 8080→8000 | Evaluation against the private answer key (kept in `secrets/`, never in git) |
```

Replace section 9 ("Run it") entirely with:

````markdown
## 9. Run it

```bash
cp .env.example .env     # NEON_DB_URI; OPENROUTER_API_KEY optional; DEMO_PASSCODE optional locally
cp <organizer zip>/data_v2/ground_truth.json secrets/   # only for the local scorer
docker compose up --build
```

- web → http://localhost:3000 · api → http://localhost:8000 (`/docs`) ·
  scorer → http://localhost:8080 · `curl localhost:8000/health` shows what
  the API can reach

```bash
# first-time data load + full run + score (same command the cloud job runs)
docker compose exec api python -m pipeline.worker seed
```

Local dev without Docker: `uv sync` · `cd web && pnpm install` ·
`uv run uvicorn app.main:app --app-dir api --reload` · `cd web && pnpm dev`.

Tests: `uv run pytest api/tests -v` · lint: `uv run ruff check api` ·
script checks: `bash scripts/gcp/selftest.sh`. CI runs all of them on every
push, plus `tsc --noEmit`, `next build`, and a container smoke test that boots
both images. The API job runs with no database and no API key.

## 10. Cloud deployment (Google Cloud Run)

**Live demo:** <WEB_URL> · API docs: <API_URL>/docs · reviewer passcode: in
the submission form.

```
 browser ──► sdoc-web (public) ──/api/* proxy──► sdoc-api (public; writes need passcode)
                                                   │  ├─ Neon Postgres
                                                   │  ├─ OpenRouter
                                                   │  ├─ gs://…-sdoc-uploads  (mounted /data/uploads)
                                                   │  ├─ sdoc-scorer (IAM-private, ID token)
                                                   │  └─ sdoc-worker (Cloud Run Job, one per run)
 GitHub main ──► Actions (OIDC, no keys) ──► Artifact Registry ──► Cloud Run
```

Everything scales to zero under a US$5 budget, with hard instance caps. Setup,
operations, rollback and costs: [`docs/deploy.md`](docs/deploy.md).
````

In section 8, add these lines to the layout tree directly above the `.github/workflows/ci.yml` line:

```text
├── scripts/gcp/                bootstrap · set-secrets · deploy · smoke · reset · monitoring
├── docs/deploy.md              Cloud Run runbook
├── secrets/                    git-ignored (local answer key)
├── .github/workflows/deploy.yml  deploy on merge (Workload Identity Federation)
```

and change the `web/next.config.ts` line to `│   ├── next.config.ts          standalone output (API proxy: app/api/[...path])`.

Fill `<WEB_URL>` and `<API_URL>` with the real URLs from Task 14.

- [ ] **Step 3: Live acceptance (the spec's checklist)**

On `WEB_URL`, in a private window, confirm each item and note any failure:
1. The dashboard loads and 520+ emails are listed.
2. `email_004` shows the consignee and notify-party mismatch side by side.
3. The Review queue lists 20 escalations with reasons.
4. A write while locked is refused. Unlocking with the passcode works. Confirming a case works.
5. Intake with the edited `clean-txt` pair gives `MISMATCH` on Gross weight.
6. Intake with the `scanned` pair gives `NEEDS_REVIEW / Document could not be read`; **Run AI assist** returns the model's reading.
7. **Run inbox checks** on the Runs page completes, and the score appears.
8. Intake of a `.txt` file renamed to `.pdf` is rejected with a clear message. **Reprocess** on `email_004` adds a new result with the same verdict.
9. `bash scripts/gcp/demo-reset.sh` removes the uploads and restores the clean state.
10. `gcloud billing budgets list --billing-account=$BILLING_ACCOUNT` shows `sdoc-verifier` at 5 USD and `sdoc-verifier-killswitch` at 10 USD; `gcloud run services list --region $REGION` shows the three services; `gcloud billing projects describe $PROJECT_ID` still reports `billingEnabled: True`.

- [ ] **Step 4: Commit**

```bash
git add docs/deploy.md README.md
git commit -m "Document the Cloud Run deployment and link the live demo

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 21: Publish the branch (gated)

- [ ] **Step 1: Final verification**

Run: `T`, `L`, `W`, `bash scripts/gcp/selftest.sh`, `git status --short`
Expected: `144 passed`; `All checks passed!`; the web build is green; `selftest OK`; a clean tree. `git ls-files | grep -c ground_truth` prints `0`.

- [ ] **Step 2: Ask the user before pushing**

Ask: "Push `feat/cloud-deploy` and open a PR against `main`?" Proceed only on an explicit yes. If PRs #1 and #2 are not merged yet, offer to target `feat/reliability-and-ci` instead.

- [ ] **Step 3: Push and open the PR (after approval)**

```bash
git push -u origin feat/cloud-deploy
gh pr create -R applejuice8/secret-hack --base main --head feat/cloud-deploy \
  --title "Cloud Run deployment, reviewer passcode, live intake" \
  --body "$(cat <<'EOF'
Implements docs/superpowers/specs/2026-09-20-cloud-deploy-design.md.

- Cloud Run: public web + api, IAM-private scorer, worker job per run; scale to zero under a US$5 budget
- Reviewer passcode on every write (reads stay open for judges)
- Fixes the build-time /api rewrite that broke browser actions under compose (runtime proxy route)
- Answer key removed from the repo (still in git history: team decision whether to rewrite it)
- Live intake with a sample kit, visible FAILED results and Retry/Reprocess
- Structured logs, uptime checks + alert, deploy on merge via Workload Identity Federation

Heads-up for web owners: next.config.ts rewrites() is replaced by app/api/[...path]/route.ts.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
