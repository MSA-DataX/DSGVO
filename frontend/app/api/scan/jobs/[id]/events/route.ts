import { NextRequest, NextResponse } from "next/server";
import { authHeaderFromCookie, backendUrl } from "@/lib/serverAuth";

// Same-origin SSE proxy for Phase 3b live progress events. Identical
// streaming rules as /api/scan/stream:
//   - stream upstream body straight through (never buffer)
//   - disable proxy / CDN buffering via Cache-Control + X-Accel-Buffering

export const runtime = "nodejs";
export const maxDuration = 300; // scans can push 60-90s; leave headroom

export async function GET(
  _req: NextRequest,
  { params }: { params: { id: string } },
) {
  const upstream = await fetch(
    `${backendUrl()}/scan/jobs/${encodeURIComponent(params.id)}/events`,
    {
      headers: {
        accept: "text/event-stream",
        ...authHeaderFromCookie(),
      },
    },
  );

  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => "");
    return new NextResponse(text || upstream.statusText, { status: upstream.status });
  }

  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}
