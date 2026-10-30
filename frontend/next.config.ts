import type { NextConfig } from "next";

// NOTE: rewrites are evaluated at BUILD time when using `output: "standalone"`,
// so BACKEND_URL must be set when running `next build` (the Dockerfile passes it
// as a build arg). In docker-compose the backend is reachable at http://api:8000.
const backendUrl = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/:path*` }];
  },
};

export default nextConfig;
