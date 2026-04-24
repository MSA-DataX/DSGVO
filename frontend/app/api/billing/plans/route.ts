import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/serverAuth";

// Public — the plan catalogue is also needed on marketing / pricing
// pages where there is no session yet. No cookie forwarding.

export const runtime = "nodejs";

export async function GET() {
  const upstream = await fetch(`${backendUrl()}/billing/plans`);
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
