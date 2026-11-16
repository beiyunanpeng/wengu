import assert from "node:assert/strict";
import test from "node:test";

import {
  COLOR_SCHEME_STORAGE_KEY,
  chartTokens,
  colorSchemeToggleIcon,
  colorSchemeToggleLabel,
  nextColorScheme,
  type ColorScheme,
} from "../src/lib/colorScheme.ts";

const SCHEMES: ColorScheme[] = ["light", "dark"];

test("存储键钉死为 Mantine 内置 colorSchemeManager 的 localStorage 键（只存呈现偏好）", () => {
  assert.equal(COLOR_SCHEME_STORAGE_KEY, "mantine-color-scheme-value");
});

test("nextColorScheme 是 light↔dark 对合：切两次回到原点", () => {
  assert.equal(nextColorScheme("light"), "dark");
  assert.equal(nextColorScheme("dark"), "light");
  for (const scheme of SCHEMES) {
    assert.equal(nextColorScheme(nextColorScheme(scheme)), scheme);
  }
});

test("按钮 label 描述目标模式（与当前相反）：深色态提示切回浅色", () => {
  assert.equal(colorSchemeToggleLabel("light"), "切换到深色模式");
  assert.equal(colorSchemeToggleLabel("dark"), "切换到浅色模式");
});

test("按钮 icon 同样指向目标模式：浅色态月亮、深色态太阳", () => {
  assert.equal(colorSchemeToggleIcon("light"), "moon");
  assert.equal(colorSchemeToggleIcon("dark"), "sun");
});

test("label / icon / next 三者口径一致：都指向 nextColorScheme(current)", () => {
  for (const current of SCHEMES) {
    const target = nextColorScheme(current);
    assert.equal(
      colorSchemeToggleLabel(current),
      `切换到${target === "dark" ? "深色" : "浅色"}模式`,
    );
    assert.equal(colorSchemeToggleIcon(current), target === "dark" ? "moon" : "sun");
  }
});

test("chartTokens 五个值全是 Mantine 语义 var，没有任何硬编码 hex", () => {
  const values = Object.values(chartTokens);
  assert.equal(values.length, 5);
  for (const value of values) {
    assert.match(value, /^var\(--mantine-color-[a-z-]+\)$/);
    assert.ok(!value.includes("#"), `仍含硬编码 hex: ${value}`);
  }
});

test("chartTokens 映射钉死：grid/idle=default-border，line/point=blue-filled，done=teal-filled", () => {
  assert.deepEqual(chartTokens, {
    grid: "var(--mantine-color-default-border)",
    line: "var(--mantine-color-blue-filled)",
    point: "var(--mantine-color-blue-filled)",
    streakDone: "var(--mantine-color-teal-filled)",
    streakIdle: "var(--mantine-color-default-border)",
  });
});