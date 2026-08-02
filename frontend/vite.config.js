import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// 專案位於 WSL 檔案系統、但編輯器從 Windows 透過 \\wsl.localhost (9p) 寫入時，
// Linux 端收不到 inotify 事件，HMR 會完全失效（新檔案不會被載入）。
// 只在 WSL 內改用輪詢監看，原生 Linux / macOS 不受影響。
const isWSL = Boolean(process.env.WSL_DISTRO_NAME || process.env.WSL_INTEROP);

export default defineConfig({
  plugins: [react(), tailwindcss()],
  optimizeDeps: {
    exclude: ["maplibre-gl"],
  },
  server: {
    port: 3000,
    watch: isWSL ? { usePolling: true, interval: 400 } : undefined,
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
