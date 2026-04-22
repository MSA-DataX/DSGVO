import { NextRequest, NextResponse } from "next/server";

// Same-origin proxy to the FastAPI backend. Avoids CORS in the browser and
// lets us swap the backend URL via NEXT_PUBLIC_BACKEND_URL without touching
// client code. Long timeout because a real scan takes 20-60s.

export const runtime = "nodejs";
export const maxDuration = 120; // seconds; keep aligned with hosting limits

export async function POST(req: NextRequest) {
  const backend = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
  const body = await req.text();

  const upstream = await fetch(`${backend}/scan`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
    // No upstream timeout here — Next.js maxDuration above is the cap.
  });

  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
