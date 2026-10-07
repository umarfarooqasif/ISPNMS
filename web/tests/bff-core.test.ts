import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AT_COOKIE,
  CSRF_VALUE,
  TokenRefresher,
  cookieOptions,
  csrfOk,
  isSafePath,
  isSecureRequest,
  loginUpstream,
  proxy,
  upstreamUrl,
  type Deps,
  type ProxyInput,
  type Tokens,
} from "../src/lib/bff-core";

const API = "http://api:8000";
const NEW: Tokens = { access_token: "new-at", refresh_token: "new-rt", expires_in: 900 };

interface Call { url: string; method: string; auth?: string; body?: unknown; contentType?: string }

/** A fake server. `handler` decides each answer; every call is recorded. */
function fake(handler: (call: Call, n: number) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const fetchFn = async (url: string, init: RequestInit = {}) => {
    const headers = (init.headers ?? {}) as Record<string, string>;
    const call: Call = {
      url, method: init.method ?? "GET", auth: headers["authorization"],
      body: init.body, contentType: headers["content-type"],
    };
    calls.push(call);
    return handler(call, calls.length);
  };
  return { calls, fetchFn };
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function deps(handler: Parameters<typeof fake>[0], now?: () => number) {
  const f = fake(handler);
  const refresher = new TokenRefresher(f.fetchFn, API, now);
  const d: Deps = { fetchFn: f.fetchFn, apiUrl: API, refresher };
  return { d, calls: f.calls };
}

const base: ProxyInput = {
  method: "GET", segments: ["customers"], search: "?q=ali", body: null,
  accessToken: "old-at", refreshToken: "old-rt",
};

const text = (b: ArrayBuffer | null) => (b ? new TextDecoder().decode(b) : "");

describe("request safety", () => {
  it("accepts plain paths and rejects traversal or encoded tricks", () => {
    assert.ok(isSafePath(["customers"]));
    assert.ok(isSafePath(["customers", "3fa85f64-5717-4562-b3fc-2c963f66afa6", "statement"]));
    for (const bad of [[], [""], [".."], ["."], ["a", ".."], ["a/b"], ["a\\b"], ["%2e%2e"], ["a?b=1"], ["a#b"], ["a\u0000b"]]) {
      assert.equal(isSafePath(bad), false, JSON.stringify(bad));
    }
  });

  it("builds the upstream URL under /api/v1 and keeps the query", () => {
    assert.equal(upstreamUrl("http://api:8000/", ["customers"], "?q=ali&limit=5"),
      "http://api:8000/api/v1/customers?q=ali&limit=5");
    assert.equal(upstreamUrl(API, ["imports", "wasooli"], ""), "http://api:8000/api/v1/imports/wasooli");
    assert.equal(upstreamUrl(API, ["customers"], "q=x"), "http://api:8000/api/v1/customers?q=x");
  });

  it("only allows changes that carry the custom header", () => {
    for (const m of ["GET", "get", "HEAD", "OPTIONS"]) assert.ok(csrfOk(m, null), m);
    for (const m of ["POST", "PUT", "PATCH", "DELETE", "post"]) {
      assert.equal(csrfOk(m, null), false, m);
      assert.equal(csrfOk(m, "something-else"), false, m);
      assert.ok(csrfOk(m, CSRF_VALUE), m);
    }
  });

  it("detects https from the proxy header or the URL", () => {
    assert.ok(isSecureRequest("https", "http://x"));
    assert.ok(isSecureRequest("https, http", "http://x"));
    assert.equal(isSecureRequest("http", "https://x"), false);
    assert.ok(isSecureRequest(null, "https://x"));
    assert.equal(isSecureRequest(null, "http://x"), false);
  });

  it("builds locked-down cookies", () => {
    assert.deepEqual(cookieOptions(true, 60), { httpOnly: true, secure: true, sameSite: "strict", path: "/", maxAge: 60 });
    assert.equal(AT_COOKIE, "isp_at");
  });
});

describe("proxy", () => {
  it("attaches the token on the server and passes the answer through", async () => {
    const { d, calls } = deps(() => json(200, [{ id: 1 }]));
    const out = await proxy(d, base);
    assert.equal(out.status, 200);
    assert.equal(text(out.body), '[{"id":1}]');
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "http://api:8000/api/v1/customers?q=ali");
    assert.equal(calls[0].auth, "Bearer old-at");
    assert.equal(out.setTokens, undefined);
  });

  it("forwards body and content type on writes", async () => {
    const { d, calls } = deps(() => json(201, { ok: true }));
    const body = new TextEncoder().encode('{"a":1}').buffer as ArrayBuffer;
    const out = await proxy(d, { ...base, method: "POST", segments: ["x"], search: "", body,
      contentType: "application/json", csrf: CSRF_VALUE });
    assert.equal(out.status, 201);
    assert.equal(calls[0].method, "POST");
    assert.equal(calls[0].contentType, "application/json");
    assert.equal(calls[0].body, body);
  });

  it("refuses writes without the header and never calls the server", async () => {
    const { d, calls } = deps(() => json(200, {}));
    const out = await proxy(d, { ...base, method: "POST", csrf: null });
    assert.equal(out.status, 403);
    assert.equal(calls.length, 0);
  });

  it("refuses bad paths and never calls the server", async () => {
    const { d, calls } = deps(() => json(200, {}));
    const out = await proxy(d, { ...base, segments: ["..", "etc"] });
    assert.equal(out.status, 400);
    assert.equal(calls.length, 0);
  });

  it("says 401 and ends the session when there are no cookies at all", async () => {
    const { d, calls } = deps(() => json(200, {}));
    const out = await proxy(d, { ...base, accessToken: undefined, refreshToken: undefined });
    assert.equal(out.status, 401);
    assert.ok(out.clearSession);
    assert.equal(calls.length, 0);
  });

  it("refreshes and retries once when the access token was rejected", async () => {
    const { d, calls } = deps((c) => {
      if (c.url.endsWith("/auth/refresh")) return json(200, NEW);
      return c.auth === "Bearer old-at" ? json(401, { detail: "expired" }) : json(200, { ok: true });
    });
    const out = await proxy(d, base);
    assert.equal(out.status, 200);
    assert.deepEqual(out.setTokens, NEW);
    assert.deepEqual(calls.map((c) => c.url.split("/api/v1")[1]), ["/customers?q=ali", "/auth/refresh", "/customers?q=ali"]);
    assert.equal(calls[2].auth, "Bearer new-at");
  });

  it("refreshes first when only the refresh cookie is left", async () => {
    const { d, calls } = deps((c) => (c.url.endsWith("/auth/refresh") ? json(200, NEW) : json(200, { ok: true })));
    const out = await proxy(d, { ...base, accessToken: undefined });
    assert.equal(out.status, 200);
    assert.deepEqual(out.setTokens, NEW);
    assert.equal(calls.length, 2);
    assert.equal(calls[1].auth, "Bearer new-at");
  });

  it("ends the session when the refresh token is rejected", async () => {
    const { d } = deps((c) => (c.url.endsWith("/auth/refresh") ? json(401, {}) : json(401, {})));
    const out = await proxy(d, base);
    assert.equal(out.status, 401);
    assert.ok(out.clearSession);
  });

  it("does NOT log the user out when the server is only briefly unreachable", async () => {
    const f = fake(() => { throw new Error("ECONNREFUSED"); });
    const d: Deps = { fetchFn: f.fetchFn, apiUrl: API, refresher: new TokenRefresher(f.fetchFn, API) };
    const out = await proxy(d, base);
    assert.equal(out.status, 502);
    assert.ok(!out.clearSession);
    // same when the refresh itself cannot reach the server
    const out2 = await proxy(d, { ...base, accessToken: undefined });
    assert.equal(out2.status, 502);
    assert.ok(!out2.clearSession);
  });

  it("passes permission errors through untouched (the user stays logged in)", async () => {
    const { d } = deps(() => json(403, { detail: "Permission denied" }));
    const out = await proxy(d, base);
    assert.equal(out.status, 403);
    assert.ok(!out.clearSession);
    assert.match(text(out.body), /Permission denied/);
  });

  it("returns no body for 204", async () => {
    const { d } = deps(() => new Response(null, { status: 204 }));
    const out = await proxy(d, { ...base, method: "DELETE", csrf: CSRF_VALUE });
    assert.equal(out.status, 204);
    assert.equal(out.body, null);
  });

  it("several requests expiring together trigger ONE refresh and all succeed", async () => {
    let refreshes = 0;
    const { d } = deps(async (c) => {
      if (c.url.endsWith("/auth/refresh")) {
        refreshes++;
        await new Promise((r) => setTimeout(r, 20)); // slow, so the others pile up behind it
        return json(200, NEW);
      }
      return c.auth === "Bearer new-at" ? json(200, { ok: true }) : json(401, {});
    });
    const results = await Promise.all(Array.from({ length: 6 }, () => proxy(d, base)));
    assert.equal(refreshes, 1);
    for (const r of results) {
      assert.equal(r.status, 200);
      assert.deepEqual(r.setTokens, NEW);
    }
  });
});

describe("token refresher", () => {
  it("reuses a result shortly after, then asks again once the window has passed", async () => {
    let t = 1_000;
    let refreshes = 0;
    const f = fake(() => { refreshes++; return json(200, { ...NEW, access_token: `at-${refreshes}` }); });
    const r = new TokenRefresher(f.fetchFn, API, () => t, 15_000);
    assert.equal((await r.refresh("rt"))?.access_token, "at-1");
    t += 5_000;
    assert.equal((await r.refresh("rt"))?.access_token, "at-1"); // reused
    assert.equal(refreshes, 1);
    t += 20_000;
    assert.equal((await r.refresh("rt"))?.access_token, "at-2"); // window over
    assert.equal(refreshes, 2);
  });

  it("remembers a rejected token (so a flood of retries does not hammer the server)", async () => {
    const f = fake(() => json(401, {}));
    const r = new TokenRefresher(f.fetchFn, API);
    assert.equal(await r.refresh("bad"), null);
    assert.equal(await r.refresh("bad"), null);
    assert.equal(f.calls.length, 1);
  });

  it("never remembers a network failure as 'invalid'", async () => {
    let fail = true;
    const f = fake(() => { if (fail) throw new Error("down"); return json(200, NEW); });
    const r = new TokenRefresher(f.fetchFn, API);
    await assert.rejects(r.refresh("rt"));
    fail = false;
    assert.deepEqual(await r.refresh("rt"), NEW); // works as soon as the server is back
  });

  it("treats a server error (5xx) like a network failure, not a bad token", async () => {
    let status = 500;
    const f = fake(() => (status === 500 ? json(500, {}) : json(200, NEW)));
    const r = new TokenRefresher(f.fetchFn, API);
    await assert.rejects(r.refresh("rt"));
    status = 200;
    assert.deepEqual(await r.refresh("rt"), NEW);
  });
});

describe("login", () => {
  it("returns the tokens on success", async () => {
    const { d, calls } = deps(() => json(200, NEW));
    const r = await loginUpstream(d, "admin", "pw");
    assert.ok(r.ok && r.tokens.access_token === "new-at");
    assert.equal(calls[0].method, "POST");
    assert.match(calls[0].url, /\/api\/v1\/auth\/login$/);
    assert.equal(calls[0].body, JSON.stringify({ username: "admin", password: "pw" }));
  });

  it("passes the server's message on a wrong password", async () => {
    const { d } = deps(() => json(401, { detail: "Invalid username or password" }));
    const r = await loginUpstream(d, "admin", "nope");
    assert.deepEqual(r, { ok: false, status: 401, detail: "Invalid username or password" });
  });

  it("falls back to a plain message when the answer is not JSON", async () => {
    const { d } = deps(() => new Response("<html>bad gateway</html>", { status: 502 }));
    const r = await loginUpstream(d, "a", "b");
    assert.ok(!r.ok && r.status === 502 && r.detail === "Login failed");
  });

  it("reports an unreachable server clearly", async () => {
    const f = fake(() => { throw new Error("down"); });
    const d: Deps = { fetchFn: f.fetchFn, apiUrl: API, refresher: new TokenRefresher(f.fetchFn, API) };
    const r = await loginUpstream(d, "a", "b");
    assert.ok(!r.ok && r.status === 502 && /not reachable/.test(r.detail));
  });
});
