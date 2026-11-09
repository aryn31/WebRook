import type { NextConfig } from "next";

// NOTE: rewrites are evaluated at BUILD time when using `output: "standalone"`,
// so BACKEND_URL must be set when running `next build` (the Dockerfile passes it
// as a build arg). In docker-compose the backend is reachable at http://api:8000.
const backendUrl = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  // Only the customer portal may be shown inside another site (it's made to be embedded). Every other page refuses
  // to be framed, so no site can trick a logged-in user into clicking dashboard buttons inside a hidden frame.
  async headers() {
    return [
      { source: "/portal", headers: [{ key: "Content-Security-Policy", value: "frame-ancestors *" }] },
      {
        source: "/((?!portal$).*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
        ],
      },
    ];
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/:path*` }];
  },
};

export default nextConfig;
