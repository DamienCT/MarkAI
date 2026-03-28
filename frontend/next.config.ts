import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "*.hstgr.cloud",
      },
    ],
    unoptimized: true,
  },
};

export default nextConfig;
