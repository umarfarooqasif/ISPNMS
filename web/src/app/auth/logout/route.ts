import { NextRequest, NextResponse } from "next/server";

import { CSRF_HEADER, RT_COOKIE, csrfOk, isSecureRequest, logoutUpstream } from "@/lib/bff-core";
import { clearTokens } from "@/lib/cookies";
import { getDeps } from "@/lib/server-deps";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  if (!csrfOk("POST", req.headers.get(CSRF_HEADER))) {
    return NextResponse.json({ detail: "Missing or wrong request header" }, { status: 403 });
  }
  const refresh = req.cookies.get(RT_COOKIE)?.value;
  if (refresh) await logoutUpstream(getDeps(), refresh);
  const res = new NextResponse(null, { status: 204 });
  clearTokens(res, isSecureRequest(req.headers.get("x-forwarded-proto"), req.nextUrl.href));
  return res;
}
