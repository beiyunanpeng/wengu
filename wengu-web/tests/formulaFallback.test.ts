import assert from "node:assert/strict";
import test from "node:test";

import { ApiError, isFormulaFallback } from "../src/api/client.ts";

function fallbackError(): ApiError {
  return new ApiError(422, "公式题：系统未自动判定，请自评或家长核对", {
    detail: {
      message: "公式题：系统未自动判定，请自评或家长核对",
      reason: "formula_fallback",
    },
  });
}

test("422 + detail.reason=formula_fallback：识别为降级信号", () => {
  assert.equal(isFormulaFallback(fallbackError()), true);
});

test("422 + 其它 reason：不是降级信号", () => {
  const error = new ApiError(422, "无法自动判分", {
    detail: { message: "无法自动判分", reason: "uncertain" },
  });
  assert.equal(isFormulaFallback(error), false);
});

test("422 + detail 为字符串：不是降级信号", () => {
  assert.equal(isFormulaFallback(new ApiError(422, "校验失败", "校验失败")), false);
});

test("非 422（400）即便 reason 匹配：不是降级信号", () => {
  const error = new ApiError(400, "公式题", {
    detail: { reason: "formula_fallback" },
  });
  assert.equal(isFormulaFallback(error), false);
});

test("普通 Error：不是降级信号", () => {
  assert.equal(isFormulaFallback(new Error("formula_fallback")), false);
});

test("null / undefined：不是降级信号", () => {
  assert.equal(isFormulaFallback(null), false);
  assert.equal(isFormulaFallback(undefined), false);
});