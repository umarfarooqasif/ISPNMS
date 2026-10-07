/**
 * The web app's "backend for the browser".
 *
 * The browser never sees an API token. Tokens live only in httpOnly, SameSite=Strict cookies and
 * every API call goes through the proxy below, which attaches the token on the server. A script
 * injected into a page therefore cannot read or steal a login.
 *
 * Pure logic, no framework imports, so it can be tested without a browser or a server.
 */

export const API_PREFIX = "/api/v1";
export const AT_COOKIE = "isp_at"; // short-lived access token
export const RT_COOKIE = "isp_rt"; // refresh token
export const CSRF_HEADER = "x-requested-with";
export const CSRF_VALUE = "isp-web";
export const RT_MAX_AGE_SECONDS = 60 * 60 * 24 * 7;

export interface Tokens {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

type FetchFn = (input: string, init?: RequestInit) => Promise<Response>;

export interface Deps {
  fetchFn: FetchFn;
  apiUrl: string;
  refresher: TokenRefresher;
}

// ------------------------------------------------------------------ request safety

/** Only plain path segments may be forwarded: no traversal, no encoded slashes or dots. */
export function isSafePath(segments: string[]): boolean {
  if (segments.length === 0) return false;
  return segments.every(
    (s) => s.length > 0 && s !== "." && s !== ".." && !/[\\/?#%\u0000-\u001f]/.test(s),
  );
}

export function upstreamUrl(apiUrl: string, segments: string[], search: string): string {
  const base = apiUrl.replace(/\/+$/, "");
  const query = search && !search.startsWith("?") ? `?${search}` : search;
  return `${base}${API_PREFIX}/${segments.map(encodeURIComponent).join("/")}${query}`;
}

/**
 * Anything that changes data must carry a custom header. A page on another website cannot add it
 * without the browser asking this site's permission first, which closes cross-site request forgery.
 * (The cookies are also SameSite=Strict, so this is a second lock.)
 */
export function csrfOk(method: string, headerValue: string | null | undefined): boolean {
  const m = method.toUpperCase();
  if (m === "GET" || m === "HEAD" || m === "OPTIONS") return true;
  return headerValue === CSRF_VALUE;
}

export function isSecureRequest(forwardedProto: string | null | undefined, url: string): boolean {
  const first = (forwardedProto ?? "").split(",")[0]?.trim().toLowerCase();
  return first === "https" || (!first && url.toLowerCase().startsWith("https:"));
}

export function cookieOptions(secure: boolean, maxAge: number) {
  return { httpOnly: true, secure, sameSite: "strict" as const, path: "/", maxAge };
}

// ------------------------------------------------------------------ token refresh

/**
 * Refresh tokens rotate: using one invalidates it. When a page fires several requests at once and
 * the access token has just expired, they would all try to refresh with the same token and all but
 * the first would fail, logging the user out. This makes concurrent callers share ONE refresh, and
 * lets stragglers arriving a moment later reuse the result.
 */
export class TokenRefresher {
  private inflight = new Map<string, Promise<Tokens | null>>();
  private recent = new Map<string, { at: number; tokens: Tokens | null }>();

  constructor(
    private fetchFn: FetchFn,
    private apiUrl: string,
    private now: () => number = Date.now,
    private reuseMs = 15_000,
  ) {}

  async refresh(refreshToken: string): Promise<Tokens | null> {
    const cached = this.recent.get(refreshToken);
    if (cached && this.now() - cached.at < this.reuseMs) return cached.tokens;

    let pending = this.inflight.get(refreshToken);
    if (!pending) {
      pending = this.call(refreshToken)
        .then((tokens) => {
          this.recent.set(refreshToken, { at: this.now(), tokens });
          this.prune();
          return tokens;
        })
        .finally(() => this.inflight.delete(refreshToken));
      this.inflight.set(refreshToken, pending);
    }
    return pending;
  }

  /** null = the server says this refresh token is no good. Throws on network/server trouble, which
   *  is deliberately NOT remembered as "invalid" (the user must not be logged out by a blip). */
  private async call(refreshToken: string): Promise<Tokens | null> {
    const res = await this.fetchFn(`${this.apiUrl.replace(/\/+$/, "")}${API_PREFIX}/auth/refresh`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    });
    if (res.status === 401 || res.status === 403 || res.status === 422) return null;
    if (!res.ok) throw new Error(`refresh failed with status ${res.status}`);
    return (await res.json()) as Tokens;
  }

  private prune(): void {
    const cutoff = this.now() - this.reuseMs;
    for (const [key, value] of this.recent) {
      if (value.at < cutoff) this.recent.delete(key);
    }
  }
}

// ------------------------------------------------------------------ the proxy

export interface ProxyInput {
  method: string;
  segments: string[];
  search: string;
  contentType?: string | null;
  accept?: string | null;
  csrf?: string | null;
  body: ArrayBuffer | null;
  accessToken?: string;
  refreshToken?: string;
}

export interface ProxyOutput {
  status: number;
  contentType: string | null;
  body: ArrayBuffer | null;
  setTokens?: Tokens; // new tokens to store in cookies
  clearSession?: boolean; // the login is over: delete the cookies
}

const jsonBody = (detail: string): ArrayBuffer => {
  const bytes = new TextEncoder().encode(JSON.stringify({ detail }));
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
};

const fail = (status: number, detail: string, clearSession = false): ProxyOutput => ({
  status,
  contentType: "application/json",
  body: jsonBody(detail),
  clearSession,
});

export async function proxy(deps: Deps, input: ProxyInput): Promise<ProxyOutput> {
  if (!isSafePath(input.segments)) return fail(400, "Bad request path");
  if (!csrfOk(input.method, input.csrf)) return fail(403, "Missing or wrong request header");
  if (!input.accessToken && !input.refreshToken) return fail(401, "Not logged in", true);

  const url = upstreamUrl(deps.apiUrl, input.segments, input.search);
  const send = async (token: string): Promise<Response> => {
    const headers: Record<string, string> = { authorization: `Bearer ${token}` };
    if (input.contentType) headers["content-type"] = input.contentType;
    if (input.accept) headers["accept"] = input.accept;
    return deps.fetchFn(url, {
      method: input.method,
      headers,
      body: input.body ?? undefined,
      cache: "no-store",
      redirect: "manual",
    });
  };

  let accessToken = input.accessToken;
  let setTokens: Tokens | undefined;

  try {
    if (!accessToken) {
      // The access cookie expired: get a fresh one before calling.
      const fresh = input.refreshToken ? await deps.refresher.refresh(input.refreshToken) : null;
      if (!fresh) return fail(401, "Session expired", true);
      accessToken = fresh.access_token;
      setTokens = fresh;
    }

    let res = await send(accessToken);
    if (res.status === 401 && input.refreshToken && !setTokens) {
      const fresh = await deps.refresher.refresh(input.refreshToken);
      if (!fresh) return fail(401, "Session expired", true);
      setTokens = fresh;
      res = await send(fresh.access_token);
    }
    if (res.status === 401) return { ...fail(401, "Session expired", true), setTokens: undefined };

    const noBody = res.status === 204 || res.status === 205 || res.status === 304;
    return {
      status: res.status,
      contentType: res.headers.get("content-type"),
      body: noBody ? null : await res.arrayBuffer(),
      setTokens,
    };
  } catch {
    return fail(502, "The billing server is not reachable. Try again in a moment.");
  }
}

// ------------------------------------------------------------------ login / logout

export type LoginResult =
  | { ok: true; tokens: Tokens }
  | { ok: false; status: number; detail: string };

export async function loginUpstream(deps: Deps, username: string, password: string): Promise<LoginResult> {
  try {
    const res = await deps.fetchFn(`${deps.apiUrl.replace(/\/+$/, "")}${API_PREFIX}/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username, password }),
      cache: "no-store",
    });
    if (res.ok) return { ok: true, tokens: (await res.json()) as Tokens };
    let detail = "Login failed";
    try {
      const j = (await res.json()) as { detail?: unknown };
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* keep the generic message */
    }
    return { ok: false, status: res.status, detail };
  } catch {
    return { ok: false, status: 502, detail: "The billing server is not reachable. Try again in a moment." };
  }
}

/** Best effort: the cookies are cleared either way. */
export async function logoutUpstream(deps: Deps, refreshToken: string): Promise<void> {
  try {
    await deps.fetchFn(`${deps.apiUrl.replace(/\/+$/, "")}${API_PREFIX}/auth/logout`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    });
  } catch {
    /* the server will expire the token on its own */
  }
}
