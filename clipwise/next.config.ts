import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // better-sqlite3 is a native module; keep it out of the server bundle.
  serverExternalPackages: ["better-sqlite3"],
  poweredByHeader: false,
  // The floating dev-tools badge sits on top of the mobile bottom nav; errors still show.
  devIndicators: false,
  // Allow opening the dev server from a phone on the LAN (npm run dev:lan).
  allowedDevOrigins: ["192.168.*.*", "10.*.*.*", "172.16.*.*", "*.local"],
};

export default nextConfig;
