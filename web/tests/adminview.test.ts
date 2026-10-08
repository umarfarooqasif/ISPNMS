import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  EMPTY_CUSTOMER, auditHighlights, cnicProblem, connectionBody, connectionProblems, connectionWarning,
  customerBody, customerProblems, describeAction, emptyConnection, formFromCustomer, passwordProblem,
  phoneProblem, redact, sameSet, statusChangeBody, statusChangeProblem, statusChoices, toggleId,
  usernameProblem, withType, type CustomerForm,
} from "../src/lib/adminview";
import type { Customer } from "../src/lib/types";

describe("users", () => {
  it("checks usernames", () => {
    assert.equal(usernameProblem("ali.khan"), null);
    assert.equal(usernameProblem("a_b-9"), null);
    assert.match(usernameProblem("ab")!, /at least 3/);
    assert.match(usernameProblem("ali khan")!, /letters, digits/);
    assert.match(usernameProblem("x".repeat(65))!, /too long/);
  });
  it("checks passwords without being fussy", () => {
    assert.equal(passwordProblem("correct horse battery"), null);
    assert.match(passwordProblem("short")!, /at least 10/);
    assert.match(passwordProblem("alikhan12345", "AliKhan")!, /username/);
    assert.match(passwordProblem("aaaaaaaaaaaa")!, /repeated/);
    assert.match(passwordProblem("x".repeat(129))!, /too long/);
  });
});

describe("customer form", () => {
  const good: CustomerForm = { ...EMPTY_CUSTOMER, full_name: "Ali Khan", mobile: "0300-1234567", cnic: "35202-1234567-1" };
  it("needs a name and sane numbers, nothing else", () => {
    assert.deepEqual(customerProblems(good), []);
    assert.deepEqual(customerProblems({ ...EMPTY_CUSTOMER, full_name: "Ali" }), []);
    assert.deepEqual(customerProblems({ ...good, full_name: "  " }), ["Enter the customer's name."]);
    assert.equal(customerProblems({ ...good, mobile: "123" }).length, 1);
    assert.equal(customerProblems({ ...good, cnic: "12345" }).length, 1);
    assert.equal(phoneProblem(""), null);
    assert.equal(phoneProblem("+92 300 1234567"), null);
    assert.equal(cnicProblem("3520212345671"), null);
  });

  const original: Customer = {
    id: "1", customer_code: "CU-1", full_name: "Ali Khan", full_name_ur: "علی خان", father_name: null, cnic_masked: "*****-*******-1",
    mobile: "03001234567", whatsapp: null, alt_contact: null, address: "Street 3", address_ur: null, area_id: "a1",
    house_no: "5", notes: null, status: "ACTIVE", created_at: "2026-01-01",
  };

  it("create sends only filled fields", () => {
    assert.deepEqual(customerBody({ ...EMPTY_CUSTOMER, full_name: " Bilal ", mobile: " 0301 " }), { full_name: "Bilal", mobile: "0301" });
  });

  it("edit sends only what changed", () => {
    const form = formFromCustomer(original);
    assert.deepEqual(customerBody(form, formFromCustomer(original)), {});
    assert.deepEqual(customerBody({ ...form, mobile: "03009999999" }, formFromCustomer(original)), { mobile: "03009999999" });
  });

  it("edit never wipes the stored CNIC just because the form cannot show it", () => {
    const form = formFromCustomer(original);
    assert.equal(form.cnic, "");
    assert.equal("cnic" in customerBody({ ...form, house_no: "6" }, formFromCustomer(original)), false);
    assert.equal(customerBody({ ...form, cnic: "35202-1234567-1" }, formFromCustomer(original)).cnic, "35202-1234567-1");
  });

  it("clearing a field on purpose sends null", () => {
    const form = { ...formFromCustomer(original), address: "", area_id: "" };
    assert.deepEqual(customerBody(form, formFromCustomer(original)), { address: null, area_id: null });
  });
});

describe("connection form", () => {
  it("keeps service lines in step with the type", () => {
    const f = emptyConnection();
    assert.ok(f.internet.enabled && !f.cable.enabled);
    const combined = withType(f, "COMBINED");
    assert.ok(combined.internet.enabled && combined.cable.enabled);
    const cable = withType(f, "CABLE");
    assert.ok(!cable.internet.enabled && cable.cable.enabled);
  });

  it("needs a package or a price for each service", () => {
    assert.equal(connectionProblems(emptyConnection()).length, 1);
    const f = emptyConnection();
    f.internet.package_id = "pkg1";
    assert.deepEqual(connectionProblems(f), []);
    f.internet.package_id = "";
    f.internet.price = "1500.50";
    assert.deepEqual(connectionProblems(f), []);
    f.internet.price = "15,00";
    assert.match(connectionProblems(f)[0], /amount like/);
    const g = withType(emptyConnection(), "COMBINED");
    g.internet.price = "1000";
    assert.equal(connectionProblems(g).length, 1);          // cable still missing
  });

  it("builds the request and warns about a missing due date", () => {
    const f = withType(emptyConnection(), "COMBINED");
    f.internet_id = " ali1 ";
    f.internet.package_id = "p1";
    f.cable.price = "300";
    assert.deepEqual(connectionBody(f), {
      connection_type: "COMBINED", internet_id: "ali1",
      service_lines: [
        { service: "INTERNET", package_id: "p1", price: null },
        { service: "CABLE", package_id: null, price: "300" },
      ],
    });
    assert.match(connectionWarning(f)!, /not be billed/);
    f.next_due_date = "2026-11-01";
    assert.equal(connectionWarning(f), null);
    assert.equal(connectionBody(f).next_due_date, "2026-11-01");
  });
});

describe("connection status change", () => {
  it("offers sensible choices and never the current status", () => {
    const fromActive = statusChoices("ACTIVE").map((c) => c.status);
    assert.ok(!fromActive.includes("ACTIVE") && fromActive.includes("SUSPENDED") && fromActive.includes("DISCONNECTED"));
    assert.equal(statusChoices("SUSPENDED").find((c) => c.status === "ACTIVE")!.label, "Reactivate");
    assert.equal(statusChoices("FREE").find((c) => c.status === "ACTIVE")!.label, "Make active");
  });

  it("always needs a reason", () => {
    assert.match(statusChangeProblem({ current: "ACTIVE", target: "SUSPENDED", reason: "x", fee: "", nextDue: "" })!, /why/);
    assert.equal(statusChangeProblem({ current: "ACTIVE", target: "SUSPENDED", reason: "non-payment", fee: "", nextDue: "" }), null);
  });

  it("allows a reconnection fee only when reactivating", () => {
    const base = { reason: "paid up", nextDue: "" };
    assert.equal(statusChangeProblem({ ...base, current: "SUSPENDED", target: "ACTIVE", fee: "500" }), null);
    assert.equal(statusChangeProblem({ ...base, current: "DISCONNECTED", target: "ACTIVE", fee: "500.50" }), null);
    assert.match(statusChangeProblem({ ...base, current: "ACTIVE", target: "SUSPENDED", fee: "500" })!, /only applies when reactivating/);
    assert.match(statusChangeProblem({ ...base, current: "SUSPENDED", target: "ACTIVE", fee: "5oo" })!, /amount like/);
  });

  it("allows a due date only for billable statuses", () => {
    const base = { reason: "because", fee: "" };
    assert.equal(statusChangeProblem({ ...base, current: "SUSPENDED", target: "ACTIVE", nextDue: "2026-11-01" }), null);
    assert.match(statusChangeProblem({ ...base, current: "ACTIVE", target: "DISCONNECTED", nextDue: "2026-11-01" })!, /only applies/);
    assert.match(statusChangeProblem({ ...base, current: "SUSPENDED", target: "ACTIVE", nextDue: "1 Nov" })!, /year-month-day/);
  });

  it("builds the request", () => {
    assert.deepEqual(statusChangeBody({ target: "ACTIVE", reason: " paid up ", fee: " 500 ", nextDue: "2026-11-01" }),
      { status: "ACTIVE", reason: "paid up", reconnection_fee: "500", next_due_date: "2026-11-01" });
    assert.deepEqual(statusChangeBody({ target: "SUSPENDED", reason: "late", fee: "", nextDue: "" }), { status: "SUSPENDED", reason: "late" });
  });
});

describe("assignments", () => {
  it("toggles ids without mutating", () => {
    const a = ["1", "2"];
    assert.deepEqual(toggleId(a, "3"), ["1", "2", "3"]);
    assert.deepEqual(toggleId(a, "1"), ["2"]);
    assert.deepEqual(a, ["1", "2"]);
  });
  it("compares sets ignoring order", () => {
    assert.ok(sameSet(["a", "b"], ["b", "a"]));
    assert.equal(sameSet(["a"], ["a", "b"]), false);
    assert.equal(sameSet(["a", "a"], ["a", "b"]), false);
    assert.ok(sameSet([], []));
  });
});

describe("audit log", () => {
  it("describes known actions and passes unknown ones through", () => {
    assert.equal(describeAction("payment.void"), "Cancelled a payment");
    assert.equal(describeAction("something.new"), "something.new");
  });
  it("picks the few useful details", () => {
    assert.deepEqual(auditHighlights({ before: null, after: { amount: "500.00", receipt_number: "RC-000001", junk: 1 } }),
      ["amount: 500.00", "receipt: RC-000001"]);
    assert.deepEqual(auditHighlights({ before: { status: "ACTIVE" }, after: { status: "SUSPENDED", reason: "late" } }),
      ["reason: late", "status: SUSPENDED", "was: ACTIVE"]);
    assert.deepEqual(auditHighlights({ before: null, after: null }), []);
  });
  it("never displays secrets", () => {
    assert.deepEqual(redact({ password: "hunter2", nested: { api_token: "abc", cnic: "35202", name: "x" }, list: [{ secret: 1 }] }),
      { password: "••••", nested: { api_token: "••••", cnic: "••••", name: "x" }, list: [{ secret: "••••" }] });
  });
});
