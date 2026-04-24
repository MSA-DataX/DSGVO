import { NextRequest, NextResponse } from "next/server";
import { authHeaderFromCookie, backendUrl } from "@/lib/serverAuth";

export const runtime = "nodejs";

async function proxy(method: "GET" | "DELETE", id: string) {
  const upstream = await fetch(`${backendUrl()}/scans/${encodeURIComponent(id)}`, {
    method,
    headers: { ...authHeaderFromCookie() },
  });
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}

export async function GET(_req: NextRequest, { params }: { params: { id: string } }) {
  return proxy("GET", params.id);
}

export async function DELETE(_req: NextRequest, { params }: { params: { id: string } }) {
  return proxy("DELETE", params.id);
}
