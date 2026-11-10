const STATIC = process.env.NEXT_PUBLIC_STATIC === "1";
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // GitHub Pages: fully static export, no server. basePath = repo name.
  ...(STATIC
    ? {
        output: "export",
        basePath,
        assetPrefix: basePath || undefined,
        images: { unoptimized: true },
        trailingSlash: true,
      }
    : {
        output: "standalone",
        async rewrites() {
          const api = process.env.API_BASE_URL || "http://localhost:8080";
          return [{ source: "/api/:path*", destination: `${api}/:path*` }];
        },
      }),
};
export default nextConfig;
