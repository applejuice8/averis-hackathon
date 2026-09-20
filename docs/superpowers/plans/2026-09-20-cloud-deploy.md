# Cloud Deployment, Demo Access & Live Intake Implementation Plan

> **Revised 2026-09-20:** Read [2026-09-20-vercel-cost-control-amendment.md](2026-09-20-vercel-cost-control-amendment.md) first. It is authoritative for deployment/costs. Tasks 1–5 were complete at `51fb6ab` (90 passing tests). The Vercel proxy is implemented locally; the RM40 billing guard is now deployed and armed. See `docs/cost-guard-status.md`. The web/backend application remains undeployed. Keep backend implementation detail below, but do not overwrite the newer files with historical snippets. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put SDOC Verifier on Vercel with a GCP Cloud Run backend, low fixed costs, a user-selected monthly billing-disconnect threshold, reviewer access, live intake, and verified deployment gates.

**Architecture:** Vercel builds `web/` natively and proxies browser API calls at request time. GCP hosts the API, private scorer and worker job; Neon and GCS remain. The billing guard must be armed before public deployment. See the amendment for the revised topology.

**Tech Stack:** Python 3.13 + uv, FastAPI, SQLAlchemy async + Neon Postgres, httpx, pytest/pytest-asyncio, Next.js 15 + React 19 + pnpm 10, Docker, bash + gcloud, Google Cloud Run (services + jobs), Artifact Registry, Secret Manager, Cloud Storage, Cloud Monitoring, Cloud Billing budgets, GitHub Actions + Workload Identity Federation.

**Spec:** `docs/superpowers/specs/2026-09-20-cloud-deploy-design.md`

## Global Constraints

- **Repo / branch:** `C:\Users\aloys\Averis Hackathon\secret-hack`, branch `feat/cloud-deploy`. Run every command from the repo root in **Git Bash** unless a step says otherwise.
- **Commit identity:** preserve the configured author; attribute only actual contributors. Do not add a Claude co-author trailer to work Claude did not write.
- **Never push** until Task 21 and the user's explicit approval.
- **Test command (T):** `DATA_DIR=docs-provided/problem-statement/sdoc-hackathon-bundle uv run pytest api/tests -q -p no:cacheprovider --basetemp=.pytest-tmp`. The default pytest temp dir is blocked on this machine; `--basetemp` fixes that. Historical baseline: **64 passed**; at completed Task 5: **90 passed**. Later expected test totals are historical estimates, not acceptance requirements.
- **Lint (L):** `uv run ruff check api`. It must print `All checks passed!` at the end of every Python task. Ruff config: line length 120, rules `E,F,I,B,UP,SIM`, `B008` ignored. Use `uv run ruff check api --fix` for import order.
- **Web check (W):** `cd web && pnpm install --frozen-lockfile && pnpm exec tsc --noEmit && pnpm build; cd ..`
- **Tests** need no database and no network (the repo's convention). Test files insert the api dir on `sys.path` and import `app.*` / `pipeline.*` with `# noqa: E402`.
- **Python deps:** only one new runtime dependency, `python-multipart` (Task 16). Use `uv add`, which also updates `uv.lock`.
- **pnpm:** `10.34.5`, pinned via `packageManager`. Node 22.
- **Budget:** US$5 spending target, not a guarantee. Use the user-selected RM40 monthly disconnect threshold; deploy/test/arm the guard before public deployment. API max 2, scorer max 1, min 0; worker task/parallelism 1 plus a separate global execution admission limit. No GCP web service, load balancer, or VPC connector.
- **Secrets:** the implementer never reads, prints, or copies `.env` or any secret value. `scripts/gcp/set-secrets.sh` and `scripts/gcp/neon-region.sh` are **run by the human operator** (the user).
- **Answer key:** `ground_truth.json` must never be committed again. It lives in git-ignored `secrets/` locally and in Secret Manager (`GROUND_TRUTH`) in the cloud.
- **Names:** GCP services `sdoc-api`, `sdoc-scorer`; Vercel project `sdoc-web`; job `sdoc-worker`; Artifact Registry repo `sdoc`; bucket `<PROJECT_ID>-sdoc-uploads`; service accounts `sdoc-api`, `sdoc-scorer`, `sdoc-deployer`; secrets `NEON_DB_URI`, `OPENROUTER_API_KEY`, `DEMO_PASSCODE`, `GROUND_TRUTH`; reviewer cookie `sdoc_reviewer`; header `X-Demo-Passcode`; uploads run label `Uploads & retries`.

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
| budgets alert only | Former Task 18b runs before app deployment; user selected RM40/month and guard is armed | delayed billing disconnect is a backstop, not an exact dollar cap |
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
| `web/next.config.ts` (modified) | native Vercel build, optional standalone for local Docker, runtime proxy |
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

> **Required correction:** normal `run_command` below does not score. Resolve the score lifecycle and enforce global execution admission/idempotency before launch; see the amendment.

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

### Task 10: Vercel web and runtime API proxy

See [2026-09-20-vercel-cost-control-amendment.md](2026-09-20-vercel-cost-control-amendment.md).

The runtime proxy, reviewer auth route, liveness endpoint and Vercel configuration now exist. Do not recreate them from the original snippets.

- [ ] Run `pnpm exec tsc --noEmit`, `pnpm build`, then `pnpm test:proxy` in `web/`.
- [ ] Vercel project root is `web`, Node 22, native Next.js build, Singapore (`sin1`). Set server-only `API_URL` after backend deployment.
- [ ] Confirm Hobby eligibility or explicitly choose a paid plan with independent spend controls; do not silently upgrade.
- [ ] Optional local Docker hardening can use `WEB_STANDALONE=1` during build, non-root runtime and pinned pnpm. No web image is pushed to GCP.
- [ ] Browser requests stay same-origin. Keep the 4,000,000-byte proxy limit and test API outage, authentication, 204/HEAD and upload failures.

---

### Task 11: Reviewer mode in the web app

See [2026-09-20-vercel-cost-control-amendment.md](2026-09-20-vercel-cost-control-amendment.md).

Use the existing `web/app/auth/reviewer/route.ts`; do not replace its origin checks, validation, cookie flags or timeout handling.

- [ ] Add the sidebar reviewer panel and provider. Unlock with POST `/auth/reviewer` and lock with DELETE; never store the passcode in localStorage or expose it through props.
- [ ] Keep the passcode input labelled, clear it after submission, show pending and incorrect/expired-passcode states, and retain public read access.
- [ ] Disable Run, AI assist, reviewer mutations, Retry and intake while locked; show an actionable explanation.
- [ ] Verify bad passcode fails, valid cookie permits a write, expiry/rotation re-locks on 401, and explicit lock clears access.
- [ ] API authorization remains mandatory even when UI controls are disabled.

---

### Task 12: Local parity and deployment checks

See [2026-09-20-vercel-cost-control-amendment.md](2026-09-20-vercel-cost-control-amendment.md).


- [ ] Keep compose for local development, with persistent uploads and a private scorer key from ignored `secrets/`.
- [ ] Harden and smoke-test API/scorer images. Optional web Docker parity uses standalone output explicitly; production web uses Vercel.
- [ ] CI requires Python lint/tests including the billing guard, TypeScript, native Next build and the production proxy stub test.
- [ ] Never upload `.env`, the answer key, or test credentials into an image/build context.

---

### Task 13: GCP scripts and billing guard before deployment

See [2026-09-20-vercel-cost-control-amendment.md](2026-09-20-vercel-cost-control-amendment.md).

Read the amendment's billing-guard operation first. The checked-in PowerShell guard setup supersedes the original Bash kill-switch example.

- [ ] Choose cutoff/currency, deploy guard in dry-run, observe the above-threshold no-op event, then arm. Confirm budget filters, retry delivery, private trigger identity and narrow runtime IAM.
- [ ] Bootstrap only `averis-email-system` (969206696114), region `asia-southeast1`, billing account `015CE1-381F1A-582702`. Every command passes an explicit project.
- [ ] Refuse absent/disabled/wrong billing. Never call `gcloud billing projects link` in normal bootstrap or deploy.
- [ ] Enable required APIs; configure Artifact Registry cleanup, GCS lifecycle, secrets and scoped identities. Include function build artifacts in storage accounting.
- [ ] Build/push API and scorer images only; resolve deployed URLs from service status, then configure worker and API.
- [ ] Add offline script checks for target selection, quoting, missing settings, no credentials in output, and no relink path.
- [ ] Before launching jobs enforce a database-backed active-run limit and idempotent dispatch; per-execution parallelism alone is insufficient.

---

### Task 14: First backend deploy and Vercel live URL

See [2026-09-20-vercel-cost-control-amendment.md](2026-09-20-vercel-cost-control-amendment.md).


- [ ] Complete Tasks 6–13 and verify the guard is armed before app deployment.
- [ ] Operator populates secrets without printing them. API must report writes protected and scorer must refuse unauthenticated requests.
- [ ] Deploy scorer, worker and API; seed dataset and establish the benchmark run/score.
- [ ] Create/configure the Vercel project with root `web`, server-side `API_URL`, native build and the chosen eligible plan. Keep production API_URL out of default previews.
- [ ] Test signed-out public reads, reviewer writes, run completion, private scorer, durable uploads and error paths on the actual public URL.
- [ ] Record deployment URLs, commit and guard state. No local build or mock test substitutes for this checkpoint.

---

### Task 15: Reprocess one email (visible, retryable failures)

> **Required correction:** the historical thread/`wait_for` example below is not hard cancellation. Add processing deadlines and duplicate prevention, or move processing into the durable worker before enabling retry in production. See the amendment.

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
- Produces: in `app.services.intake`, the constants `MAX_FILES=4`, `MAX_FILE_BYTES=3 MiB`, `MAX_TOTAL_BYTES=3 MiB`, `MAX_SENDER=200`, `MAX_SUBJECT=300`, `MAX_BODY=20000`, `ALLOWED_SUFFIXES`, and `IntakeError(ValueError)`, `IntakeFile(name, data)`, `safe_filename(raw, taken) -> str`, `check_content(name, data)`, `validate_submission(sender, subject, body, uploads) -> list[IntakeFile]`, `new_email_id(now=None, token=None) -> str`, `save_files(data_dir, subdir, email_id, files) -> list[str]`, `build_record(email_id, sender, subject, body, attachments) -> dict`. The endpoint is `POST /api/intake` (multipart fields `sender`, `subject`, `body`, `files[]`), returning `201 ProcessOutcome`, or `422 {"detail": str}` on invalid input.

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
    ([("big.txt", b"x" * (intake.MAX_FILE_BYTES + 1))], "larger than 3 MiB"),
    ([(f"f{i}.txt", b"x") for i in range(intake.MAX_FILES + 1)], "at most 4"),
])
def test_bad_files_are_rejected_with_a_reason(uploads, message):
    with pytest.raises(intake.IntakeError, match=message):
        intake.validate_submission("ops@example.com", "Check", "", uploads)


def test_total_size_is_capped():
    chunk = b"x" * (intake.MAX_FILE_BYTES - 10)
    with pytest.raises(intake.IntakeError, match="3 MiB"):
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
MAX_FILE_BYTES = 3 * 1024 * 1024
MAX_TOTAL_BYTES = 3 * 1024 * 1024
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
            raise IntakeError(f"{name} is larger than 3 MiB.")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise IntakeError("Attachments are limited to 3 MiB in total.")
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
    <label>Attachments (up to 4 · .txt .pdf .docx .xlsx · 3 MiB each)<input type="file" multiple accept=".txt,.pdf,.docx,.xlsx" onChange={e => setFiles(Array.from(e.target.files ?? []).slice(0, 4))}/></label>
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
# Process liveness only: no promise that instances remain warm; never wake Neon.
# One alert policy emails ALERT_EMAIL when either check keeps failing.
#   PROJECT_ID=... REGION=... ALERT_EMAIL=... bash scripts/gcp/monitoring.sh
set -euo pipefail
cd "$(dirname "$0")"
: "${ALERT_EMAIL:?set ALERT_EMAIL}"
: "${WEB_HOST:?set WEB_HOST to the deployed Vercel production hostname}"
: "${API_HOST:?set API_HOST from the deployed Cloud Run API status URL}"
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

WEB_CHECK="$(ensure_uptime sdoc-web "$WEB_HOST" /healthz)"
API_CHECK="$(ensure_uptime sdoc-api-livez "$API_HOST" /livez)"
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

### Task 18b: Billing disconnect guard — execute before Task 14

See [2026-09-20-vercel-cost-control-amendment.md](2026-09-20-vercel-cost-control-amendment.md).

This task has moved earlier. Implementation is in `scripts/gcp/killswitch/` and `scripts/gcp/deploy-cost-guard.ps1`; tests are `api/tests/test_killswitch.py`.

Follow the amendment's dry-run → event-delivery proof → arm procedure. The user selected **RM40 per month in MYR**, plus **Vercel Hobby**, on 2026-09-20. Budget reporting is delayed, and disconnecting billing can stop or delete project resources. It cannot guarantee an exact dollar cap or stop Vercel, Neon or OpenRouter billing. Never publish a synthetic over-threshold event after arming.

The old $10 hard-stop claim, unvalidated payload handler, automatic relink, and invalid budget CLI flag are withdrawn. Run unit tests and lint; independently verify cloud IAM, locked-association status, retry policy and delivery before claiming protection is active.

---

### Task 19: Deploy only after all CI gates pass

See [2026-09-20-vercel-cost-control-amendment.md](2026-09-20-vercel-cost-control-amendment.md).


- [ ] Require API lint/tests, guard tests, web TypeScript/build/proxy checks and container smoke.
- [ ] Deploy GCP services/jobs through repository/ref-restricted WIF with concurrency control and billing-enabled preflight.
- [ ] Deploy/promote Vercel only after successful checks. Git integration requires an explicit check gate; otherwise deploy from the gated workflow using a scoped Vercel credential.
- [ ] Never give a deployment job billing relink rights or make it reset/rearm the cost guard.
- [ ] Record revision/URL and smoke-test; document rollback separately for GCP and Vercel.

---

### Task 20: Runbook and live acceptance

See [2026-09-20-vercel-cost-control-amendment.md](2026-09-20-vercel-cost-control-amendment.md).


- [ ] Write `docs/deploy.md` and update README from the Vercel/GCP amendment, including prerequisites, secret setup, deployment, reset, rollback and teardown.
- [ ] Explain actual cost meters and external-provider limits; remove the under-$1 promise and any guaranteed $5 ceiling.
- [ ] Verify public reads, locked/unlocked writes, full worker completion, explicit score lifecycle, edited sample mismatch, upload-size errors, image-only review, retry and reset on the live URL.
- [ ] Record budget amount/currency/month, exact project filter, function dry-run=false, topic/trigger/IAM and error alert. Document manual recovery and no automatic billing relink.
- [ ] Keep proof of deployment and a backup demo recording for cold starts/outages. These are acceptance tasks, not evidence already collected.

---

### Task 21: Publish the branch (gated)

- [ ] **Step 1: Final verification**

Run: `T`, `L`, `W`, `bash scripts/gcp/selftest.sh`, `git status --short`
Expected: all implemented tests pass (record actual count), lint/build/proxy checks pass, and pending changes are reviewed. Verify both Vercel and GCP live acceptance plus the billing guard separately. `git ls-files | grep -c ground_truth` prints `0`.

- [ ] **Step 2: Ask the user before pushing**

Ask: "Push `feat/cloud-deploy` and open a PR against `main`?" Proceed only on an explicit yes. If PRs #1 and #2 are not merged yet, offer to target `feat/reliability-and-ci` instead.

- [ ] **Step 3: Push and open the PR (after approval)**

```bash
git push -u origin feat/cloud-deploy
gh pr create -R applejuice8/secret-hack --base main --head feat/cloud-deploy \
  --title "Vercel web, Cloud Run backend, reviewer access and cost controls" \
  --body "$(cat <<'EOF'
Implements docs/superpowers/specs/2026-09-20-cloud-deploy-design.md.

- Vercel web; Cloud Run API, IAM-private scorer and worker; scale to zero with a selected MYR billing-disconnect threshold (reporting can lag)
- Reviewer passcode on every write (reads stay open for judges)
- Fixes the build-time /api rewrite that broke browser actions under compose (runtime proxy route)
- Answer key removed from the repo (still in git history: team decision whether to rewrite it)
- Live intake with a sample kit, visible FAILED results and Retry/Reprocess
- Structured logs, uptime checks + alert, deploy on merge via Workload Identity Federation

Heads-up for web owners: next.config.ts rewrites() is replaced by app/api/[...path]/route.ts.

Include only the implementation and validation actually completed; do not claim future acceptance tasks are done.
EOF
)"
```
