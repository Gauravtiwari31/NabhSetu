/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000";

function spaAwareProxy() {
  return {
    target: apiTarget,
    bypass(req: { headers: { accept?: string }; url?: string }) {
      if (req.headers.accept?.includes("text/html")) {
        return "/index.html";
      }
      return undefined;
    },
  };
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/health": apiTarget,
      "/sources": spaAwareProxy(),
      "/collection-jobs": apiTarget,
      "/fares": spaAwareProxy(),
      "/v1": apiTarget,
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 5173,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/setupTests.ts",
  },
});
