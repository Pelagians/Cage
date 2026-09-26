import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";

const PORT = 3100;
// Use a pre-installed Chromium when available (e.g. CI images), otherwise Playwright's own.
const executablePath = process.env.CHROMIUM_PATH || (fs.existsSync("/opt/pw-browsers/chromium") ? "/opt/pw-browsers/chromium" : undefined);

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    ...devices["iPhone 13"],
    browserName: "chromium",
    launchOptions: executablePath ? { executablePath } : {},
    trace: "retain-on-failure",
  },
  webServer: {
    // Separate database so tests never touch your real data.
    command: `rm -f data/e2e.db data/e2e.db-wal data/e2e.db-shm && CLIPWISE_DB_PATH=./data/e2e.db npx next dev -H 127.0.0.1 -p ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/feed?limit=1`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
