/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Backend URL — used by app/api/scan/route.ts to proxy.
  env: {
    NEXT_PUBLIC_BACKEND_URL: process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000",
  },
};

export default nextConfig;
