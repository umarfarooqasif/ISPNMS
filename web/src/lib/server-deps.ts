import { TokenRefresher, type Deps } from "./bff-core";

/** One shared instance per server process, so concurrent requests share a single token refresh. */
const g = globalThis as unknown as { __ispDeps?: Deps };

export function getDeps(): Deps {
  if (!g.__ispDeps) {
    const apiUrl = process.env.API_URL ?? "http://api:8000";
    const fetchFn = (input: string, init?: RequestInit) => fetch(input, init);
    g.__ispDeps = { fetchFn, apiUrl, refresher: new TokenRefresher(fetchFn, apiUrl) };
  }
  return g.__ispDeps;
}
