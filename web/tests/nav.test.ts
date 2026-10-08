import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { NAV, isActive, visibleNav } from "../src/lib/nav";

describe("menu", () => {
  it("lights up only the page you are on", () => {
    assert.ok(isActive("/", "/"));
    assert.equal(isActive("/customers", "/"), false);
    assert.ok(isActive("/customers", "/customers"));
    assert.ok(isActive("/customers/abc", "/customers"));
    assert.equal(isActive("/billing/runs", "/billing/run"), false);   // the trap
    assert.equal(isActive("/billing/runs/abc", "/billing/run"), false);
    assert.ok(isActive("/billing/runs/abc", "/billing/runs"));
    assert.ok(isActive("/billing/run", "/billing/run"));
    assert.equal(isActive("/customersx", "/customers"), false);
  });

  it("never lights two items for the same page", () => {
    for (const path of ["/", "/customers", "/customers/1", "/payments", "/payments/9", "/billing/run", "/billing/runs",
      "/billing/runs/7", "/billing/outstanding", "/billing/late-fees", "/billing/opening-balances", "/import", "/import/3", "/collectors", "/collectors/9", "/users", "/audit", "/customers/new"]) {
      const lit = NAV.filter((n) => isActive(path, n.href));
      assert.equal(lit.length, 1, `${path} lit ${lit.map((n) => n.href).join(", ")}`);
    }
  });

  it("shows each person only what their role allows", () => {
    assert.deepEqual(visibleNav([]).map((n) => n.href), ["/"]);
    const accountant = visibleNav(["customer.view", "invoice.view", "payment.view", "billing.run", "billing.opening_balance"]).map((n) => n.href);
    assert.ok(accountant.includes("/billing/run") && accountant.includes("/payments"));
    assert.equal(accountant.includes("/import"), false);
    const all = visibleNav(NAV.map((n) => n.permission).filter((p): p is string => !!p));
    assert.equal(all.length, NAV.length);
  });

  it("has unique links", () => {
    assert.equal(new Set(NAV.map((n) => n.href)).size, NAV.length);
  });
});
