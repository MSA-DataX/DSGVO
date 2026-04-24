import { NextResponse } from "next/server";
import { clearAuthCookie } from "@/lib/serverAuth";

export const runtime = "nodejs";

export async function POST() {
  // Stateless JWT — nothing to invalidate server-side. Clearing the
  // cookie is enough to log the browser out; the token keeps working
  // until it expires if someone already has it, but it's no longer in
  // the cookie jar so nothing will send it.
  return clearAuthCookie(NextResponse.json({ ok: true }));
}
