import { NextRequest, NextResponse } from "next/server";
import { authHeaderFromCookie, backendUrl } from "@/lib/serverAuth";

// Same-origin proxy for the SSE scan stream. Two things matter here:
//
//   1. We MUST NOT buffer. If we await res.text() first, all progress
//      events would arrive in one lump at the end. Instead we stream the
//      upstream body straight through to the browser.
//   2. Set Cache-Control + X-Accel-Buffering so nothing in the middle
//      (CDN, nginx, Vercel edge) tries to buffer either.

export const runtime = "nodejs";
export const maxDuration = 300; // scans with AI can push 60-90s; leave headroom

export async function POST(req: NextRequest) {
  const body = await req.text();

  const upstream = await fetch(`${backendUrl()}/scan/stream`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "text/event-stream",
      ...authHeaderFromCookie(),
    },
    body,
    // @ts-expect-error — Node fetch supports `duplex`, types lag behind.
    duplex: "half",
  });

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
