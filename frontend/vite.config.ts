import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Em desenvolvimento o Vite encaminha /api para o backend (uvicorn na porta 8000).
export default defineConfig({
  plugins: [react()],
  // o editor de código (CodeMirror, ~630 kB) é carregado à parte, só quando se abre um robô Groovy
  build: { chunkSizeWarningLimit: 700 },
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
