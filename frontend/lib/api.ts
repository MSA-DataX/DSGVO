import type {
  ProgressEvent,
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
