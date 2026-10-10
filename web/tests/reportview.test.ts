import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { EXPORTS, exportFilename, exportPath, localIsoDate, presetRange, rangeProblem } from "../src/lib/reportview";

describe("report date presets", () => {
  const today = "2026-10-04";
  it("gives inclusive ranges ending today", () => {
    assert.deepEqual(presetRange("today", today), { from: "2026-10-04", to: "2026-10-04" });
    assert.deepEqual(presetRange("last7", today), { from: "2026-09-28", to: "2026-10-04" });
    assert.deepEqual(presetRange("last30", today), { from: "2026-09-05", to: "2026-10-04" });
    assert.deepEqual(presetRange("month", today), { from: "2026-10-01", to: "2026-10-04" });
    assert.deepEqual(presetRange("year", today), { from: "2026-01-01", to: "2026-10-04" });
  });
  it("finds last month across month and year boundaries", () => {
    assert.deepEqual(presetRange("lastMonth", today), { from: "2026-09-01", to: "2026-09-30" });
    assert.deepEqual(presetRange("lastMonth", "2026-01-15"), { from: "2025-12-01", to: "2025-12-31" });
    assert.deepEqual(presetRange("lastMonth", "2026-03-01"), { from: "2026-02-01", to: "2026-02-28" });
    assert.deepEqual(presetRange("lastMonth", "2028-03-10"), { from: "2028-02-01", to: "2028-02-29" });
  });
  it("counts days correctly over a month end and a leap day", () => {
    assert.deepEqual(presetRange("last7", "2026-03-03"), { from: "2026-02-25", to: "2026-03-03" });
    assert.deepEqual(presetRange("last7", "2028-03-02"), { from: "2028-02-25", to: "2028-03-02" });
  });
  it("reads the local calendar day without timezone drift", () => {
    assert.equal(localIsoDate(new Date(2026, 9, 4, 23, 59)), "2026-10-04");
    assert.equal(localIsoDate(new Date(2026, 0, 1, 0, 0)), "2026-01-01");
  });
});

describe("custom range", () => {
  it("accepts good ranges and explains bad ones", () => {
    assert.equal(rangeProblem("2026-10-01", "2026-10-04"), null);
    assert.equal(rangeProblem("2026-10-04", "2026-10-04"), null);
    assert.match(rangeProblem("", "2026-10-04")!, /both dates/);
    assert.match(rangeProblem("2026-10-05", "2026-10-01")!, /before the start/);
    assert.match(rangeProblem("2025-01-01", "2026-10-01")!, /at most 366/);
    assert.equal(rangeProblem("2025-10-04", "2026-10-04"), null);          // exactly 366 days
    assert.match(rangeProblem("2025-10-03", "2026-10-04")!, /at most 366/);
  });
});

describe("exports", () => {
  it("builds the address and file name, with dates only where they apply", () => {
    assert.equal(exportPath("payments", "2026-10-01", "2026-10-04"), "/reports/export/payments.csv?date_from=2026-10-01&date_to=2026-10-04");
    assert.equal(exportPath("customers", "2026-10-01", "2026-10-04"), "/reports/export/customers.csv");
    assert.equal(exportFilename("invoices", "2026-10-01", "2026-10-04"), "invoices_2026-10-01_to_2026-10-04.csv");
    assert.equal(exportFilename("outstanding", "2026-10-01", "2026-10-04"), "outstanding.csv");
    assert.equal(exportPath("payments"), "/reports/export/payments.csv");
  });
  it("lists four exports with unique names", () => {
    assert.equal(new Set(EXPORTS.map((e) => e.name)).size, 4);
  });
});
