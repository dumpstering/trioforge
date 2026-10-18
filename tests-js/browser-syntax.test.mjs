// The files of the home picker and of the 404 page are written for Safari 15.0 and ES2021: the syntax is checked by lowering them for that target, and the features that a lowering
// cannot supply (a method or a pattern a browser of that age does not have) are looked for in the text. The bundle target of the build is newer (it only decides what esbuild rewrites), so
// nothing else would notice a call to `.at()` until a visitor on an older phone met it.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { transformSync } from "esbuild";
import { describe, expect, it } from "vitest";

const STATIC = resolve(dirname(fileURLToPath(import.meta.url)), "../pipeline/trioforge/site/static");
const FILES = ["canonical.js", "notfound.js", "picker.js"];

/** What a browser of that age does not have, as patterns in the text of a file (comments and strings are taken out first). */
const TOO_NEW = [
  [/\.at\(/, "Array.prototype.at, String.prototype.at (ES2022)"],
  [/\bObject\.hasOwn\(/, "Object.hasOwn (ES2022)"],
  [/\bstructuredClone\(/, "structuredClone"],
  [/\(\?<[=!]/, "a lookbehind in a regular expression (Safari 16.4)"],
  [/\.(?:findLast|findLastIndex)\(/, "findLast (ES2023)"],
  [/\.(?:toSorted|toReversed|toSpliced)\(/, "toSorted, toReversed, toSpliced (ES2023)"],
  [/\.(?:isWellFormed|toWellFormed)\(/, "isWellFormed (ES2024)"],
  [/\bArray\.fromAsync\b|\bObject\.groupBy\b|\bMap\.groupBy\b|\bPromise\.withResolvers\b/, "ES2024 statics"],
  [/\bstatic\s*\{/, "a static block of a class (ES2022)"],
  [/(?:this|\w)\.#\w+/, "a private field (ES2022)"],
  [/^\s*#\w+\s*[=;(]/m, "a private member of a class (ES2022)"],
  [/^\s*await\s/m, "an await at the top of a module (ES2022)"],
  [/\bnew Error\([^)]*,\s*\{\s*cause/, "the cause of an error (ES2022)"],
];

/** The text of a file without its comments and the text inside its strings and templates, so that a pattern is looked for in the code only. */
function codeOf(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:\\])\/\/[^\n]*/g, "$1")
    .replace(/"(?:[^"\\\n]|\\.)*"/g, '""')
    .replace(/'(?:[^'\\\n]|\\.)*'/g, "''")
    .replace(/`(?:[^`\\]|\\.)*`/g, "``");
}

describe("the files of the home picker and of the 404 page", () => {
  it.each(FILES)("%s can be lowered for ES2021 and Safari 15 and uses nothing newer than that", (name) => {
    const source = readFileSync(resolve(STATIC, name), "utf8");
    expect(() => transformSync(source, { loader: "js", target: ["es2021", "safari15"], format: "esm" })).not.toThrow();
    const code = codeOf(source);
    for (const [pattern, what] of TOO_NEW) expect(pattern.test(code), `${name} uses ${what}`).toBe(false);
  });

  it("are checked by patterns that find what they are meant to find", () => {
    for (const [sample, index] of [["list.at(-1)", 0], ["Object.hasOwn(a, b)", 1], ["structuredClone(x)", 2], ["/(?<=a)b/", 3], ["xs.findLast(f)", 4], ["xs.toSorted()", 5], ["this.#x", 9]]) {
      expect(TOO_NEW[index][0].test(codeOf(sample)), sample).toBe(true);
    }
    expect(TOO_NEW[0][0].test(codeOf('// list.at(-1)\nconst a = "x.at(1)";'))).toBe(false);
  });
});
