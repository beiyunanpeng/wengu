import assert from "node:assert/strict";
import test from "node:test";

import { mistakesSubjectHref, reviewCta } from "../src/lib/dashboard.ts";
import { NAV } from "../src/lib/nav.ts";

test("主 CTA：到期为 0 换文案，但目标路由不变（不做禁用态）", () => {
  assert.deepEqual(reviewCta(0), {
    label: "今天没有到期复习",
    to: "/review",
  });
  assert.deepEqual(reviewCta(1), { label: "开始今日复习", to: "/review" });
  assert.deepEqual(reviewCta(37), { label: "开始今日复习", to: "/review" });
});

test("主 CTA 只返回 label + to：没有 disabled 之类的第三态", () => {
  for (const dueTotal of [0, 1, 37]) {
    assert.deepEqual(Object.keys(reviewCta(dueTotal)).sort(), ["label", "to"]);
  }
});

test("主 CTA 与学科卡的目标都是侧栏里真实存在的路由", () => {
  const targets = [reviewCta(0).to, new URL(mistakesSubjectHref("数学"), "http://local").pathname];
  for (const target of targets) {
    assert.ok(
      NAV.some((item) => item.to === target),
      `${target} 不在 NAV 中`,
    );
  }
});

test("学科卡深链：学科名走 subject 查询参数，中文百分号编码后可原样解回", () => {
  const href = mistakesSubjectHref("数学");
  assert.equal(href, "/mistakes?subject=%E6%95%B0%E5%AD%A6");
  const url = new URL(href, "http://local");
  assert.equal(url.pathname, "/mistakes");
  assert.equal(url.searchParams.get("subject"), "数学");
});

test("学科卡深链：未挂考点与含分隔符的学科名都不破坏 query 结构", () => {
  for (const subject of ["未挂考点", "英语", "道德与法治", "a&b=c", "x y+z", "100%"]) {
    const url = new URL(mistakesSubjectHref(subject), "http://local");
    assert.equal(url.pathname, "/mistakes");
    assert.equal(url.searchParams.get("subject"), subject);
    assert.equal([...url.searchParams.keys()].length, 1);
  }
});

test("学科卡深链不带多余参数：进入即只按学科筛选", () => {
  const url = new URL(mistakesSubjectHref("数学"), "http://local");
  assert.deepEqual([...url.searchParams.keys()], ["subject"]);
});