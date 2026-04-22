import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

async function proxy(method: "GET" | "DELETE", id: string) {
  const backend = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
  const upstream = await fetch(`${backend}/scans/${encodeURIComponent(id)}`, { method });
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
