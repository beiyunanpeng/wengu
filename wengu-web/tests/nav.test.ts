import assert from "node:assert/strict";
import test from "node:test";

import { groupNavItems, isNavActive, NAV } from "../src/lib/nav.ts";

test("NAV 共 12 项：9 枚孩子可见 + 3 枚家长专属", () => {
  assert.equal(NAV.length, 12);
  assert.equal(NAV.filter((item) => !item.parentOnly).length, 9);
  assert.equal(NAV.filter((item) => item.parentOnly).length, 3);
});

test("家长未解锁：只有孩子组 9 枚，家长组整组不渲染", () => {
  const groups = groupNavItems(NAV, false);
  assert.deepEqual(
    groups.map((group) => [group.key, group.title, group.items.length]),
    [["student", "孩子组", 9]],
  );
  assert.deepEqual(
    groups[0].items.map((item) => item.to),
    ["/dashboard", "/import", "/intake", "/mistakes", "/review", "/recitations", "/schedule", "/review-calendar", "/records"],
  );
});

test("家长已解锁：孩子组 9 枚 + 家长组 3 枚，顺序与原 NAV 一致", () => {
  const groups = groupNavItems(NAV, true);
  assert.deepEqual(
    groups.map((group) => [group.key, group.title, group.items.length]),
    [
      ["student", "孩子组", 9],
      ["parent", "家长组", 3],
    ],
  );
  assert.deepEqual(
    groups[1].items.map((item) => item.to),
    ["/bank", "/local-seed", "/backup"],
  );
});

test("分组不修改入参：NAV 在多次调用后保持原样", () => {
  const before = JSON.stringify(NAV);
  groupNavItems(NAV, false);
  groupNavItems(NAV, true);
  assert.equal(JSON.stringify(NAV), before);
});

test("当前路径高亮：完全匹配与子路径匹配为真，前缀相近为假", () => {
  assert.equal(isNavActive("/mistakes", "/mistakes"), true);
  assert.equal(isNavActive("/mistakes/42", "/mistakes"), true);
  assert.equal(isNavActive("/mistakes-archive", "/mistakes"), false);
  assert.equal(isNavActive("/dashboard", "/mistakes"), false);
});

test("复习日历高亮独立：/review-calendar 不点亮 /review，反之亦然", () => {
  assert.equal(isNavActive("/review-calendar", "/review-calendar"), true);
  assert.equal(isNavActive("/review-calendar", "/review"), false);
  assert.equal(isNavActive("/review", "/review-calendar"), false);
  assert.equal(isNavActive("/review", "/review"), true);
});
