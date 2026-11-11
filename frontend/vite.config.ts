import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  if (env.VITE_CHATBI_PUBLIC_DEMO === "true" && !env.VITE_CHATBI_API_BASE_URL) {
    throw new Error("Set VITE_CHATBI_API_BASE_URL to the deployed API origin before building the public demo.");
  }

  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
    },
  };
});
