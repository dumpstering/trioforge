// Prints the HiGHS core version embedded in the pinned highs-js build:
//   highs-js-core <MAJOR.MINOR.PATCH>
// If the loaded library exposes no version, it first proves it can still solve
// a trivial LP and then prints:
//   highs-js-core unknown
import highsLoader from "highs";

const TRIVIAL_LP = `Maximize
 obj: x
Subject To
 c1: x <= 1
End
`;

function formatVersion(version) {
  if (version && [version.major, version.minor, version.patch].every(Number.isInteger)) {
    return `${version.major}.${version.minor}.${version.patch}`;
  }
  return undefined;
}

const highs = await highsLoader();
let version = formatVersion(highs.version);

if (version === undefined) {
  const solution = highs.solve(TRIVIAL_LP, { output_flag: false });
  if (solution.Status !== "Optimal") {
    console.error(`trivial LP did not solve to optimality: ${solution.Status}`);
    process.exit(1);
  }
  version = "unknown";
}

console.log(`highs-js-core ${version}`);
