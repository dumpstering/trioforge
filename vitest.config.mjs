// `npm test` runs the unit tests in tests-js/. The browser tests in tests-e2e/ belong to Playwright (`npm run e2e`) and must not be collected here.
import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    exclude: [...configDefaults.exclude, "tests-e2e/**"],
    // a test's own time limit: vitest's 5 s is hit by tests of 2 to 5 s when the machine is busy; a test that hangs still fails at 15 s (wall-clock bounds go through tests-js/timing.mjs)
    testTimeout: 15_000,
  },
});
