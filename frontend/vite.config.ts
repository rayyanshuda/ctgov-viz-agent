import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // During `npm run dev`, forward API calls to the FastAPI server so there is no CORS to deal with
    proxy: { "/api": "http://localhost:8000" },
  },
});
