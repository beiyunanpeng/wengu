import assert from "node:assert/strict";
import test from "node:test";

import type { DictationSheetDetail } from "../src/api/types.ts";
import { buildPrintRows } from "../src/pages/dictationPrint.ts";

function detail(audioRef: string | null): DictationSheetDetail {
  return {
    sheet: {
      id: 7,
      created_on: "2026-11-20",
      created_by: "parent",
      subject: "英语",
      unit: "U1",
      item_ids: [11, 12],
      status: "open",
      recorded_on: null,
      audio_ref: audioRef,
    },
    items: [
      { item_id: 11, prompt: "苹果", unit: "U1", status: "active" },
      { item_id: 12, prompt: "香蕉", unit: null, status: "retired" },
    ],
    missing_item_ids: [],
  };
}

test("挂音频的听写卷：行内不含 prompt 字段（定案⑥，防退化成抄写）", () => {
  assert.deepEqual(buildPrintRows(detail("u1.mp3")), [
    { item_id: 11, unit: "U1", status: "active" },
    { item_id: 12, unit: null, status: "retired" },
  ]);
});

test("不挂音频的默写卷：行内含 prompt 字段", () => {
  assert.deepEqual(buildPrintRows(detail(null)), [
    { item_id: 11, unit: "U1", status: "active", prompt: "苹果" },
    { item_id: 12, unit: null, status: "retired", prompt: "香蕉" },
  ]);
});

test("听写卷逐行确认 prompt 键不存在（deepEqual 之外的显式键检查）", () => {
  for (const row of buildPrintRows(detail("u1.mp3"))) {
    assert.equal("prompt" in row, false);
  }
});

test("空卷两侧都返回空数组", () => {
  const empty = detail("u1.mp3");
  empty.items = [];
  assert.deepEqual(buildPrintRows(empty), []);
  empty.sheet.audio_ref = null;
  assert.deepEqual(buildPrintRows(empty), []);
});