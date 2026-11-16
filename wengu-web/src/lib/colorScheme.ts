// 主题切换的纯函数层：不 import @mantine、不碰 DOM，供 node --test 直接覆盖。
// 主题 = 每设备的呈现偏好（不是学习数据），只存 localStorage，绝不进 app-config / 数据库。
// 完整理由见 main.tsx 的 MantineProvider 注释；存储键与 Mantine 内置 colorSchemeManager 一致。

export const COLOR_SCHEME_STORAGE_KEY = "mantine-color-scheme-value";

export type ColorScheme = "light" | "dark";

export function nextColorScheme(current: ColorScheme): ColorScheme {
  return current === "dark" ? "light" : "dark";
}

// 按钮 aria-label / title 描述“点下去会切到哪个模式”，与当前模式相反。
export function colorSchemeToggleLabel(current: ColorScheme): string {
  return current === "dark" ? "切换到浅色模式" : "切换到深色模式";
}

export type ToggleIcon = "sun" | "moon";

// 图标同样表示“点下去要去的模式”：深色态显示太阳（去浅色），浅色态显示月亮（去深色）。
export function colorSchemeToggleIcon(current: ColorScheme): ToggleIcon {
  return current === "dark" ? "sun" : "moon";
}

// Dashboard 图表 token：把原先的硬编码 hex 映射到 Mantine 语义变量，随 light/dark 自适应。
// line/point：blue-filled 在 light=#228be6（与原值逐字一致）、dark=#1971c2。
// streakDone：teal-filled 在 light=#12b886（与原值逐字一致）、dark=#099268。
// grid/streakIdle：default-border 在 light=#ced4da、dark=#424242（原值 #e9ecef=gray-2，
//   语义边框 token 在浅色下略深一档，换取深色下不再是一块刺眼的浅灰方块）。
export const chartTokens = {
  grid: "var(--mantine-color-default-border)",
  line: "var(--mantine-color-blue-filled)",
  point: "var(--mantine-color-blue-filled)",
  streakDone: "var(--mantine-color-teal-filled)",
  streakIdle: "var(--mantine-color-default-border)",
} as const;