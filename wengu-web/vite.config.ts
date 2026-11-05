import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  return {
    plugins: [react()],
    server: {
      // 默认只绑回环：vite 的 /api 代理直通后端，绑 0.0.0.0 等于把整套系统开到局域网。
      // 局域网调试需显式：npm run dev -- --host 0.0.0.0（自担风险）；远程访问走 Tailscale。
      host: "127.0.0.1",
      port: 5173,
      proxy: {
        "/api": {
          target: env.WENGU_API_PROXY || "http://127.0.0.1:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
