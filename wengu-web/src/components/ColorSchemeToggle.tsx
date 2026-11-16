import { ActionIcon, Tooltip, useMantineColorScheme } from "@mantine/core";

import {
  colorSchemeToggleIcon,
  colorSchemeToggleLabel,
  type ColorScheme,
} from "../lib/colorScheme";

// 内联 SVG：package.json 没有图标库，本票禁止为暗色引入新依赖，故手绘日/月。
// stroke=currentColor 跟随主题文字色，light/dark 下都自动可读。
function SunIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

export default function ColorSchemeToggle() {
  const { colorScheme, toggleColorScheme } = useMantineColorScheme();
  // useMantineColorScheme 的类型含 "auto"；本应用 defaultColorScheme="light" 且从不写 auto，
  // 这里把非 dark 一律归一为 light，纯函数 label/icon 只接受 light|dark。
  const current: ColorScheme = colorScheme === "dark" ? "dark" : "light";
  const label = colorSchemeToggleLabel(current);
  const icon = colorSchemeToggleIcon(current);

  return (
    <Tooltip label={label} position="bottom-end" openDelay={300}>
      <ActionIcon
        variant="subtle"
        color="gray"
        size="lg"
        radius="xl"
        aria-label={label}
        title={label}
        onClick={() => toggleColorScheme()}
      >
        {icon === "sun" ? <SunIcon /> : <MoonIcon />}
      </ActionIcon>
    </Tooltip>
  );
}