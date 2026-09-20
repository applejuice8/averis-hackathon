import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Vercel builds Next.js natively. API_URL is resolved by the route handler.
  // Optional standalone output is for local Docker only.
  ...(process.env.WEB_STANDALONE === "1" ? { output: "standalone" as const } : {}),
  outputFileTracingRoot: process.cwd(),
};
export default nextConfig;
