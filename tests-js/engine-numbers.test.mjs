import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The numbers lint of the pruning, the sessions and the farm path (static/engine/prune.js, solve.js, path.js). These ports of Python modules hold no rule of
// the game: the knees and caps and the curves come from CONSTANTS and UNITS of evaluate.js (which a test holds to the bundle) or from the profile, and a
// number that is not one (a tolerance, a limit on a message, a default) is a named constant of the module, with a comment above it that says what it is
// (and, for a tolerance, which constant of the Python module it is). So the code of these files holds no numeric literal other than 0, 1 and -1, except as
// the value of a constant whose name is in capitals and that has a comment. The scan reads the source as JavaScript does: a number in a comment, a
// string or the text of a template is not a literal, a number inside the `${ }` of a template is, and a digit inside a name is part of the name. (A
// regular expression literal is not read as one: the files have none, and a digit in one would show up as a number.) It is tested on what it must see,
// and on planted literals.

const NAMES = ["prune.js", "solve.js", "path.js"];
const NUMBER = /0[xX][0-9a-fA-F_]+n?|0[oO][0-7_]+n?|0[bB][01_]+n?|(?:[0-9][0-9_]*\.?[0-9_]*|\.[0-9][0-9_]*)(?:[eE][+-]?[0-9_]+)?n?/y;
const NAME = /[\p{L}\p{Nl}_$][\p{L}\p{Nl}\p{Mn}\p{Mc}\p{Nd}\p{Pc}$]*/uy;
const ALLOWED = new Set(["0", "1"]);
/** A line that gives a number to a constant named in capitals. */
const CONSTANT = /^\s*(?:export\s+)?const\s+[A-Z][A-Z0-9_]*\s*=\s*-?[0-9][0-9_.eE+-]*n?\s*;/;
/** The last line of a comment. */
const COMMENT_END = /^\s*\/\/|\*\/\s*$/;

/** The numeric literals of some JavaScript source, as `{text, line}` in order. */
function literals(source) {
  const found = [];
  let at = 0;
  let line = 1;
  const skip = (count) => {
    for (let i = 0; i < count; i += 1) if (source[at + i] === "\n") line += 1;
    at += count;
  };

  function code(insideTemplate) {
    let depth = 0;
    while (at < source.length) {
      const c = source[at];
      const next = source[at + 1];
      if (c === "\n" || c === " " || c === "\t" || c === "\r") {
        skip(1);
      } else if (c === "/" && next === "/") {
        const end = source.indexOf("\n", at);
        skip((end < 0 ? source.length : end) - at);
      } else if (c === "/" && next === "*") {
        const end = source.indexOf("*/", at + 2);
        skip((end < 0 ? source.length : end + 2) - at);
      } else if (c === '"' || c === "'") {
        let end = at + 1;
        while (end < source.length && source[end] !== c) end += source[end] === "\\" ? 2 : 1;
        skip(end + 1 - at);
      } else if (c === "`") {
        skip(1);
        template();
      } else if ((c >= "0" && c <= "9") || (c === "." && next >= "0" && next <= "9")) {
        NUMBER.lastIndex = at;
        const match = NUMBER.exec(source);
        found.push({ text: match[0], line });
        skip(match[0].length);
      } else {
        NAME.lastIndex = at;
        const word = NAME.exec(source);
        if (word !== null) {
          skip(word[0].length);
        } else {
          if (insideTemplate && c === "{") depth += 1;
          if (insideTemplate && c === "}") {
            if (depth === 0) return;
            depth -= 1;
          }
          skip(1);
        }
      }
    }
  }

  function template() {
    while (at < source.length) {
      const c = source[at];
      if (c === "\\") skip(2);
      else if (c === "`") return skip(1);
      else if (c === "$" && source[at + 1] === "{") {
        skip(2);
        code(true);
        skip(1); // the closing brace
      } else skip(1);
    }
    return undefined;
  }

  code(false);
  return found;
}

/** The numbers a file may not hold: not 0 or 1, and not the value of a named constant that has a comment. */
function forbidden(source) {
  const lines = source.split("\n");
  // a constant has a comment when the line above it, or above the group of constants it stands in, ends one
  const commented = (line) => {
    let above = line - 1;
    while (above > 0 && CONSTANT.test(lines[above - 1])) above -= 1;
    return above > 0 && COMMENT_END.test(lines[above - 1]);
  };
  return literals(source).filter(({ text, line }) => {
    if (ALLOWED.has(text)) return false;
    if (CONSTANT.test(lines[line - 1])) return !commented(line);
    return true;
  });
}

describe("the scan for numeric literals", () => {
  const texts = (source) => literals(source).map(({ text }) => text);

  it("sees every form of a number, and none in a comment, a string, the text of a template or a name", () => {
    expect(texts("a = 255; b = 0.5; c = .5; d = 1e3; e = 2E-3; f = 0xff; g = 1_000; h = 10n")).toEqual(["255", "0.5", ".5", "1e3", "2E-3", "0xff", "1_000", "10n"]);
    const quiet = [
      "// 255 in a comment",
      "/* 510 in a",
      "   block comment */",
      'const a = "255"; const b = \'510\'; const c = `text 255 ${name} and 510`; const weight10 = x2 + $3 + _4;',
    ].join("\n");
    expect(texts(quiet)).toEqual([]);
    expect(texts("`a 1 ${x + 255} b ${`c ${y * 510}`} d 4`")).toEqual(["255", "510"]);
  });

  it("counts lines", () => {
    expect(literals("a = 1;\n\n/* two\nlines */ b = 2;\n`x\n${3}`;")).toEqual([
      { text: "1", line: 1 },
      { text: "2", line: 4 },
      { text: "3", line: 6 },
    ]);
  });

  it("allows 0, 1 and the value of a commented constant in capitals, and nothing else", () => {
    const found = (source) => forbidden(source).map(({ text }) => text);
    expect(found("x = 0 + 1 - (-1);")).toEqual([]);
    expect(found("/** a limit */\nconst LIMIT = 255;\nconst OTHER = -1_000;")).toEqual([]); // a group shares the comment above it
    expect(found("/** a limit */\nconst LIMIT = 255;\nlet y;\nconst OTHER = 1_000;")).toEqual(["1_000"]);
    expect(found("const LIMIT = 255;")).toEqual(["255"]); // no comment
    expect(found("/** a limit */\nconst limit = 255;")).toEqual(["255"]); // not in capitals
    expect(found("/** a limit */\nconst LIMIT = 255 * 2;")).toEqual(["255", "2"]); // not just a number
    expect(found("x = y * 0.5; z = a / 4;")).toEqual(["0.5", "4"]);
  });
});

for (const name of NAMES) {
  describe(`${name}`, () => {
    const source = readFileSync(new URL(`../pipeline/trioforge/site/static/engine/${name}`, import.meta.url), "utf8");

    it("is there, and is code (the scan finds the 0 and 1 that any module has)", () => {
      expect(source.length).toBeGreaterThan(5000);
      const found = literals(source).map(({ text }) => text);
      expect(found.filter((text) => text === "0").length).toBeGreaterThan(5);
      expect(found.filter((text) => text === "1").length).toBeGreaterThan(5);
    });

    it("holds no numeric literal but 0, 1 and the value of a named, commented constant", () => {
      expect(forbidden(source)).toEqual([]);
    });

    it("is caught by the scan when a literal is planted in it, before its first and its last top-level function or class", () => {
      const lines = source.split("\n");
      const statements = lines.flatMap((text, at) => (/^(?:export )?(?:function|class) /.test(text) ? [at] : []));
      expect(statements.length).toBeGreaterThan(5);
      for (const plant of ["255", "0.5", "1e3", "0xff", "-2", ".25"]) {
        for (const at of [statements[0], statements[statements.length - 1]]) {
          const planted = [...lines.slice(0, at), `const planted = ${plant};`, ...lines.slice(at)].join("\n");
          const found = forbidden(planted);
          expect(found.map(({ text }) => text), `${plant} before line ${at + 1}`).toEqual([plant.replace("-", "")]);
          expect(found[0].line).toBe(at + 1);
        }
      }
    });
  });
}
