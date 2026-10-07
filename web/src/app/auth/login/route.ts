import { NextRequest, NextResponse } from "next/server";

import { CSRF_HEADER, csrfOk, isSecureRequest, loginUpstream } from "@/lib/bff-core";
import { storeTokens } from "@/lib/cookies";
import { getDeps } from "@/lib/server-deps";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  if (!csrfOk("POST", req.headers.get(CSRF_HEADER))) {
    return NextResponse.json({ detail: "Missing or wrong request header" }, { status: 403 });
  }
  let body: { username?: unknown; password?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: "Send a username and password" }, { status: 400 });
  }
  if (typeof body.username !== "string" || typeof body.password !== "string" || !body.username.trim()) {
    return NextResponse.json({ detail: "Enter your username and password" }, { status: 400 });
  }

  const result = await loginUpstream(getDeps(), body.username.trim(), body.password);
  if (!result.ok) {
    return NextResponse.json({ detail: result.detail }, { status: result.status });
  }
  const res = NextResponse.json({ ok: true });
  storeTokens(res, result.tokens, isSecureRequest(req.headers.get("x-forwarded-proto"), req.nextUrl.href));
  return res;
}
