import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const root = dirname(fileURLToPath(import.meta.url));

// `base: "./"` keeps asset URLs relative so the bundle works when Streamlit
// serves it from an arbitrary component mount path.
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    outDir: "build",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: resolve(root, "index.html"),
        dev: resolve(root, "dev.html"),
      },
    },
  },
  server: {
    port: 3001,
    strictPort: true,
  },
});
