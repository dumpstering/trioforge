// Real-browser checks (Chromium) of the built site, served by `wrangler pages dev` so the production headers apply.
//
//   npm run e2e                                    the whole suite; it builds the site and starts the preview itself
//   npm run e2e -- --project=phone-dark -g axe     one view, some tests
//   TRIOFORGE_RESULTS=build/results npm run e2e    against real results instead of the synthetic fixture
//
// A project is one of the four views the checks run in: a 1280 px or a 360 px wide window, with the system in light or in dark
// mode. A test whose title has @once does not depend on the view and runs once, in the project "once".
//
// The browser comes from `npx playwright install chromium`.

import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.TRIOFORGE_PREVIEW_PORT ?? 8788);
const ORIGIN = `http://127.0.0.1:${PORT}`;

const WINDOWS = { desktop: { width: 1280, height: 900 }, phone: { width: 360, height: 740 } };
const matrix = Object.entries(WINDOWS).flatMap(([size, viewport]) =>
  ["light", "dark"].map((colorScheme) => ({
    name: `${size}-${colorScheme}`,
    grepInvert: /@once/,
    use: { ...devices["Desktop Chrome"], viewport, colorScheme },
  })),
);

export default defineConfig({
  testDir: "tests-e2e",
  testMatch: "*.spec.mjs",
  // everything the run writes (failure traces, screenshots) stays under build/, which git ignores
  outputDir: "build/e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  // a flaky test is a finding, not something to retry away
  retries: 0,
  workers: process.env.CI ? 2 : 6,
  timeout: 30_000,
  expect: { timeout: 7_000 },
  reporter: [["list"]],
  use: {
    baseURL: ORIGIN,
    locale: "en-US",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    ...matrix,
    { name: "once", grep: /@once/, use: { ...devices["Desktop Chrome"], viewport: WINDOWS.desktop, colorScheme: "light" } },
  ],
  webServer: {
    command: "node scripts/preview.mjs",
    url: `${ORIGIN}/`,
    // a server left over from an earlier run would hide a broken build, so an occupied port is an error
    reuseExistingServer: false,
    timeout: 180_000,
    env: { TRIOFORGE_PREVIEW_PORT: String(PORT) },
  },
});
