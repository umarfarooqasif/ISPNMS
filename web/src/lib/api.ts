/** Browser-side helper. Every call goes to this site's own /bff proxy; no token is ever visible here. */

import { CSRF_HEADER, CSRF_VALUE } from "./bff-core";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

/** Turns whatever the API sent back into one readable sentence. */
export function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string" && d.trim()) return d;
    if (Array.isArray(d)) {
      const parts = d
        .map((e) => {
          if (e && typeof e === "object" && "msg" in e) {
            const loc = Array.isArray((e as { loc?: unknown[] }).loc)
              ? ((e as { loc: unknown[] }).loc.filter((p) => p !== "body" && p !== "query").join(" "))
              : "";
            const msg = String((e as { msg: unknown }).msg);
            return loc ? `${loc}: ${msg}` : msg;
          }
          return "";
        })
        .filter(Boolean);
      if (parts.length) return parts.join("; ");
    }
  }
  return fallback;
}

export interface ApiOptions {
  method?: string;
  json?: unknown;
  form?: FormData;
  signal?: AbortSignal;
}

export async function api<T>(path: string, opts: ApiOptions = {}): Promise<T> {
  const headers: Record<string, string> = { [CSRF_HEADER]: CSRF_VALUE, accept: "application/json" };
  let body: BodyInit | undefined;
  if (opts.json !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(opts.json);
  } else if (opts.form) {
    body = opts.form; // the browser sets the multipart boundary itself
  }
  const method = opts.method ?? (body !== undefined ? "POST" : "GET");

  let res: Response;
  try {
    res = await fetch(`/bff${path}`, { method, headers, body, signal: opts.signal, cache: "no-store" });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "Could not reach the server. Check your internet connection.");
  }

  if (res.status === 401) {
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
    throw new ApiError(401, "Your session has ended. Please log in again.");
  }

  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  if (!res.ok) {
    const fallback =
      res.status === 403 ? "You do not have permission to do that." : `Something went wrong (error ${res.status}).`;
    throw new ApiError(res.status, detailOf(parsed, fallback));
  }
  return parsed as T;
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}
