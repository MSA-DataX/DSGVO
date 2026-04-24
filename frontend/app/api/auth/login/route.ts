import { NextRequest, NextResponse } from "next/server";
import { backendUrl, setAuthCookie } from "@/lib/serverAuth";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const body = await req.text();
  const upstream = await fetch(`${backendUrl()}/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
  });
  const text = await upstream.text();

  if (upstream.ok) {
    try {
      const parsed = JSON.parse(text) as { access_token: string; user: unknown };
      const res = NextResponse.json({ user: parsed.user }, { status: upstream.status });
      return setAuthCookie(res, parsed.access_token);
    } catch {
      return new NextResponse(text, { status: 502 });
    }
  }

  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
