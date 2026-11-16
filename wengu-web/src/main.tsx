import "@mantine/core/styles.css";
import "katex/dist/katex.min.css";
import { MantineProvider } from "@mantine/core";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { theme } from "./theme";

const container = document.getElementById("root");
if (!container) {
  throw new Error("root element is missing");
}

createRoot(container).render(
  <StrictMode>
    {/*
      主题（浅色/深色）是“每设备的呈现偏好”，不是学习数据：只走 Mantine 内置
      colorSchemeManager（localStorage 键 mantine-color-scheme-value），绝不进
      app-config / 数据库。原因：app/api/config.py:24 把 require_parent 挂在 router 级，
      连 GET /api/config 都要家长 PIN——把主题放进去，孩子连自己设备的外观都读不到、
      改不了，且会把 UI 偏好伪装成业务配置。本票是“localStorage 只准存呈现偏好、
      不准存业务/学习数据”的边界样本，不是放宽数据入库的先例。
      defaultColorScheme="light" 只管首次默认；已存深色由 index.html 的首屏脚本预设，
      避免刷新闪白。
    */}
    <MantineProvider theme={theme} defaultColorScheme="light">
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </MantineProvider>
  </StrictMode>,
);
