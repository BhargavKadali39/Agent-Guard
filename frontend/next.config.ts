import type { NextConfig } from "next";

// The browser talks to same-origin /api/*; Next.js proxies it to the backend so no CORS
// configuration is needed in local development or in docker-compose.
// 127.0.0.1 rather than "localhost": on Windows, Node may resolve localhost to ::1 (IPv6)
// while uvicorn listens on IPv4 only.
const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${apiInternalUrl}/api/:path*` },
      { source: "/backend-docs", destination: `${apiInternalUrl}/docs` },
      { source: "/openapi.json", destination: `${apiInternalUrl}/openapi.json` },
    ];
  },
};

export default nextConfig;
