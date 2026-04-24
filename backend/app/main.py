# Windows + Playwright needs the Proactor event loop (default on 3.8+, but
# uvicorn's --reload subprocess can regress to SelectorEventLoop, which
# breaks asyncio.create_subprocess_exec → "NotImplementedError" when
# Playwright launches Chromium. Pin the policy before anything else runs.
import asyncio
import json
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import text

from app.auth import AuthedUser, get_current_user
from app.billing.mollie import close_mollie_client
from app.billing.subscriptions import check_scan_quota
from app.config import settings
from app.db import session_scope
from app.jobs import close_pool, enqueue_scan, get_pool
from app.observability import metrics as obs_metrics
from app.observability.logging import configure_logging, set_request_id
from app.observability.sentry import init_sentry_if_configured
from app.progress_bus import subscribe_progress
from app.models import (
    ScanJobCreated,
    ScanJobStatusResponse,
    ScanListItem,
    ScanRequest,
    ScanResponse,
)
from app.progress import ProgressReporter
from app.routers import admin as admin_router
from app.routers import auth as auth_router
from app.routers import billing as billing_router
from app.routers import well_known as well_known_router
from app.scanner import run_scan
from app.security.rate_limit import scan_rate_limiter
from app.security.ssrf import SsrfError, validate_url_safe
from app.storage import (
    create_pending_scan,
    delete_scan,
    get_scan,
    get_scan_status,
    init_db,
    list_scans,
    save_scan,
)


# Observability bootstrap — runs at module-import, before the first
# request. Idempotent; safe to import this module twice (e.g. tests).
configure_logging(level=settings.log_level, fmt=settings.log_format)
init_sentry_if_configured()
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    try:
        yield
    finally:
        # Release external clients if any code path opened them. Both
        # helpers no-op when the respective client was never touched
        # (sync-mode / billing-disabled deploys).
        await close_pool()
        await close_mollie_client()


app = FastAPI(
    title="GDPR Scanner",
    version="0.2.0",
    description="Crawler + network/data-flow + cookie/storage + AI policy review + risk scoring.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # Frontend goes through its own /api/scan proxy, so in production this
    # endpoint should NOT be reachable cross-origin from a browser at all.
    # Keep "*" only for local development / curl testing. Set
    # ALLOWED_ORIGINS in .env (comma-separated) before deploying.
    allow_origins=settings.allowed_origins_list,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """One middleware doing two closely-related things so we don't pay
    double per-request overhead:

      1. Request-ID propagation: reuse an incoming ``X-Request-ID``
         header (set by a reverse proxy) or mint a fresh one, stash
         it on the ContextVar so every log line from this request
         carries the same id, and echo it back to the client.
      2. HTTP metrics: count + time the response. We normalise the
         path to the FastAPI route template so
         ``/scans/{scan_id}`` is one series, not N.
    """
    incoming = request.headers.get("x-request-id")
    rid = incoming if incoming and 8 <= len(incoming) <= 128 else uuid.uuid4().hex[:12]
    set_request_id(rid)

    started = time.perf_counter()
    status_code = 500  # default for unhandled exception case
    try:
        response = await call_next(request)
        status_code = response.status_code
    finally:
        elapsed = time.perf_counter() - started
        # Route template is only populated by FastAPI after routing ran.
        route = request.scope.get("route")
        template = getattr(route, "path", None)
        path_label = obs_metrics.normalise_path(request.url.path, template)
        # Don't observe /metrics itself — scraping would inflate its
        # own counters.
        if path_label != "/metrics":
            obs_metrics.http_request_duration_seconds.labels(
                request.method, path_label,
            ).observe(elapsed)
            obs_metrics.http_requests_total.labels(
                request.method, path_label, str(status_code),
            ).inc()

    response.headers["x-request-id"] = rid
    set_request_id(None)
    return response

app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(billing_router.router)
app.include_router(well_known_router.router)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    """Aggregate liveness + dependency probe.

    Returns ``status="ok"`` only when every optional dependency we
    need at runtime is reachable. Orchestrators (Kubernetes, Docker
    Compose, uptime-check services) consume the ``status`` field;
    the per-dep dictionary is for human ops debugging.

    Redis is ``"disabled"`` when REDIS_URL is unset — that's a valid
    deployment mode (sync scans only), not a failure.
    """
    deps: dict[str, str] = {}

    # --- Postgres / SQLite -----------------------------------------
    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
        deps["db"] = "ok"
    except Exception as e:
        log.warning("health: db probe failed: %s", e)
        deps["db"] = "fail"

    # --- Redis (optional) ------------------------------------------
    if not settings.redis_url:
        deps["redis"] = "disabled"
    else:
        try:
            pool = await get_pool()
            # arq.create_pool returns an ArqRedis subclass that exposes
            # .ping() from redis-py. Fake pools in tests won't, so
            # we soften the attribute check.
            ping = getattr(pool, "ping", None)
            if ping is not None:
                await ping()
            deps["redis"] = "ok"
        except Exception as e:
            log.warning("health: redis probe failed: %s", e)
            deps["redis"] = "fail"

    overall = "ok" if deps["db"] == "ok" and deps.get("redis") != "fail" else "degraded"
    return {
        "status":  overall,
        "version": settings.app_version,
        "deps":    deps,
    }


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    """Prometheus scrape target. Plain text, not JSON. Serve this
    behind the reverse proxy's IP allowlist in production — Caddy's
    `remote_ip` matcher is the usual pattern — so operators can
    collect without exposing counter values to the internet."""
    body, content_type = obs_metrics.render_metrics()
    return PlainTextResponse(body, media_type=content_type)


# ---------------------------------------------------------------------------
# One-shot scan (batch). Used by curl / scripts / the non-streaming fallback.
# ---------------------------------------------------------------------------

async def _scan_boundary_guards(req: ScanRequest, current: AuthedUser) -> None:
    """Shared pre-flight for /scan, /scan/stream, /scan/jobs: SSRF
    validator → rate limit → quota. Ticks the domain-metric counters
    on the relevant failure branches so dashboards see the signal
    without having to parse logs."""
    try:
        validate_url_safe(str(req.url))
    except SsrfError as e:
        obs_metrics.ssrf_blocks_total.inc()
        raise HTTPException(status_code=400, detail=str(e)) from e

    scan_rate_limiter.check(f"scan:{current.organization_id}")

    try:
        await check_scan_quota(current.organization_id)
    except HTTPException as e:
        if e.status_code == 402:
            # Extract the plan label from the structured detail payload
            # the check helper produces (see billing/subscriptions.py).
            plan_label = "unknown"
            if isinstance(e.detail, dict):
                plan_label = str(e.detail.get("plan") or "unknown")
            obs_metrics.quota_exceeded_total.labels(plan_label).inc()
        raise


@app.post("/scan", response_model=ScanResponse)
async def scan(
    req: ScanRequest,
    current: AuthedUser = Depends(get_current_user),
) -> ScanResponse:
    # Boundary checks BEFORE any network activity — refuse SSRF targets
    # and over-quota callers without touching Playwright.
    await _scan_boundary_guards(req, current)

    try:
        result = await run_scan(req)
    except Exception as e:
        obs_metrics.scans_total.labels("sync", "failed").inc()
        raise HTTPException(status_code=500, detail=f"scan failed: {e}") from e
    scan_id, created_at = await save_scan(result, organization_id=current.organization_id)
    obs_metrics.scans_total.labels("sync", "ok").inc()
    result.id = scan_id
    result.created_at = created_at
    return result


# ---------------------------------------------------------------------------
# Streaming scan (SSE). Each event is one of:
#   event: progress  data: {stage, message, data, ts}
#   event: result    data: <full ScanResponse JSON>
#   event: error     data: {error: "..."}
# The stream closes after `result` or `error`.
# ---------------------------------------------------------------------------

@app.post("/scan/stream")
async def scan_stream(
    req: ScanRequest,
    current: AuthedUser = Depends(get_current_user),
):
    # Same guards as the batch endpoint — rejected synchronously so the
    # SSE stream isn't even opened on a 400 / 429 / 402.
    await _scan_boundary_guards(req, current)

    reporter = ProgressReporter()
    org_id = current.organization_id

    async def runner() -> None:
        try:
            result = await run_scan(req, progress=reporter)
            scan_id, created_at = await save_scan(result, organization_id=org_id)
            result.id = scan_id
            result.created_at = created_at
            reporter.emit("done", "Scan complete", {"scan_id": scan_id})
            # Stash the final result on the reporter for the generator to pick up.
            reporter._final_result = result.model_dump_json()  # type: ignore[attr-defined]
            obs_metrics.scans_total.labels("sync", "ok").inc()
        except Exception as e:
            reporter._final_error = str(e)  # type: ignore[attr-defined]
            reporter.emit("error", f"Scan failed: {e}", {"error": str(e)})
            obs_metrics.scans_total.labels("sync", "failed").inc()
        finally:
            reporter.close()

    task = asyncio.create_task(runner())

    async def event_stream():
        try:
            async for ev in reporter:
                yield ev.to_sse()
            # Drain the background task so unhandled exceptions show up in logs.
            await task
            final_result = getattr(reporter, "_final_result", None)
            final_error = getattr(reporter, "_final_error", None)
            if final_result is not None:
                yield f"event: result\ndata: {final_result}\n\n"
            elif final_error is not None:
                yield f"event: error\ndata: {json.dumps({'error': final_error})}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable buffering on nginx if reverse-proxied
        },
    )


# ---------------------------------------------------------------------------
# Async scan jobs (Phase 3). The HTTP handler enqueues, returns
# immediately, and the Arq worker does the actual Playwright scan.
# ---------------------------------------------------------------------------

@app.post("/scan/jobs", response_model=ScanJobCreated, status_code=202)
async def enqueue_scan_job(
    req: ScanRequest,
    current: AuthedUser = Depends(get_current_user),
) -> ScanJobCreated:
    # Same boundary guards as sync /scan — SSRF first so a 400 is cheap
    # to iterate on, then the per-tenant rate limit.
    await _scan_boundary_guards(req, current)

    scan_id, created_at = await create_pending_scan(
        url=str(req.url), organization_id=current.organization_id,
    )
    try:
        await enqueue_scan(scan_id, req.model_dump(mode="json"))
    except RuntimeError as e:
        # REDIS_URL not set — surface a clear error rather than letting
        # the scan row sit in "queued" forever.
        raise HTTPException(status_code=503, detail=str(e)) from e
    obs_metrics.scans_total.labels("async", "ok").inc()
    return ScanJobCreated(
        id=scan_id, status="queued", url=str(req.url), created_at=created_at,
    )


@app.get("/scan/jobs/{scan_id}", response_model=ScanJobStatusResponse)
async def get_scan_job(
    scan_id: str,
    current: AuthedUser = Depends(get_current_user),
) -> ScanJobStatusResponse:
    status = await get_scan_status(scan_id, organization_id=current.organization_id)
    if status is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return ScanJobStatusResponse(
        id=status.id,
        status=status.status,  # type: ignore[arg-type]
        url=status.url,
        created_at=status.created_at,
        started_at=status.started_at,
        completed_at=status.completed_at,
        error=status.error,
        result=status.result,
    )


@app.get("/scan/jobs/{scan_id}/events")
async def stream_scan_events(
    scan_id: str,
    current: AuthedUser = Depends(get_current_user),
):
    """SSE stream of progress events for an async scan.

    Race-free subscribe: we open the pub/sub subscription FIRST, then
    re-check the DB status. If the scan had already finished before we
    subscribed the re-check catches it and we emit a terminal event
    directly. Otherwise we forward Redis messages until we see a
    ``done`` / ``error`` stage and close.
    """
    # Tenant scope + existence check up front so an unknown / cross-
    # tenant id gets the same plain 404 as every other scan endpoint.
    status = await get_scan_status(scan_id, organization_id=current.organization_id)
    if status is None:
        raise HTTPException(status_code=404, detail="scan not found")

    try:
        pool = await get_pool()
    except RuntimeError as e:
        # No REDIS_URL configured — async mode is off, events don't exist.
        raise HTTPException(status_code=503, detail=str(e)) from e

    async def event_stream():
        # Open subscription BEFORE the status re-check so we can't miss a
        # publish that fires in between.
        subscription = subscribe_progress(pool, scan_id)
        try:
            snapshot = await get_scan_status(
                scan_id, organization_id=current.organization_id,
            )
            if snapshot is not None and snapshot.status in ("done", "failed"):
                payload = json.dumps({
                    "stage": "done" if snapshot.status == "done" else "error",
                    "message": (
                        "Scan complete"
                        if snapshot.status == "done"
                        else (snapshot.error or "Scan failed")
                    ),
                    "data": {"scan_id": scan_id, "status": snapshot.status},
                })
                yield f"event: progress\ndata: {payload}\n\n"
                return

            async for ev in subscription:
                yield f"event: progress\ndata: {json.dumps(ev)}\n\n"
                if ev.get("stage") in ("done", "error"):
                    return
        finally:
            # subscribe_progress cleans up via its own finally when the
            # generator is closed; explicitly aclose to make that
            # immediate on client disconnect.
            await subscription.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@app.get("/scans", response_model=list[ScanListItem])
async def list_history(
    limit: int = 50,
    current: AuthedUser = Depends(get_current_user),
) -> list[ScanListItem]:
    return await list_scans(organization_id=current.organization_id, limit=limit)


@app.get("/scans/{scan_id}", response_model=ScanResponse)
async def get_one(
    scan_id: str,
    current: AuthedUser = Depends(get_current_user),
) -> ScanResponse:
    scan = await get_scan(scan_id, organization_id=current.organization_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return scan


@app.delete("/scans/{scan_id}")
async def delete_one(
    scan_id: str,
    current: AuthedUser = Depends(get_current_user),
) -> dict:
    deleted = await delete_scan(scan_id, organization_id=current.organization_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="scan not found")
    return {"deleted": scan_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
