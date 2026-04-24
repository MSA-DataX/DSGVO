import { NextRequest, NextResponse } from "next/server";
import { authHeaderFromCookie, backendUrl } from "@/lib/serverAuth";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  // Forward limit + filter params one-for-one — the backend validates.
  const qs = req.nextUrl.searchParams.toString();
  const upstream = await fetch(
    `${backendUrl()}/admin/audit${qs ? `?${qs}` : ""}`,
    { headers: { ...authHeaderFromCookie() } },
  );
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
