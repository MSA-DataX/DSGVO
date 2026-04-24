import type {
  ProgressEvent,
  ScanJobCreated,
  ScanJobStatusResponse,
  ScanListItem,
  ScanRequest,
  ScanResponse,
} from "./types";

// Same-origin proxy. See comments in app/api/scan/route.ts.
export async function runScan(req: ScanRequest): Promise<ScanResponse> {
  const res = await fetch("/api/scan", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Scan failed (${res.status}): ${text || res.statusText}`);
  }
  return (await res.json()) as ScanResponse;
}

// ---------------------------------------------------------------------------
// Streaming
// ---------------------------------------------------------------------------

export interface StreamHandlers {
  onProgress: (ev: ProgressEvent) => void;
  onResult: (result: ScanResponse) => void;
  onError: (err: string) => void;
}

/**
 * POSTs to /api/scan/stream and parses the returned SSE stream into
 * progress / result / error callbacks. Uses fetch+ReadableStream because
 * the native `EventSource` is GET-only and we want the scan parameters
 * in the request body.
 */
export async function streamScan(
  req: ScanRequest,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/scan/stream", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream" },
    body: JSON.stringify(req),
    signal,
  });

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    handlers.onError(`Stream failed (${res.status}): ${text || res.statusText}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line (\n\n).
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      dispatchFrame(frame, handlers);
    }
  }
  // Flush any trailing partial frame (rare; servers should always end with \n\n).
  if (buffer.trim()) dispatchFrame(buffer, handlers);
}

function dispatchFrame(frame: string, h: StreamHandlers) {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return;
  const raw = dataLines.join("\n");
  try {
    const payload = JSON.parse(raw);
    if (event === "progress") h.onProgress(payload as ProgressEvent);
    else if (event === "result") h.onResult(payload as ScanResponse);
    else if (event === "error") h.onError(String(payload?.error ?? "unknown error"));
  } catch {
    // ignore malformed frames; keep streaming
  }
}

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------

export async function listScans(limit = 50): Promise<ScanListItem[]> {
  const res = await fetch(`/api/scans?limit=${limit}`);
  if (!res.ok) throw new Error(`listScans failed: ${res.status}`);
  return (await res.json()) as ScanListItem[];
}

export async function getScan(id: string): Promise<ScanResponse> {
  const res = await fetch(`/api/scans/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`getScan failed: ${res.status}`);
  return (await res.json()) as ScanResponse;
}

export async function deleteScan(id: string): Promise<void> {
  const res = await fetch(`/api/scans/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`deleteScan failed: ${res.status}`);
}

// ---------------------------------------------------------------------------
// Async scan mode (Phase 3c — opt-in via NEXT_PUBLIC_SCAN_MODE=async)
// ---------------------------------------------------------------------------
//
// The same-handler UX from streamScan(), rebuilt against the Arq-backed
// endpoints. Orchestration:
//   1. POST /api/scan/jobs      → {id, status: "queued"}
//   2. GET  /api/scan/jobs/{id}/events  → SSE stream of stage events
//   3. On terminal stage ("done" / "error"):
//        - done  → GET /api/scan/jobs/{id} for the full ScanResponse,
//                  hand it to handlers.onResult
//        - error → hand the message to handlers.onError
//
// This keeps the page-level call site identical to the sync path — the
// feature flag below picks the implementation.

export async function enqueueScan(req: ScanRequest): Promise<ScanJobCreated> {
  const res = await fetch("/api/scan/jobs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Enqueue failed (${res.status}): ${text || res.statusText}`);
  }
  return (await res.json()) as ScanJobCreated;
}

export async function getScanJob(id: string): Promise<ScanJobStatusResponse> {
  const res = await fetch(`/api/scan/jobs/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`getScanJob failed: ${res.status}`);
  return (await res.json()) as ScanJobStatusResponse;
}

export async function streamScanAsync(
  req: ScanRequest,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let job: ScanJobCreated;
  try {
    job = await enqueueScan(req);
  } catch (err) {
    handlers.onError(err instanceof Error ? err.message : String(err));
    return;
  }

  // Emit an initial progress frame so the UI shows feedback immediately
  // instead of sitting on whatever it had before the enqueue.
  handlers.onProgress({
    stage: "started",
    message: "Scan queued",
    data: { scan_id: job.id },
    ts: Date.now() / 1000,
  });

  const eventsRes = await fetch(
    `/api/scan/jobs/${encodeURIComponent(job.id)}/events`,
    { headers: { accept: "text/event-stream" }, signal },
  );
  if (!eventsRes.ok || !eventsRes.body) {
    const text = await eventsRes.text().catch(() => "");
    handlers.onError(`Stream failed (${eventsRes.status}): ${text || eventsRes.statusText}`);
    return;
  }

  const reader = eventsRes.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminalStage: string | null = null;

  const captureStage = (frame: string) => {
    for (const line of frame.split("\n")) {
      if (line.startsWith("data:")) {
        try {
          const payload = JSON.parse(line.slice(5).trim());
          if (payload?.stage === "done" || payload?.stage === "error") {
            terminalStage = payload.stage;
          }
        } catch {
          // ignore
        }
      }
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      captureStage(frame);
      dispatchFrame(frame, handlers);
    }
  }
  if (buffer.trim()) {
    captureStage(buffer);
    dispatchFrame(buffer, handlers);
  }

  // The backend only closes the event stream after emitting a terminal
  // stage, so missing it here means upstream truncated — surface as error.
  if (terminalStage === "done") {
    try {
      const status = await getScanJob(job.id);
      if (status.result) {
        handlers.onResult(status.result);
      } else {
        handlers.onError("Scan completed but no result payload was persisted");
      }
    } catch (err) {
      handlers.onError(err instanceof Error ? err.message : String(err));
    }
  } else if (terminalStage === "error") {
    try {
      const status = await getScanJob(job.id);
      handlers.onError(status.error || "Scan failed");
    } catch {
      handlers.onError("Scan failed");
    }
  } else {
    handlers.onError("Event stream ended before a terminal event arrived");
  }
}

/**
 * Dispatches to streamScan (inline SSE, Phase 1-2) or streamScanAsync
 * (Arq-backed, Phase 3/3b) based on the `NEXT_PUBLIC_SCAN_MODE` build-
 * time env var. Callers use this instead of the two specific functions
 * so the UI doesn't care which mode is active.
 *
 * Default: "sync". Set NEXT_PUBLIC_SCAN_MODE=async to opt into the
 * async path — requires the backend to have REDIS_URL set and an
 * `arq app.worker.WorkerSettings` worker running.
 */
export function streamScanAuto(
  req: ScanRequest,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const mode = process.env.NEXT_PUBLIC_SCAN_MODE;
  if (mode === "async") return streamScanAsync(req, handlers, signal);
  return streamScan(req, handlers, signal);
}
