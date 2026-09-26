// Renders public/icons/icon.svg to the PNG sizes the PWA manifest needs.
// Usage: node scripts/gen-icons.mjs  (uses Playwright's Chromium, a dev dependency)
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const dir = path.resolve("public/icons");
const svg = fs.readFileSync(path.join(dir, "icon.svg"), "utf8");
const targets = [
  { file: "icon-192.png", size: 192, pad: 0 },
  { file: "icon-512.png", size: 512, pad: 0 },
  { file: "apple-touch-icon.png", size: 180, pad: 0, square: true },
  { file: "icon-maskable-512.png", size: 512, pad: 0.12, square: true },
];

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await browser.newPage();
for (const t of targets) {
  const inner = Math.round(t.size * (1 - t.pad * 2));
  await page.setViewportSize({ width: t.size, height: t.size });
  await page.setContent(
    `<html><body style="margin:0;background:${t.square ? "#0b0b0d" : "transparent"};display:grid;place-items:center;width:${t.size}px;height:${t.size}px">
      <div style="width:${inner}px;height:${inner}px">${svg.replace("<svg ", `<svg width="${inner}" height="${inner}" `)}</div></body></html>`,
  );
  await page.screenshot({ path: path.join(dir, t.file), omitBackground: !t.square });
  console.log("wrote", t.file);
}
await browser.close();
