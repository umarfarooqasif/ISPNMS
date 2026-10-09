import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { absMoney, balanceText, columns, entryLabel, isNegative, usageText } from "../src/lib/history";

describe("customer history wording", () => {
  it("names every kind of ledger entry", () => {
    assert.equal(entryLabel("CHARGE"), "Bill");
    assert.equal(entryLabel("PAYMENT"), "Payment received");
    assert.equal(entryLabel("PAYMENT_REVERSAL"), "Payment cancelled");
    assert.equal(entryLabel("ADJUSTMENT"), "Adjustment");
    assert.equal(entryLabel("SOMETHING_ELSE"), "SOMETHING_ELSE");
  });

  it("spots negative amounts exactly", () => {
    for (const neg of ["-500.00", "-0.01", "-100", "-1000.50"]) assert.ok(isNegative(neg), neg);
    for (const not of ["500.00", "0.00", "-0.00", "0", ""]) assert.equal(isNegative(not), false, not);
    assert.equal(absMoney("-500.00"), "500.00");
    assert.equal(absMoney("500.00"), "500.00");
  });

  it("splits an amount into charged and credited columns", () => {
    assert.deepEqual(columns("2000.00"), { charged: "Rs 2,000", credited: "" });
    assert.deepEqual(columns("-500.00"), { charged: "", credited: "Rs 500" });
    assert.deepEqual(columns("0.00"), { charged: "", credited: "" });
  });

  it("says what a balance means", () => {
    assert.equal(balanceText("1500.00"), "Rs 1,500 owed");
    assert.equal(balanceText("-300.50"), "Rs 300.50 credit");
    assert.equal(balanceText("0.00"), "Rs 0");
  });

  it("describes how a payment was used", () => {
    assert.equal(usageText("500.00", "0.00"), "Rs 500 paid against bills");
    assert.equal(usageText("300.00", "700.00"), "Rs 300 paid against bills, Rs 700 kept as advance credit");
    assert.equal(usageText("0.00", "1000.00"), "Rs 1,000 kept as advance credit");
    assert.equal(usageText("0.00", "0.00"), "Recorded");
  });
});
