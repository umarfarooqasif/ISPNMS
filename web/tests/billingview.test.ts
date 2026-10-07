import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  amountProblem, itemsByOutcome, outcomeNeedsAttention, paramsKey, parseOpeningBalanceCsv,
  runHeadline, runParamsProblem, splitCsvLine, toRunBody, validAmount, type RunParams,
} from "../src/lib/billingview";
import type { RunItem } from "../src/lib/types";

const params = (over: Partial<RunParams> = {}): RunParams => ({
  runDate: "", leadDays: "", maxCycles: 1, skipRemaining: false, ...over,
});

describe("bill run form", () => {
  it("sends only what the person set", () => {
    assert.deepEqual(toRunBody(params()), { max_cycles: 1, skip_remaining: false });
    assert.deepEqual(toRunBody(params({ runDate: "2026-10-04", leadDays: "7", maxCycles: 3, skipRemaining: true })),
      { max_cycles: 3, skip_remaining: true, run_date: "2026-10-04", lead_days: 7 });
    assert.deepEqual(toRunBody(params({ leadDays: "0" })), { max_cycles: 1, skip_remaining: false, lead_days: 0 });
  });

  it("explains a bad setting in plain words", () => {
    assert.equal(runParamsProblem(params()), null);
    assert.match(runParamsProblem(params({ leadDays: "abc" }))!, /whole number/);
    assert.match(runParamsProblem(params({ leadDays: "61" }))!, /60 or less/);
    assert.match(runParamsProblem(params({ maxCycles: 0 }))!, /between 1 and 12/);
    assert.match(runParamsProblem(params({ maxCycles: 13 }))!, /between 1 and 12/);
    assert.match(runParamsProblem(params({ maxCycles: 1.5 }))!, /between 1 and 12/);
    assert.match(runParamsProblem(params({ runDate: "4 Oct" }))!, /year-month-day/);
  });

  it("changing any setting invalidates an earlier preview", () => {
    const base = paramsKey(params());
    assert.equal(paramsKey(params()), base);
    for (const changed of [params({ runDate: "2026-10-04" }), params({ leadDays: "3" }), params({ maxCycles: 2 }),
      params({ skipRemaining: true })]) {
      assert.notEqual(paramsKey(changed), base);
    }
    assert.equal(paramsKey(params({ leadDays: " 3 " })), paramsKey(params({ leadDays: "3" })));
  });

  it("describes a run in one sentence", () => {
    assert.equal(runHeadline({ invoices_created: 1079, counts: { INVOICED: 1079 }, behind_connections: 0, skipped_cycles: 0 }, true),
      "1,079 invoice(s) would be created");
    assert.equal(
      runHeadline({ invoices_created: 10, counts: { INVOICED: 10, ZERO_PRICE: 26, ERROR: 1 }, behind_connections: 509, skipped_cycles: 4 }, false),
      "10 invoice(s) created, 27 item(s) need attention, 509 connection(s) still behind, 4 missed month(s) left out");
  });

  it("flags the outcomes a person must look at", () => {
    for (const o of ["ERROR", "ZERO_PRICE", "NO_DUE_DATE", "CYCLES_SKIPPED"]) assert.ok(outcomeNeedsAttention(o), o);
    for (const o of ["INVOICED", "FREE_SKIPPED", "LATE_FEE"]) assert.equal(outcomeNeedsAttention(o), false, o);
  });

  it("filters items by outcome", () => {
    const mk = (outcome: string): RunItem => ({ customer_id: "c", customer_name: null, customer_code: null, connection_id: null, cycle_due_date: null, outcome, amount: "0", invoice_id: null, message: null });
    const items = [mk("INVOICED"), mk("ERROR"), mk("INVOICED")];
    assert.equal(itemsByOutcome(items, "INVOICED").length, 2);
    assert.equal(itemsByOutcome(items, "").length, 3);
    assert.equal(itemsByOutcome(items, "NO_DUE_DATE").length, 0);
  });
});

describe("amounts", () => {
  it("accepts plain positive amounts only", () => {
    for (const ok of ["1", "1500", "1500.5", "1500.50", "0.01", " 200 "]) assert.ok(validAmount(ok), ok);
    for (const bad of ["", "0", "0.00", "-5", "1,500", "10.555", "abc", "1e3", ".5", "5.", "Rs 5"]) {
      assert.equal(validAmount(bad), false, bad);
    }
  });

  it("gives a reason for each kind of mistake", () => {
    assert.equal(amountProblem("1500"), null);
    assert.match(amountProblem("")!, /Enter the amount/);
    assert.match(amountProblem("10.555")!, /two decimals/);
    assert.match(amountProblem("0")!, /more than zero/);
  });
});

describe("opening balance CSV", () => {
  it("reads a clean list", () => {
    const r = parseOpeningBalanceCsv("wasooli_id,amount,note\n9001,1500,old register\n9002,250.50,\n");
    assert.deepEqual(r.problems, []);
    assert.deepEqual(r.rows, [
      { wasooli_id: "9001", amount: "1500", note: "old register" },
      { wasooli_id: "9002", amount: "250.50" },
    ]);
  });

  it("copes with Windows line endings, blank lines, reordered columns and quotes", () => {
    const r = parseOpeningBalanceCsv('amount,wasooli_id,note\r\n\r\n700,"9003","paid ""late"", sorry"\r\n');
    assert.deepEqual(r.problems, []);
    assert.deepEqual(r.rows, [{ wasooli_id: "9003", amount: "700", note: 'paid "late", sorry' }]);
  });

  it("reports bad lines with their line number and skips them", () => {
    const r = parseOpeningBalanceCsv("wasooli_id,amount\n9001,100\n9002,abc\n,50\n9004,-5\n9005,0\n9006,75");
    assert.deepEqual(r.rows.map((x) => x.wasooli_id), ["9001", "9006"]);
    assert.deepEqual(r.problems.map((p) => p.line), [3, 4, 5, 6]);
    assert.match(r.problems[0].text, /abc/);
    assert.match(r.problems[1].text, /Missing wasooli_id/);
  });

  it("insists on a header and handles empty input", () => {
    const noHeader = parseOpeningBalanceCsv("9001,100\n9002,200");
    assert.equal(noHeader.rows.length, 0);
    assert.match(noHeader.problems[0].text, /header/);
    const empty = parseOpeningBalanceCsv("   \n");
    assert.equal(empty.rows.length, 0);
    assert.equal(empty.problems.length, 1);
  });

  it("splits quoted fields", () => {
    assert.deepEqual(splitCsvLine('a, "b,c" ,d'), ["a", "b,c", "d"]);
    assert.deepEqual(splitCsvLine("a,,c"), ["a", "", "c"]);
  });
});
