const STATIC = process.env.NEXT_PUBLIC_STATIC === "1"; // GitHub Pages export
const ON_VERCEL = process.env.VERCEL === "1"; // Vercel managed build
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

/** @type {import('next').NextConfig} */
let nextConfig;

if (STATIC) {
  // GitHub Pages: fully static export, in-browser engine, repo-name base path.
  nextConfig = {
    reactStrictMode: true,
    output: "export",
    basePath,
    assetPrefix: basePath || undefined,
    images: { unoptimized: true },
    trailingSlash: true,
  };
} else if (ON_VERCEL) {
  // Vercel: let the platform manage output; engine mode, no backend proxy.
  nextConfig = { reactStrictMode: true, images: { unoptimized: true } };
} else {
  // Local / Docker: standalone server that proxies /api to the FastAPI backend.
  nextConfig = {
    reactStrictMode: true,
    output: "standalone",
    async rewrites() {
      const api = process.env.API_BASE_URL || "http://localhost:8080";
      return [{ source: "/api/:path*", destination: `${api}/:path*` }];
    },
  };
}

export default nextConfig;
