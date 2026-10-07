import { NextRequest, NextResponse } from "next/server";

import { AT_COOKIE, CSRF_HEADER, RT_COOKIE, isSecureRequest, proxy } from "@/lib/bff-core";
import { clearTokens, storeTokens } from "@/lib/cookies";
import { getDeps } from "@/lib/server-deps";

export const dynamic = "force-dynamic";

async function handle(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  const out = await proxy(getDeps(), {
    method: req.method,
    segments: path,
    search: req.nextUrl.search,
    contentType: req.headers.get("content-type"),
    accept: req.headers.get("accept"),
    csrf: req.headers.get(CSRF_HEADER),
    body: hasBody ? await req.arrayBuffer() : null,
    accessToken: req.cookies.get(AT_COOKIE)?.value,
    refreshToken: req.cookies.get(RT_COOKIE)?.value,
  });

  const headers: Record<string, string> = { "cache-control": "no-store" };
  if (out.contentType) headers["content-type"] = out.contentType;
  const res = new NextResponse(out.body, { status: out.status, headers });

  const secure = isSecureRequest(req.headers.get("x-forwarded-proto"), req.nextUrl.href);
  if (out.setTokens) storeTokens(res, out.setTokens, secure);
  if (out.clearSession) clearTokens(res, secure);
  return res;
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
