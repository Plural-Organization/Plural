import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  // Keep generated assets working both at the standalone domain root and behind /app/.
  base: "./",
  plugins: [react()],
});
