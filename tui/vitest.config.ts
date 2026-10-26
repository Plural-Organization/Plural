import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: { ink: fileURLToPath(new URL("./node_modules/ink/build/index.js", import.meta.url)) },
  },
  test: { server: { deps: { inline: ["ink-testing-library"] } } },
});
