import { NextRequest, NextResponse } from "next/server";
import { authHeaderFromCookie, backendUrl } from "@/lib/serverAuth";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const limit = req.nextUrl.searchParams.get("limit") ?? "100";
  const upstream = await fetch(
    `${backendUrl()}/admin/users?limit=${encodeURIComponent(limit)}`,
    { headers: { ...authHeaderFromCookie() } },
  );
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
