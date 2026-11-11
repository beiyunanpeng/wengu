import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_FOCUS_MINUTES,
  MAX_FOCUS_MINUTES,
  MIN_FOCUS_MINUTES,
  focusMinutes,
} from "../src/lib/pomodoro.ts";

test("时长档位：默认 25，可选范围 5–120", () => {
  assert.equal(MIN_FOCUS_MINUTES, 5);
  assert.equal(MAX_FOCUS_MINUTES, 120);
  assert.equal(DEFAULT_FOCUS_MINUTES, 25);
  assert.ok(DEFAULT_FOCUS_MINUTES >= MIN_FOCUS_MINUTES);
  assert.ok(DEFAULT_FOCUS_MINUTES <= MAX_FOCUS_MINUTES);
});

test("跑满整轮：剩余 0 秒按计划时长记", () => {
  assert.equal(focusMinutes(25, 0), 25);
  assert.equal(focusMinutes(5, 0), 5);
  assert.equal(focusMinutes(120, 0), 120);
});

test("提前完成：45 分钟的轮次做了 12 分钟就记 12", () => {
  assert.equal(focusMinutes(45, 45 * 60 - 12 * 60), 12);
  assert.equal(focusMinutes(25, 25 * 60 - 20 * 60), 20);
});

test("不足下限：刚开 10 秒就完成也记 5，不会被服务端 422", () => {
  assert.equal(focusMinutes(25, 25 * 60 - 10), 5);
  assert.equal(focusMinutes(25, 25 * 60), 5);
  assert.equal(focusMinutes(5, 5 * 60 - 30), 5);
});

test("四舍五入到分钟：1 分 30 秒 → 2，但仍受下限约束", () => {
  assert.equal(focusMinutes(60, 60 * 60 - 90), 5);
  assert.equal(focusMinutes(60, 60 * 60 - 8 * 60 - 30), 9);
  assert.equal(focusMinutes(60, 60 * 60 - 8 * 60 - 29), 8);
});

test("结果永远落在服务端严格区间内（5–120）", () => {
  for (const planned of [5, 25, 45, 120]) {
    for (const remaining of [0, 1, 59, 60, 300, planned * 60]) {
      const minutes = focusMinutes(planned, remaining);
      assert.ok(Number.isInteger(minutes));
      assert.ok(minutes >= MIN_FOCUS_MINUTES && minutes <= MAX_FOCUS_MINUTES);
      assert.ok(minutes <= planned);
    }
  }
});