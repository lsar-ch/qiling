import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 开发模式：/api 转发到本地 ai-service，生产由 ai-service 托管 dist
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8736",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
