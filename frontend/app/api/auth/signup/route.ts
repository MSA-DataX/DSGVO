import { NextRequest, NextResponse } from "next/server";
import { backendUrl, setAuthCookie } from "@/lib/serverAuth";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const body = await req.text();
  const upstream = await fetch(`${backendUrl()}/auth/signup`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
  });
  const text = await upstream.text();

  // On success the backend returns { access_token, token_type, user }.
  // Strip the token out of the response body — the client only gets the
  // user object; the token stays in an httpOnly cookie.
  if (upstream.ok) {
    try {
      const parsed = JSON.parse(text) as { access_token: string; user: unknown };
      const res = NextResponse.json({ user: parsed.user }, { status: upstream.status });
      return setAuthCookie(res, parsed.access_token);
    } catch {
      // If the backend response is malformed, surface the raw text so the
      // developer can diagnose.
      return new NextResponse(text, { status: 502 });
    }
  }

  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
