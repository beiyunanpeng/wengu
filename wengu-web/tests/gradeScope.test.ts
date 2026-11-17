import assert from "node:assert/strict";
import test from "node:test";

import { GRADE_SCOPE_OPTIONS, parseGradeScope } from "../src/setup/gradeScope.ts";

test("三档选项钉死字面：6=小学 / 9=初中 / 16=高中（顺序也是契约）", () => {
  assert.deepEqual(
    GRADE_SCOPE_OPTIONS.map((option) => [option.value, option.label]),
    [
      [6, "小学"],
      [9, "初中"],
      [16, "高中"],
    ],
  );
});

test("parseGradeScope 只接受三档字面串，其余一律 null", () => {
  assert.equal(parseGradeScope("6"), 6);
  assert.equal(parseGradeScope("9"), 9);
  assert.equal(parseGradeScope("16"), 16);
  for (const raw of ["7", "0", "", "9.0", "six", " 9", "16 "]) {
    assert.equal(parseGradeScope(raw), null);
  }
});