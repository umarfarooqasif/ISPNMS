import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { detailOf, qs } from "../src/lib/api";
import { fmtBytes, fmtDate, isPositiveMoney, money, plural, sumMoney } from "../src/lib/format";
import {
  attachableCustomers, candidateText, canCommit, commitWarnings, defaultRowStatus, isBusy,
  issueLabel, rowName, summaryView,
} from "../src/lib/importview";
import type { ImportRow } from "../src/lib/types";

describe("money", () => {
  it("groups thousands and hides empty paisa", () => {
    assert.equal(money("12500.00"), "Rs 12,500");
    assert.equal(money("1234567.5"), "Rs 1,234,567.50");
    assert.equal(money("999"), "Rs 999");
    assert.equal(money("0.05"), "Rs 0.05");
    assert.equal(money("0.00"), "Rs 0");
    assert.equal(money(1500), "Rs 1,500");
  });
  it("keeps the sign of negatives (credit) and never shows -Rs 0", () => {
    assert.equal(money("-300.00"), "-Rs 300");
    assert.equal(money("-0.00"), "Rs 0");
  });
  it("is exact for large values (no float rounding)", () => {
    assert.equal(money("123456789012.34"), "Rs 123,456,789,012.34");
  });
  it("passes through blanks and junk instead of crashing", () => {
    assert.equal(money(null), "");
    assert.equal(money(undefined), "");
    assert.equal(money(""), "");
    assert.equal(money("abc"), "abc");
  });
  it("knows positive amounts", () => {
    assert.ok(isPositiveMoney("0.01"));
    assert.ok(isPositiveMoney("1500.00"));
    assert.equal(isPositiveMoney("0.00"), false);
    assert.equal(isPositiveMoney("-5.00"), false);
    assert.equal(isPositiveMoney(null), false);
  });
});

describe("dates and sizes", () => {
  it("formats dates without shifting the day", () => {
    assert.equal(fmtDate("2026-10-04"), "4 Oct 2026");
    assert.equal(fmtDate("2026-01-31"), "31 Jan 2026");
    assert.equal(fmtDate("2026-12-01T10:00:00Z"), "1 Dec 2026");
    assert.equal(fmtDate(null), "");
    assert.equal(fmtDate("not a date"), "not a date");
  });
  it("formats sizes and counts", () => {
    assert.equal(fmtBytes(512), "512 B");
    assert.equal(fmtBytes(2048), "2 KB");
    assert.equal(fmtBytes(5 * 1024 * 1024), "5.0 MB");
    assert.equal(plural(1, "row"), "1 row");
    assert.equal(plural(1254, "row"), "1,254 rows");
  });
});

describe("api helpers", () => {
  it("reads FastAPI error messages", () => {
    assert.equal(detailOf({ detail: "Invalid username or password" }, "x"), "Invalid username or password");
    assert.equal(
      detailOf({ detail: [{ loc: ["body", "amount"], msg: "Input should be greater than 0" }] }, "x"),
      "amount: Input should be greater than 0",
    );
    assert.equal(
      detailOf({ detail: [{ loc: ["body", "a"], msg: "bad" }, { loc: ["query", "b"], msg: "worse" }] }, "x"),
      "a: bad; b: worse",
    );
  });
  it("falls back when there is no usable message", () => {
    assert.equal(detailOf(null, "fallback"), "fallback");
    assert.equal(detailOf({}, "fallback"), "fallback");
    assert.equal(detailOf({ detail: "" }, "fallback"), "fallback");
    assert.equal(detailOf({ detail: [] }, "fallback"), "fallback");
  });
  it("builds query strings, skipping empty values", () => {
    assert.equal(qs({ q: "ali khan", limit: 25, offset: 0, status: "" , area: null, x: undefined }), "?q=ali+khan&limit=25&offset=0");
    assert.equal(qs({}), "");
    assert.equal(qs({ flag: false }), "?flag=false");
  });
});

const row = (over: Partial<ImportRow> = {}): ImportRow => ({
  id: "r1", page: 1, row_index: 1, status: "NEW", raw_cells: { Name: "Raw Name", ID: "9001" },
  normalized: { full_name: "Ali Khan", mobile: "03001234567" }, issues: [], match_candidates: [],
  result_customer_id: null, result_connection_id: null, ...over,
});

describe("import screen logic", () => {
  it("knows when the server is still working and when commit is allowed", () => {
    for (const s of ["UPLOADED", "PARSED", "IMPORTING"]) assert.ok(isBusy(s), s);
    for (const s of ["MATCHED", "IN_REVIEW", "COMPLETED", "FAILED"]) assert.equal(isBusy(s), false, s);
    for (const s of ["MATCHED", "IN_REVIEW", "APPROVED"]) assert.ok(canCommit({ status: s }), s);
    for (const s of ["UPLOADED", "PARSED", "IMPORTING", "FAILED"]) assert.equal(canCommit({ status: s }), false, s);
  });

  it("reads a real-looking summary", () => {
    const v = summaryView({
      rows_by_status: { NEW: 1100, REVIEW: 36, ERROR: 2 },
      issue_counts: { NO_MOBILE: 313, INVALID_MOBILE: 29, AREA_INFERRED: 98 },
      packages_to_create: { Star3: 551, "cable 1": 96 },
      areas_to_create: ["Housing Colony"],
      monthly_charge_total: "1080750.00",
      connection_status: { ACTIVE: 1105, DISCONNECTED: 132, FREE: 17 },
    });
    assert.equal(v.totalRows, 1138);
    assert.deepEqual(v.issueCounts[0], ["NO_MOBILE", 313]);
    assert.deepEqual(v.packagesToCreate[0], ["Star3", 551]);
    assert.equal(v.monthlyChargeTotal, "1080750.00");
    assert.equal(v.error, null);
  });

  it("survives a missing or failed summary", () => {
    const empty = summaryView(null);
    assert.equal(empty.totalRows, 0);
    assert.deepEqual(empty.issueCounts, []);
    assert.deepEqual(empty.areasToCreate, []);
    assert.equal(summaryView({ error: "could not read the PDF" }).error, "could not read the PDF");
  });

  it("opens on the tab that needs a person first", () => {
    assert.equal(defaultRowStatus({ NEW: 10, REVIEW: 2 }), "REVIEW");
    assert.equal(defaultRowStatus({ NEW: 10, ERROR: 1 }), "ERROR");
    assert.equal(defaultRowStatus({ NEW: 10 }), "NEW");
    assert.equal(defaultRowStatus({}), "NEW");
  });

  it("names rows and labels issues", () => {
    assert.equal(rowName(row()), "Ali Khan");
    assert.equal(rowName(row({ normalized: null })), "Raw Name");
    assert.equal(rowName(row({ normalized: null, raw_cells: null })), "(no name)");
    assert.equal(issueLabel("NO_MOBILE"), "No mobile number");
    assert.equal(issueLabel("SOMETHING_NEW"), "SOMETHING_NEW");
  });

  it("offers only real existing customers for attaching", () => {
    const r = row({
      status: "REVIEW",
      match_candidates: [
        { kind: "customer", customer_id: "c1", customer_code: "CU-000007", name: "Ali Khan" },
        { kind: "same_file", wasooli_id: "123", name: "Ali K", row_index: 5 },
        { kind: "customer", name: "No id" },
      ],
    });
    const list = attachableCustomers(r);
    assert.equal(list.length, 1);
    assert.equal(list[0].customer_id, "c1");
    assert.match(candidateText(list[0]), /CU-000007/);
    assert.match(candidateText(r.match_candidates![1]), /Another row in this file/);
    assert.deepEqual(attachableCustomers(row({ match_candidates: null })), []);
  });

  it("lists what the preview will create so the person can confirm", () => {
    assert.deepEqual(commitWarnings(null), []);
    assert.deepEqual(commitWarnings({}), []);
    assert.deepEqual(commitWarnings({ areas_to_create: ["A", "B"], packages_to_create: ["P"] }), [
      "2 new area(s) will be created", "1 new package(s) will be created",
    ]);
  });
});

describe("sumMoney", () => {
  it("adds exactly, with no floating-point drift", () => {
    assert.equal(sumMoney(["0.10", "0.20"]), "0.30");
    assert.equal(sumMoney(["1500.50", "1500.50", "0.01"]), "3001.01");
    assert.equal(sumMoney(["999999999999.99", "0.01"]), "1000000000000.00");
  });
  it("handles negatives, blanks and junk", () => {
    assert.equal(sumMoney(["100", "-250.5"]), "-150.50");
    assert.equal(sumMoney([]), "0.00");
    assert.equal(sumMoney([null, undefined, "", "abc", "5"]), "5.00");
  });
});
