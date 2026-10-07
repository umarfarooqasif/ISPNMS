import { NextRequest, NextResponse } from "next/server";

import { AT_COOKIE, RT_COOKIE } from "./lib/bff-core";

/** Sends visitors without a login cookie to the login page. (The API still checks every request.) */
export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const hasSession = req.cookies.has(AT_COOKIE) || req.cookies.has(RT_COOKIE);

  if (pathname === "/login") {
    return hasSession ? NextResponse.redirect(new URL("/", req.url)) : NextResponse.next();
  }
  if (!hasSession) return NextResponse.redirect(new URL("/login", req.url));
  return NextResponse.next();
}

export const config = {
  // Everything except static files and the two API-like routes (they answer 401 themselves).
  matcher: ["/((?!_next/|favicon.ico|auth/|bff/).*)"],
};
