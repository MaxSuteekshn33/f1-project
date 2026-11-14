/** @type {import('next').NextConfig} */
const backend = process.env.BACKEND_URL || "http://localhost:8000";
export default {
  reactStrictMode: true,
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};
