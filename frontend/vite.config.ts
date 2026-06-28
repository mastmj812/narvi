import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the narvi backend (uvicorn on :8078), so the
// frontend uses same-origin /api/* URLs — including the pmtiles basemap, which
// MapLibre range-requests.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5176,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8078",
        changeOrigin: true,
      },
    },
  },
});
