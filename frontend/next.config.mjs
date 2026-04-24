/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // `output: "standalone"` produces a self-contained .next/standalone
  // directory — only the files Next actually needs at runtime — so the
  // production Docker image can skip node_modules + .next altogether.
  // Docs: https://nextjs.org/docs/app/api-reference/next-config-js/output
  output: "standalone",
  // Backend URL — used by app/api/scan/route.ts to proxy.
  env: {
    NEXT_PUBLIC_BACKEND_URL: process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000",
  },
};

export default nextConfig;
