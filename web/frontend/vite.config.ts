import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В разработке фронтенд живёт на 5173 и обращается к серверу на 8000.
// В собранном виде его отдаёт сам сервер, и прокси не нужен.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});