import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  base: "./",                       // Electron file:// 加载需要相对 base
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
});
