import { AT_COOKIE, RT_COOKIE, RT_MAX_AGE_SECONDS, cookieOptions, type Tokens } from "./bff-core";

interface CookieJar {
  set(name: string, value: string, options: ReturnType<typeof cookieOptions>): unknown;
}

export function storeTokens(res: { cookies: CookieJar }, tokens: Tokens, secure: boolean): void {
  // The access cookie lives exactly as long as the token; the refresh cookie for a week.
  res.cookies.set(AT_COOKIE, tokens.access_token, cookieOptions(secure, Math.max(tokens.expires_in - 10, 30)));
  res.cookies.set(RT_COOKIE, tokens.refresh_token, cookieOptions(secure, RT_MAX_AGE_SECONDS));
}

export function clearTokens(res: { cookies: CookieJar }, secure: boolean): void {
  res.cookies.set(AT_COOKIE, "", cookieOptions(secure, 0));
  res.cookies.set(RT_COOKIE, "", cookieOptions(secure, 0));
}
