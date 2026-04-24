import { NextRequest, NextResponse } from "next/server";
import { authHeaderFromCookie, backendUrl } from "@/lib/serverAuth";

export const runtime = "nodejs";

export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  const body = await req.text();
  const upstream = await fetch(
    `${backendUrl()}/admin/users/${encodeURIComponent(params.id)}/reset-password`,
    {
      method: "POST",
      headers: { "content-type": "application/json", ...authHeaderFromCookie() },
      body,
    },
  );
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
