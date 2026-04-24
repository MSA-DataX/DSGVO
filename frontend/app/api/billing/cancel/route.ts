import { NextResponse } from "next/server";
import { authHeaderFromCookie, backendUrl } from "@/lib/serverAuth";

export const runtime = "nodejs";

export async function POST() {
  const upstream = await fetch(`${backendUrl()}/billing/cancel`, {
    method: "POST",
    headers: { ...authHeaderFromCookie() },
  });
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
