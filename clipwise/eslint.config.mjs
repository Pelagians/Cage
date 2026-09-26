import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const config = [
  ...nextVitals,
  ...nextTs,
  {
    ignores: [".next/**", "node_modules/**", "data/**", "playwright-report/**", "test-results/**", "next-env.d.ts", "public/sw.js"],
  },
  {
    rules: {
      // Thumbnails come straight from YouTube's CDN; next/image optimisation adds nothing here.
      "@next/next/no-img-element": "off",
    },
  },
];

export default config;
