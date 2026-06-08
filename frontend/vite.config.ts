import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/generate": "http://localhost:8000",
      "/review": "http://localhost:8000",
      "/ops": "http://localhost:8000",
      "/export": "http://localhost:8000",
      "/healthz": "http://localhost:8000",
    },
  },
});
