import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const backend = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
  const limit = req.nextUrl.searchParams.get("limit") ?? "50";
  const upstream = await fetch(`${backend}/scans?limit=${encodeURIComponent(limit)}`);
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
