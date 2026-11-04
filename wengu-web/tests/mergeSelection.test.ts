import assert from "node:assert/strict";
import test from "node:test";

import {
  initialMergeSelection,
  isMergeSelectionReady,
} from "../src/pages/mergeSelection.ts";

test("错题只有一个 concept 时，打开弹窗也不预选源", () => {
  assert.deepEqual(initialMergeSelection([42]), {
    sourceId: null,
    targetId: null,
  });
});

test("错题有多个 concept 时，源与目标都为空", () => {
  assert.deepEqual(initialMergeSelection([1, 2, 3]), {
    sourceId: null,
    targetId: null,
  });
});

test("错题没有 concept 时，源与目标同样为空", () => {
  assert.deepEqual(initialMergeSelection([]), {
    sourceId: null,
    targetId: null,
  });
});

test("未同时选好源与目标：不发 preview、确认按钮禁用", () => {
  const cases = [
    { sourceId: null, targetId: null },
    { sourceId: "1", targetId: null },
    { sourceId: null, targetId: "2" },
    { sourceId: "1", targetId: "1" },
  ];
  for (const selection of cases) {
    assert.equal(
      isMergeSelectionReady(selection),
      false,
      `不应就绪：${JSON.stringify(selection)}`,
    );
  }
});

test("源与目标都选好且不同：才允许请求 preview 与确认", () => {
  assert.equal(
    isMergeSelectionReady({ sourceId: "1", targetId: "2" }),
    true,
  );
});
