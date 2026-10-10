import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { DEFAULT_FRAME, axisTicks, barLayout, groupedLayout, labelStep, niceMax, percentOfMax, shortNumber } from "../src/lib/charts";

describe("chart axis", () => {
  it("rounds the top of the axis up to a tidy number", () => {
    assert.equal(niceMax(0), 1);
    assert.equal(niceMax(-5), 1);
    assert.equal(niceMax(NaN), 1);
    assert.equal(niceMax(1), 1);
    assert.equal(niceMax(1.4), 2);
    assert.equal(niceMax(2.3), 2.5);
    assert.equal(niceMax(3), 5);
    assert.equal(niceMax(7), 10);
    assert.equal(niceMax(123_456), 200_000);
    assert.equal(niceMax(1_080_750), 2_000_000);
    assert.equal(niceMax(80), 100);
  });
  it("makes evenly spaced ticks from zero", () => {
    assert.deepEqual(axisTicks(1_080_750), [0, 500_000, 1_000_000, 1_500_000, 2_000_000]);
    assert.deepEqual(axisTicks(0), [0, 0.25, 0.5, 0.75, 1]);
  });
  it("shortens big numbers for labels", () => {
    assert.equal(shortNumber(0), "0");
    assert.equal(shortNumber(800), "800");
    assert.equal(shortNumber(1500), "1.5K");
    assert.equal(shortNumber(450_000), "450K");
    assert.equal(shortNumber(1_250_000), "1.3M");
    assert.equal(shortNumber(2_000_000), "2M");
  });
  it("limits the number of x labels", () => {
    assert.equal(labelStep(12, 12), 1);
    assert.equal(labelStep(30, 8), 4);
    assert.equal(labelStep(0, 8), 1);
    assert.equal(labelStep(5, 0), 5);
  });
});

describe("bar layout", () => {
  const plotH = DEFAULT_FRAME.height - DEFAULT_FRAME.top - DEFAULT_FRAME.bottom;
  it("scales bars against the axis top and keeps them inside the plot", () => {
    const { bars, max } = barLayout([0, 50, 100]);
    assert.equal(max, 100);
    assert.equal(bars[0].h, 0);
    assert.equal(bars[2].h, plotH);
    assert.ok(Math.abs(bars[1].h - plotH / 2) < 1e-9);
    for (const b of bars) {
      assert.ok(b.x >= DEFAULT_FRAME.left && b.x + b.w <= DEFAULT_FRAME.width - DEFAULT_FRAME.right + 1e-6);
      assert.ok(b.y >= DEFAULT_FRAME.top - 1e-9 && b.y + b.h <= DEFAULT_FRAME.top + plotH + 1e-9);
    }
  });
  it("never lets a small positive value vanish", () => {
    const { bars } = barLayout([1, 1_000_000]);
    assert.ok(bars[0].h >= 1);
  });
  it("copes with no data and with all zeros", () => {
    assert.deepEqual(barLayout([]).bars, []);
    const zero = barLayout([0, 0, 0]);
    assert.ok(zero.bars.every((b) => b.h === 0));
    assert.equal(zero.max, 1);
  });
  it("lays bars out left to right without overlap", () => {
    const { bars } = barLayout(Array.from({ length: 12 }, (_, i) => i + 1));
    for (let i = 1; i < bars.length; i++) assert.ok(bars[i].x >= bars[i - 1].x + bars[i - 1].w - 1e-9);
  });
});

describe("grouped layout", () => {
  it("puts the second bar beside the first with the same scale", () => {
    const g = groupedLayout([100, 0], [50, 100]);
    assert.equal(g.max, 100);
    assert.equal(g.first.length, 2);
    assert.ok(g.second[0].x >= g.first[0].x + g.first[0].w - 1e-9);
    assert.ok(g.first[0].h > g.second[0].h && g.second[1].h > g.first[1].h);
  });
  it("handles uneven or empty input", () => {
    assert.equal(groupedLayout([], []).first.length, 0);
    assert.equal(groupedLayout([5], []).second.length, 0);
  });
});

describe("horizontal bars", () => {
  it("is a percentage of the largest, at least 1 when there is something", () => {
    assert.equal(percentOfMax(50, 100), 50);
    assert.equal(percentOfMax(100, 100), 100);
    assert.equal(percentOfMax(0.1, 100), 1);
    assert.equal(percentOfMax(0, 100), 0);
    assert.equal(percentOfMax(5, 0), 0);
    assert.equal(percentOfMax(500, 100), 100);
  });
});
