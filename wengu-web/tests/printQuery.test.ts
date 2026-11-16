import assert from "node:assert/strict";
import test from "node:test";

import {
  buildPrintMistakesQuery,
  cleanPrintDate,
  parsePrintQuery,
  printDocMeta,
  printLabels,
  printToolbarSummary,
} from "../src/lib/printQuery.ts";

const q = (search: string) => parsePrintQuery(new URLSearchParams(search));

test("parsePrintQuery 解析五个参数键，subject 在参数集合内（依赖数组纯函数层）", () => {
  const query = q(
    "subject=数学&category_id=cnm_001&error_cause=concept_unclear&from=2026-11-01&to=2026-11-16",
  );
  assert.deepEqual(Object.keys(query), [
    "subject",
    "categoryId",
    "errorCause",
    "from",
    "to",
  ]);
  assert.equal(query.subject, "数学");
  assert.equal(query.categoryId, "cnm_001");
  assert.equal(query.errorCause, "concept_unclear");
  assert.equal(query.from, "2026-11-01");
  assert.equal(query.to, "2026-11-16");
});

test("缺省参数全部为 null", () => {
  assert.deepEqual(q(""), {
    subject: null,
    categoryId: null,
    errorCause: null,
    from: null,
    to: null,
  });
});

test("cleanPrintDate 只认 YYYY-MM-DD 格式，其余清洗为 null", () => {
  assert.equal(cleanPrintDate("2026-11-16"), "2026-11-16");
  assert.equal(cleanPrintDate("2026/11/16"), null);
  assert.equal(cleanPrintDate("20261116"), null);
  assert.equal(cleanPrintDate(""), null);
  assert.equal(cleanPrintDate(null), null);
});

// ---- 三种筛选组合各一条，标签集合与实际参数一一对应（§19-L 纪律②，不以一类代全部）----

test("组合① subject 单独：学科=数学、知识点必须=全部知识点、错因=全部错因、日期=全部日期", () => {
  const labels = printLabels(q("subject=数学"), null, null);
  assert.deepEqual(labels, {
    subject: "数学",
    category: "全部知识点",
    error: "全部错因",
    date: "全部日期",
  });
  assert.equal(
    printToolbarSummary(labels, 6),
    "数学 · 全部知识点 · 全部错因 · 全部日期 · 6 道",
  );
  assert.equal(
    printDocMeta(labels, 2),
    "学科：数学 · 知识点：全部知识点 · 错因：全部错因 · 日期：全部日期 · 共 2 个知识点页组",
  );
});

test("组合② subject+category_id：学科=数学、知识点=一元一次方程（解析名）、其余缺省", () => {
  const labels = printLabels(q("subject=数学&category_id=cnm_001"), "一元一次方程", null);
  assert.deepEqual(labels, {
    subject: "数学",
    category: "一元一次方程",
    error: "全部错因",
    date: "全部日期",
  });
  const meta = printDocMeta(labels, 1);
  assert.ok(meta.includes("学科：数学"));
  assert.ok(meta.includes("知识点：一元一次方程"));
});

test("组合③ subject+error_cause：学科=数学、错因=概念不清（解析名）、知识点=全部知识点", () => {
  const labels = printLabels(q("subject=数学&error_cause=concept_unclear"), null, "概念不清");
  assert.deepEqual(labels, {
    subject: "数学",
    category: "全部知识点",
    error: "概念不清",
    date: "全部日期",
  });
  const meta = printDocMeta(labels, 1);
  assert.ok(meta.includes("学科：数学"));
  assert.ok(meta.includes("错因：概念不清"));
});

// ---- 导出按钮转发 + 中文百分号编码可原样解回 ----

test("导出 URL 转发 subject：含 subject 参数且中文百分号编码可原样解回", () => {
  const query = buildPrintMistakesQuery({ subject: "数学" });
  assert.ok(query.includes("subject=%E6%95%B0%E5%AD%A6"));
  assert.equal(new URLSearchParams(query).get("subject"), "数学");
});

test("导出 URL 同段转发 category_id/error_cause/subject 三键，绝不泄露 q/mastery_state", () => {
  const query = buildPrintMistakesQuery({
    subject: "数学",
    categoryId: "cnm_001",
    errorCause: "concept_unclear",
  });
  const parsed = new URLSearchParams(query);
  assert.equal(parsed.get("subject"), "数学");
  assert.equal(parsed.get("category_id"), "cnm_001");
  assert.equal(parsed.get("error_cause"), "concept_unclear");
  assert.deepEqual([...parsed.keys()].sort(), [
    "category_id",
    "error_cause",
    "subject",
  ]);
  assert.equal(parsed.get("q"), null);
  assert.equal(parsed.get("mastery_state"), null);
});

test("导出 URL 空筛选 → 空串（导航不带 ?）", () => {
  assert.equal(buildPrintMistakesQuery({}), "");
  assert.equal(
    buildPrintMistakesQuery({ subject: null, categoryId: null, errorCause: null }),
    "",
  );
});

// ---- 空态不撒谎 ----

test("空态：某学科 0 道在册，学科标签仍为该学科 + 0 道，不回落全部学科", () => {
  const labels = printLabels(q("subject=英语"), null, null);
  assert.equal(labels.subject, "英语");
  assert.notEqual(labels.subject, "全部学科");
  assert.equal(labels.category, "全部知识点");
  const toolbar = printToolbarSummary(labels, 0);
  assert.ok(toolbar.startsWith("英语"));
  assert.ok(toolbar.endsWith("0 道"));
  const meta = printDocMeta(labels, 0);
  assert.ok(meta.includes("学科：英语"));
  assert.ok(!meta.includes("个知识点页组"));
});

// ---- 缺省值钉死：右侧用字面串，不引用被测常量（§19-L 纪律①）----

test("四标签缺省值钉死为字面串", () => {
  assert.deepEqual(printLabels(q(""), null, null), {
    subject: "全部学科",
    category: "全部知识点",
    error: "全部错因",
    date: "全部日期",
  });
});

// ---- 学科标签两处都要有：文档头与工具栏各自独立断言（变异②只摘文档头）----

test("文档头 print-meta 带学科前缀标签", () => {
  const labels = printLabels(q("subject=数学"), null, null);
  assert.ok(printDocMeta(labels, 1).startsWith("学科：数学"));
});

test("工具栏摘要带学科标签（裸值，无前缀）", () => {
  const labels = printLabels(q("subject=数学"), null, null);
  assert.ok(printToolbarSummary(labels, 1).startsWith("数学 · "));
});

// ---- 解析名缺失回退、日期标签 ----

test("知识点解析名缺失回退 category_id 本身；错因解析名缺失回退 error_cause 键", () => {
  const labels = printLabels(q("category_id=cnm_001&error_cause=concept_unclear"), null, null);
  assert.equal(labels.category, "cnm_001");
  assert.equal(labels.error, "concept_unclear");
});

test("日期标签：from/to 单边与双边、缺省全部日期", () => {
  assert.equal(printLabels(q("from=2026-11-01"), null, null).date, "2026-11-01 至 今天");
  assert.equal(printLabels(q("to=2026-11-16"), null, null).date, "最早 至 2026-11-16");
  assert.equal(
    printLabels(q("from=2026-11-01&to=2026-11-16"), null, null).date,
    "2026-11-01 至 2026-11-16",
  );
  assert.equal(printLabels(q(""), null, null).date, "全部日期");
});