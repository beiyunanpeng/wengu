import { createTheme } from "@mantine/core";

// 最小主题锚点：只确认主色为 blue（与看板图表既有的蓝一致），不重设圆角/字体/全站配色。
// light/dark 的具体色值全部交给 Mantine 内置语义变量（primaryShade 默认 light=6 / dark=8），
// 这里不覆盖任何色值，避免“借主题之名换全站配色”。
export const theme = createTheme({
  primaryColor: "blue",
});