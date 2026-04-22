# Windows + Playwright needs the Proactor event loop (default on 3.8+, but
# uvicorn's --reload subprocess can regress to SelectorEventLoop, which
# breaks asyncio.create_subprocess_exec → "NotImplementedError" when
# Playwright launches Chromium. Pin the policy before anything else runs.
import asyncio
import json
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import settings
from app.models import ScanListItem, ScanRequest, ScanResponse
from app.progress import ProgressReporter
from app.scanner import run_scan
from app.storage import delete_scan, get_scan, init_db, list_scans, save_scan


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


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


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": app.version}


# ---------------------------------------------------------------------------
# One-shot scan (batch). Used by curl / scripts / the non-streaming fallback.
# ---------------------------------------------------------------------------

@app.post("/scan", response_model=ScanResponse)
async def scan(req: ScanRequest) -> ScanResponse:
    try:
        result = await run_scan(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"scan failed: {e}") from e
    scan_id, created_at = await save_scan(result)
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
async def scan_stream(req: ScanRequest):
    reporter = ProgressReporter()

    async def runner() -> None:
        try:
            result = await run_scan(req, progress=reporter)
            scan_id, created_at = await save_scan(result)
            result.id = scan_id
            result.created_at = created_at
            reporter.emit("done", "Scan complete", {"scan_id": scan_id})
            # Stash the final result on the reporter for the generator to pick up.
            reporter._final_result = result.model_dump_json()  # type: ignore[attr-defined]
        except Exception as e:
            reporter._final_error = str(e)  # type: ignore[attr-defined]
            reporter.emit("error", f"Scan failed: {e}", {"error": str(e)})
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
# History
# ---------------------------------------------------------------------------

@app.get("/scans", response_model=list[ScanListItem])
async def list_history(limit: int = 50) -> list[ScanListItem]:
    return await list_scans(limit=limit)


@app.get("/scans/{scan_id}", response_model=ScanResponse)
async def get_one(scan_id: str) -> ScanResponse:
    scan = await get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return scan


@app.delete("/scans/{scan_id}")
async def delete_one(scan_id: str) -> dict:
    deleted = await delete_scan(scan_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="scan not found")
    return {"deleted": scan_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
