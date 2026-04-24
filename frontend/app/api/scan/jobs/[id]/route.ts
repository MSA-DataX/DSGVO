import { NextRequest, NextResponse } from "next/server";
import { authHeaderFromCookie, backendUrl } from "@/lib/serverAuth";

// GET /scan/jobs/{id} — job status + full result once status=="done".

export const runtime = "nodejs";

export async function GET(
  _req: NextRequest,
  { params }: { params: { id: string } },
) {
  const upstream = await fetch(
    `${backendUrl()}/scan/jobs/${encodeURIComponent(params.id)}`,
    { headers: { ...authHeaderFromCookie() } },
  );
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
