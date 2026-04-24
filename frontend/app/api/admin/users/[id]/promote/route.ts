import { NextRequest, NextResponse } from "next/server";
import { authHeaderFromCookie, backendUrl } from "@/lib/serverAuth";

export const runtime = "nodejs";

export async function POST(
  _req: NextRequest,
  { params }: { params: { id: string } },
) {
  const upstream = await fetch(
    `${backendUrl()}/admin/users/${encodeURIComponent(params.id)}/promote`,
    { method: "POST", headers: { ...authHeaderFromCookie() } },
  );
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
