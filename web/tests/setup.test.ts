import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  EMPTY_PACKAGE, areaBody, areaProblem, formFromPackage, optionalAmountProblem, packageBody, packageProblems,
  packageWarning, type PackageForm,
} from "../src/lib/setup";
import type { PackageFull } from "../src/lib/types";

const good: PackageForm = { ...EMPTY_PACKAGE, code: "star3", name: "Star3", display_name: "Star 3", internet_price: "1200" };

const stored: PackageFull = {
  id: "1", code: "star3", name: "Star3", display_name: "Star 3", display_name_ur: "اسٹار 3", speed_mbps: 3,
  monthly_price: null, cable_price: null, internet_price: "1200.00", status: "ACTIVE", description: null, aliases: [],
};

describe("packages", () => {
  it("accepts a good package and rejects the obvious mistakes", () => {
    assert.deepEqual(packageProblems(good, true), []);
    assert.equal(packageProblems({ ...good, code: "" }, true).length, 1);
    assert.equal(packageProblems({ ...good, code: "star 3" }, true).length, 1);
    assert.deepEqual(packageProblems({ ...good, code: "" }, false), []); // the code is fixed once created
    assert.equal(packageProblems({ ...good, name: " " }, true).length, 1);
    assert.equal(packageProblems({ ...good, display_name: "" }, true).length, 1);
  });

  it("checks prices and speed", () => {
    assert.equal(optionalAmountProblem("", "x"), null);
    assert.equal(optionalAmountProblem("0", "x"), null);
    assert.equal(optionalAmountProblem("1500.50", "x"), null);
    assert.match(optionalAmountProblem("1,500", "The price")!, /The price must be an amount/);
    assert.match(optionalAmountProblem("-5", "x")!, /amount/);
    assert.equal(packageProblems({ ...good, internet_price: "12o0" }, true).length, 1);
    assert.equal(packageProblems({ ...good, speed_mbps: "fast" }, true).length, 1);
    assert.deepEqual(packageProblems({ ...good, speed_mbps: "10" }, true), []);
  });

  it("warns when no price is set at all", () => {
    assert.match(packageWarning({ ...good, internet_price: "" })!, /No price/);
    assert.equal(packageWarning(good), null);
  });

  it("creating sends only what was filled, trimmed", () => {
    assert.deepEqual(packageBody({ ...good, code: " star3 ", speed_mbps: "3" }), {
      code: "star3", name: "Star3", display_name: "Star 3", internet_price: "1200", speed_mbps: 3, status: "ACTIVE",
    });
  });

  it("editing sends only what changed", () => {
    const orig = formFromPackage(stored);
    assert.deepEqual(packageBody(orig, orig), {});
    assert.deepEqual(packageBody({ ...orig, internet_price: "1300" }, orig), { internet_price: "1300" });
    assert.deepEqual(packageBody({ ...orig, status: "INACTIVE" }, orig), { status: "INACTIVE" });
  });

  it("clearing a price or the speed on purpose sends null", () => {
    const orig = formFromPackage(stored);
    assert.deepEqual(packageBody({ ...orig, internet_price: "", speed_mbps: "" }, orig), { internet_price: null, speed_mbps: null });
  });

  it("loads a stored package into the form without losing anything", () => {
    const f = formFromPackage(stored);
    assert.equal(f.display_name_ur, "اسٹار 3");
    assert.equal(f.speed_mbps, "3");
    assert.equal(f.internet_price, "1200.00");
    assert.equal(f.monthly_price, "");
  });
});

describe("areas", () => {
  it("needs a name", () => {
    assert.equal(areaProblem({ name: "Qadir Colony", name_ur: "", code: "" }), null);
    assert.match(areaProblem({ name: "  ", name_ur: "", code: "" })!, /name/);
  });
  it("sends only changes when editing", () => {
    const orig = { name: "Qadir Colony", name_ur: "", code: "" };
    assert.deepEqual(areaBody(orig, orig), {});
    assert.deepEqual(areaBody({ ...orig, name: "Qadir Town", name_ur: "قادر ٹاؤن" }, orig), { name: "Qadir Town", name_ur: "قادر ٹاؤن" });
    assert.deepEqual(areaBody({ name: "X", name_ur: "", code: "" }), { name: "X" });
    assert.deepEqual(areaBody({ ...orig, name_ur: "" }, { ...orig, name_ur: "پرانا" }), { name_ur: null });
  });
});
