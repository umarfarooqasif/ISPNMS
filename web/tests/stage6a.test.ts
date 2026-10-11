import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { adjustBody, adjustProblem, balanceAfter, exceeds, refundBody, refundProblem, signedAmount } from "../src/lib/adjustview";
import { FIELDS, changesFrom, defaultText, fieldProblem, formProblems, normalize, toForm } from "../src/lib/settingsview";
import { overrideWarning, planBody, planProblems, servicesFor } from "../src/lib/planview";

const spec = (key: string) => FIELDS.find((f) => f.key === key)!;
const current = {
  "billing.lead_days": 5, "late_fee.amount": "0.00", "late_fee.grace_days": 5, "late_fee.due_days": 7,
  "import.recharge_date_means": "NEXT_DUE", "company.name": "", "company.phone": "", "company.address": "",
};

describe("settings form", () => {
  it("has a field for every server setting, with unique keys", () => {
    assert.equal(new Set(FIELDS.map((f) => f.key)).size, FIELDS.length);
    assert.deepEqual(FIELDS.map((f) => f.key).sort(), Object.keys(current).sort());
  });

  it("checks numbers against their range, like the server", () => {
    const lead = spec("billing.lead_days");
    assert.equal(fieldProblem(lead, "5"), null);
    assert.equal(fieldProblem(lead, "0"), null);
    assert.equal(fieldProblem(lead, "60"), null);
    for (const bad of ["61", "-1", "abc", "5.5", "", "1e3"]) assert.notEqual(fieldProblem(lead, bad), null, bad);
    assert.match(fieldProblem(spec("late_fee.grace_days"), "91")!, /0 to 90/);
  });

  it("checks money as exact amounts", () => {
    const fee = spec("late_fee.amount");
    for (const ok of ["0", "100", "100.5", "100.50"]) assert.equal(fieldProblem(fee, ok), null, ok);
    for (const bad of ["-5", "1,000", "10.555", "abc", "", "Rs 5"]) assert.notEqual(fieldProblem(fee, bad), null, bad);
  });

  it("checks choices and text length", () => {
    assert.equal(fieldProblem(spec("import.recharge_date_means"), "LAST_RECHARGE"), null);
    assert.notEqual(fieldProblem(spec("import.recharge_date_means"), "SOMETIMES"), null);
    assert.equal(fieldProblem(spec("company.name"), ""), null);
    assert.notEqual(fieldProblem(spec("company.name"), "x".repeat(121)), null);
  });

  it("treats 75 and 75.00 as the same fee, and 05 as 5", () => {
    const fee = spec("late_fee.amount");
    assert.equal(normalize(fee, "75"), "75.00");
    assert.equal(normalize(fee, "75.5"), "75.50");
    assert.equal(normalize(fee, "007.1"), "7.10");
    assert.equal(normalize(spec("billing.lead_days"), "05"), "5");
    assert.equal(normalize(spec("company.name"), "  Fast   Net "), "Fast Net");
  });

  it("sends only what changed", () => {
    const form = toForm(current);
    assert.deepEqual(changesFrom(form, current), {});
    assert.deepEqual(changesFrom({ ...form, "late_fee.amount": "75" }, current), { "late_fee.amount": "75.00" });
    assert.deepEqual(changesFrom({ ...form, "billing.lead_days": "5.0" }, current), { "billing.lead_days": "5.0" });   // invalid text is still passed on for the check to catch
    assert.deepEqual(changesFrom({ ...form, "late_fee.amount": "0" }, current), {});                                   // 0 equals 0.00
    assert.deepEqual(changesFrom({ ...form, "company.name": " Fast Net " }, current), { "company.name": "Fast Net" });
  });

  it("collects every problem before saving", () => {
    const form = { ...toForm(current), "billing.lead_days": "x", "late_fee.amount": "-1" };
    assert.equal(formProblems(form).length, 2);
    assert.deepEqual(formProblems(toForm(current)), []);
  });

  it("describes the standard value in words", () => {
    assert.equal(defaultText(spec("late_fee.amount"), "0.00"), "Rs 0");
    assert.equal(defaultText(spec("late_fee.amount"), "50.50"), "Rs 50.50");
    assert.equal(defaultText(spec("import.recharge_date_means"), "NEXT_DUE"), "The date the next payment is due");
    assert.equal(defaultText(spec("company.name"), ""), "not set");
    assert.equal(defaultText(spec("billing.lead_days"), 5), "5");
  });
});

describe("adjustments and refunds", () => {
  it("turns a credit into a negative amount and a charge into a positive one", () => {
    assert.equal(signedAmount("credit", " 250 "), "-250");
    assert.equal(signedAmount("charge", "250"), "250");
    assert.deepEqual(adjustBody("c1", "credit", "250.50", "  waived by manager "), { customer_id: "c1", amount: "-250.50", reason: "waived by manager" });
  });

  it("needs a valid amount and a reason", () => {
    assert.equal(adjustProblem("250", "waived"), null);
    assert.match(adjustProblem("", "waived")!, /Enter the amount/);
    assert.match(adjustProblem("0", "waived")!, /more than zero/);
    assert.match(adjustProblem("-5", "waived")!, /digits only/);
    assert.match(adjustProblem("250", "ab")!, /why/);
    assert.match(adjustProblem("250", "x".repeat(301))!, /too long/);
  });

  it("shows the balance after, exactly", () => {
    assert.equal(balanceAfter("1000.00", "credit", "250"), "Rs 750 owed");
    assert.equal(balanceAfter("1000.00", "charge", "0.10"), "Rs 1,000.10 owed");
    assert.equal(balanceAfter("100.00", "credit", "250"), "Rs 150 credit");
    assert.equal(balanceAfter("250.00", "credit", "250"), "Rs 0");
    assert.equal(balanceAfter("0.10", "charge", "0.20"), "Rs 0.30 owed");        // no floating-point drift
  });

  it("compares amounts exactly", () => {
    assert.ok(exceeds("500.01", "500.00"));
    assert.equal(exceeds("500.00", "500.00"), false);
    assert.equal(exceeds("499.99", "500.00"), false);
    assert.ok(exceeds("0.01", "0"));
  });

  it("lets a refund be at most the credit the customer has", () => {
    assert.equal(refundProblem("300", "customer left", "300.00"), null);
    assert.equal(refundProblem("100", "customer left", "300.00"), null);
    assert.match(refundProblem("300.01", "customer left", "300.00")!, /only pay back the credit/);
    assert.match(refundProblem("100", "customer left", "0.00")!, /only pay back the credit/);
    assert.match(refundProblem("", "customer left", "300")!, /Enter the amount/);
    assert.match(refundProblem("100", "x", "300")!, /why/);
    assert.deepEqual(refundBody("c1", " 100 ", " left "), { customer_id: "c1", amount: "100", reason: "left" });
  });
});

describe("changing a package", () => {
  it("offers only the services a connection has", () => {
    assert.deepEqual(servicesFor("INTERNET"), ["INTERNET"]);
    assert.deepEqual(servicesFor("CABLE"), ["CABLE"]);
    assert.deepEqual(servicesFor("COMBINED"), ["INTERNET", "CABLE"]);
  });

  it("needs a package or a price, a valid price, and a reason", () => {
    const base = { service: "INTERNET" as const, packageId: "", price: "", reason: "customer asked" };
    assert.equal(planProblems({ ...base, packageId: "p1" }).length, 0);
    assert.equal(planProblems({ ...base, price: "1200" }).length, 0);
    assert.equal(planProblems(base).length, 1);
    assert.equal(planProblems({ ...base, price: "12,00" }).length, 1);
    assert.equal(planProblems({ ...base, packageId: "p1", reason: "x" }).length, 1);
  });

  it("sends only what was filled", () => {
    assert.deepEqual(planBody({ service: "CABLE", packageId: "p1", price: "", reason: " upgrade " }), { service: "CABLE", reason: "upgrade", package_id: "p1" });
    assert.deepEqual(planBody({ service: "INTERNET", packageId: "", price: " 850 ", reason: "special" }), { service: "INTERNET", reason: "special", price: "850" });
  });

  it("warns when a special price would make the change pointless", () => {
    assert.match(overrideWarning("900.00")!, /special monthly price/);
    assert.equal(overrideWarning(null), null);
  });
});

import { DEFAULT_COMPANY, mergeCompany } from "../src/lib/company";

describe("business details on receipts", () => {
  it("prefers saved settings, then the configuration file, then a plain default", () => {
    assert.deepEqual(mergeCompany({ name: "Fast Net", phone: "042 1", address: "Lahore" }, { name: "Old", phone: "9", address: "X" }),
      { name: "Fast Net", phone: "042 1", address: "Lahore" });
    assert.deepEqual(mergeCompany({ name: "", phone: "", address: "" }, { name: "From File", phone: "555", address: "Karachi" }),
      { name: "From File", phone: "555", address: "Karachi" });
    assert.deepEqual(mergeCompany({ name: "", phone: "", address: "" }, { name: "", phone: "", address: "" }), DEFAULT_COMPANY);
  });
  it("mixes fields independently and copes with missing answers", () => {
    assert.deepEqual(mergeCompany({ name: "Fast Net", phone: "", address: "" }, { name: "Old", phone: "555", address: "" }),
      { name: "Fast Net", phone: "555", address: "" });
    assert.deepEqual(mergeCompany(null, null), DEFAULT_COMPANY);
    assert.deepEqual(mergeCompany(undefined, { name: "File" }), { name: "File", phone: "", address: "" });
    assert.equal(mergeCompany({ name: "   " }, null).name, "ISP Billing");
  });
});
