import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep the development badge clear of the sidebar's account controls.
  devIndicators: { position: "bottom-right" },
};

export default nextConfig;
