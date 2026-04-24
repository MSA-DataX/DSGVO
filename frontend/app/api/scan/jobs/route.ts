import { NextRequest, NextResponse } from "next/server";
import { authHeaderFromCookie, backendUrl } from "@/lib/serverAuth";

// Same-origin proxy for the async enqueue endpoint (Phase 3).
// Returns 202 almost immediately; the actual scan runs on a separate
// Arq worker process. See /api/scan/jobs/[id]/events for live progress.

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const body = await req.text();

  const upstream = await fetch(`${backendUrl()}/scan/jobs`, {
    method: "POST",
    headers: { "content-type": "application/json", ...authHeaderFromCookie() },
    body,
  });

  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
