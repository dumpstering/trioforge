import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The numeric-literal lint of the MILP builder (static/engine/model.js). The builder is a port of a Python module that is full of constants (the
// knees at 255 and 510, the 5/2 slope of the mana bands, the 4/3 of the sheet ...); a port that copies them as literals would be a second place
// to keep each of them right. So the source of the builder holds no numeric literal but 0, 1 and -1 (the last is the unary minus on 1): every
// constant comes from the bundle's constants (CONSTANTS in evaluate.js, which a test holds to the bundle) or from the profile.
//
// The scan below reads the source as JavaScript does: a number inside a comment, a string, the text of a template or a regular expression is not
// a literal, a number inside the `${ }` of a template is, and a digit inside a name (`weight10`, `x2`) is part of the name. A number can also be
// written as text for a conversion (`Number("255")`, `+"510"`, `parseInt(x, 10)`), so a string, or a part of a template's text, that is a numeric
// literal as a whole (apart from spaces and a sign) is a literal too, and `parseInt` and `parseFloat` are not used at all. It is tested here on
// what it must see and must not see, and on planted literals: a lint that sees nothing would pass the builder for the wrong reason.

const SOURCE = new URL("../pipeline/trioforge/site/static/engine/model.js", import.meta.url);

/** The numeric literals that the builder may hold. `0n` and `1n` are the BigInt forms of the same two numbers. */
const ALLOWED = new Set(["0", "1", "0n", "1n"]);
/** Words after which a `/` starts a regular expression and not a division. */
const BEFORE_REGEX = new Set(["return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do", "else", "yield", "await"]);

/** The words that turn text into a number: the builder does not use them (its numbers come from the constants and the profile). */
const PARSERS = new Set(["parseInt", "parseFloat"]);

const NUMBER = /0[xX][0-9a-fA-F_]+n?|0[oO][0-7_]+n?|0[bB][01_]+n?|(?:[0-9][0-9_]*\.?[0-9_]*|\.[0-9][0-9_]*)(?:[eE][+-]?[0-9_]+)?n?/y;
/** A text that is a numeric literal as a whole: a sign and spaces around it are allowed, as `Number(" -7 ")` takes them. */
const NUMERIC_TEXT = new RegExp(`^[+-]?\\s*(${NUMBER.source})$`, "u");
const NAME = /[\p{L}\p{Nl}_$][\p{L}\p{Nl}\p{Mn}\p{Mc}\p{Nd}\p{Pc}$‌‍]*/uy;

/**
 * What the scan finds in some JavaScript source, as `{text, line, kind}` in order: the numeric literals (`kind` "number"), the strings and the parts
 * of a template's text that are a numeric literal as a whole (the text without a sign or spaces, `kind` "text"), and the words that parse text into
 * a number (`kind` "parser").
 */
function scan(source) {
  const found = [];
  let at = 0;
  let line = 1;

  /** A string, or a part of a template's text, that might be a number written as text. */
  const text = (content, where) => {
    const match = NUMERIC_TEXT.exec(content.trim());
    if (match !== null) found.push({ text: match[1], line: where, kind: "text" });
  };

  /** Move past `count` characters, counting the lines. */
  const skip = (count) => {
    for (let i = 0; i < count; i += 1) if (source[at + i] === "\n") line += 1;
    at += count;
  };

  /** Scan code until the end of the source, or (inside a template's `${ }`) until the brace that closes it. */
  function code(insideTemplate) {
    let depth = 0;
    let previous = ""; // the last token that was not a comment: a word, a number, or a punctuator
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
        text(source.slice(at + 1, end), line);
        skip(end + 1 - at);
        previous = "string";
      } else if (c === "`") {
        skip(1);
        template();
        previous = "string";
      } else if (c === "/") {
        // after a name (that is not a keyword), a number, a string, a closing bracket or a postfix ++ or --, a slash divides
        const division = previous !== "" && (previous === "number" || previous === "string" || previous === ")" || previous === "]" || previous === "}" || previous === "++" || previous === "--" || (/^[\p{L}_$]/u.test(previous) && !BEFORE_REGEX.has(previous)));
        if (division) {
          skip(1);
          previous = "/";
        } else {
          let end = at + 1;
          let inClass = false;
          while (end < source.length && (source[end] !== "/" || inClass)) {
            if (source[end] === "\\") end += 1;
            else if (source[end] === "[") inClass = true;
            else if (source[end] === "]") inClass = false;
            end += 1;
          }
          end += 1;
          while (end < source.length && /[a-z]/.test(source[end])) end += 1;
          skip(end - at);
          previous = "regex";
        }
      } else if ((c >= "0" && c <= "9") || (c === "." && next >= "0" && next <= "9")) {
        NUMBER.lastIndex = at;
        const match = NUMBER.exec(source);
        found.push({ text: match[0], line, kind: "number" });
        skip(match[0].length);
        previous = "number";
      } else {
        NAME.lastIndex = at;
        const word = NAME.exec(source);
        if (word !== null) {
          if (PARSERS.has(word[0])) found.push({ text: word[0], line, kind: "parser" });
          skip(word[0].length);
          previous = word[0];
        } else if ((c === "+" || c === "-") && next === c) {
          skip(2);
          previous = c + c; // ++ or --: a postfix one ends an expression (a prefix one is followed by its operand, never by a slash)
        } else {
          if (insideTemplate && c === "{") depth += 1;
          if (insideTemplate && c === "}") {
            if (depth === 0) return;
            depth -= 1;
          }
          skip(1);
          previous = c;
        }
      }
    }
  }

  /** Scan the text of a template (the opening backtick is behind us) to the closing backtick, reading each `${ }` as code. */
  function template() {
    let from = at;
    let fromLine = line;
    while (at < source.length) {
      const c = source[at];
      if (c === "\\") skip(2);
      else if (c === "`") {
        text(source.slice(from, at), fromLine);
        return skip(1);
      } else if (c === "$" && source[at + 1] === "{") {
        text(source.slice(from, at), fromLine);
        skip(2);
        code(true);
        skip(1); // the closing brace
        from = at;
        fromLine = line;
      } else skip(1);
    }
    return undefined;
  }

  code(false);
  return found;
}

/** Every numeric literal of some JavaScript source, as `{text, line}`, in order (a number written as text is not one: see `forbidden`). */
const numericLiterals = (source) => scan(source).filter(({ kind }) => kind === "number").map(({ text, line }) => ({ text, line }));

/** What the builder may not hold: a numeric literal, or a string that is one as a whole, other than 0 and 1 (and 0n, 1n), and a parser of text. */
const forbidden = (source) => scan(source).filter(({ text, kind }) => kind === "parser" || !ALLOWED.has(text));

describe("the scan for numeric literals", () => {
  const texts = (source) => numericLiterals(source).map(({ text }) => text);

  it("sees every form of a number", () => {
    expect(texts("a = 255; b = 0.5; c = .5; d = 1e3; e = 2E-3; f = 0xff; g = 0o17; h = 0b101; i = 1_000; j = 10n; k = 5.; l = 1.0")).toEqual(
      ["255", "0.5", ".5", "1e3", "2E-3", "0xff", "0o17", "0b101", "1_000", "10n", "5.", "1.0"],
    );
  });

  it("sees a number where a minus sign, an operator, a bracket or a comma is before it", () => {
    expect(texts("x[2] = f(3, -4) + 5 * -6 - (7)")).toEqual(["2", "3", "4", "5", "6", "7"]);
  });

  it("does not see a number in a comment, a string, a template's text or a regular expression", () => {
    const source = [
      "// 255 in a line comment",
      "/* 510 in a",
      "   block comment 4/3 */",
      'const a = "255";',
      "const b = '510';",
      "const c = `text 255 ${name} and 510`;",
      "const d = /^[0-9]{3,10}$/.test(a);",
      "const e = a.replace(/0|1|2/g, '');",
      "const f = [/10/, /\\/20/, /[/30]/];",
    ].join("\n");
    expect(texts(source)).toEqual([]);
  });

  it("does not see a digit in a name", () => {
    expect(texts("const weight10 = x2 + $3 + _4 + a.b5 + item.tier6; const é7 = 0;")).toEqual(["0"]);
  });

  it("sees a number inside the ${ } of a template, even a nested one, and not the text around it", () => {
    expect(texts("`a 1 ${x + 255} b 2 ${`c 3 ${y * 510}`} d 4`")).toEqual(["255", "510"]);
  });

  it("takes a slash for a division after a name, a number, a bracket or a string, and for a regular expression after an operator", () => {
    expect(texts("a = b / 255 / c; d = (e) / 4; f = g[0] / 5; h = 6 / 7; i = 'j' / 8")).toEqual(["255", "4", "0", "5", "6", "7", "8"]);
    expect(texts("a = x ? /2/ : /3/; b = [/4/, /5/]; return /6/.test(c)")).toEqual([]);
  });

  it("counts lines", () => {
    expect(numericLiterals("a = 1;\n\n/* two\nlines */ b = 2;\n`x\n${3}`;")).toEqual([
      { text: "1", line: 1 },
      { text: "2", line: 4 },
      { text: "3", line: 6 },
    ]);
  });
});

describe("the scan for what a constant can hide behind", () => {
  const found = (source) => forbidden(source).map(({ text }) => text);

  it("sees the literals after a postfix ++ or --, where a slash divides (and does not start a regular expression that swallows them)", () => {
    expect(found("x++ / 2; const K = 255;")).toEqual(["2", "255"]);
    expect(found("x-- / 3; const K = 255;")).toEqual(["3", "255"]);
    expect(found("a = b++ / 4 / c; d = 5;")).toEqual(["4", "5"]);
    expect(found("a = (b++) / 6; c = d[e++] / 7; f = 8")).toEqual(["6", "7", "8"]);
    expect(found("for (let i = 0; i < n; i++) total += x[i] / 9;")).toEqual(["9"]);
    expect(found("a = b + +c / 2 / 3;")).toEqual(["2", "3"]); // a plus and a unary plus are not an increment
  });

  it("still takes a slash for a regular expression where an operator, not a postfix one, comes before it", () => {
    expect(found("a = b + /2/.test(c); d = 255;")).toEqual(["255"]);
    expect(found("a = ++b; c = /3/.test(d); e = 255;")).toEqual(["255"]);
    expect(found("a = x ? /4/ : /5/; return /6/.test(c) && 255;")).toEqual(["255"]);
  });

  it("sees a number written as text: a string, or a part of a template's text, that is a numeric literal as a whole", () => {
    for (const [source, want] of [
      ['Number("255")', "255"], ["Number('510')", "510"], ['+"510"', "510"], ['`${"7"}`', "7"], ['Number("1e3")', "1e3"], ['Number("0x10")', "0x10"],
      ['Number(" 7 ")', "7"], ['BigInt("510n")', "510n"], ["x = `${a} 7 ${b}`", "7"], ["x = `255`", "255"], ["x = `${a}2`", "2"], ["x = `3${a}`", "3"],
      ['Number("-5")', "5"], ['Number("+5")', "5"], ['Number("- 5")', "5"], ['Number(".5")', ".5"], ['Number("1_000")', "1_000"], ['Number("0.5")', "0.5"],
      ["x = `${`${'9'}`}`", "9"],
    ]) {
      expect(found(source), source).toEqual([want]);
    }
  });

  it("does not see text that has a number among other text, is 0 or 1, or only looks like one", () => {
    expect(found('a = "0"; b = "1"; c = " 1 "; d = "-1"; e = "0n"; f = "1n"; g = "+1"; h = "- 0"')).toEqual([]);
    expect(found('a = "2h"; b = "1h-shield"; c = "text 255 and 510"; d = "a1"; e = "1 2"; f = ""; g = " "; h = "--"; i = "1e"; j = "0x"; k = "1.2.3"')).toEqual([]);
    expect(found("a = `text 255 ${x} and 510`; b = `${x}`; c = `${x}${y}`; d = `${x} one ${y}`; e = `${x}, 2 ${y}`; f = `1 ${x} 0`")).toEqual([]);
  });

  it("sees a BigInt literal, a digit separator and a number that starts with a dot", () => {
    expect(found("a = 255n; b = 1_000; c = .5; d = 0xFFn; e = 5e-1")).toEqual(["255n", "1_000", ".5", "0xFFn", "5e-1"]);
  });

  it("sees the words that parse text into a number, wherever they stand", () => {
    expect(found("parseInt(x, 10)")).toEqual(["parseInt", "10"]);
    expect(found("Number.parseFloat(x)")).toEqual(["parseFloat"]);
    expect(found("const f = parseFloat; f(x)")).toEqual(["parseFloat"]);
    expect(found("a = { parseIntent: 1, myparseInt: 1, parse: 0 }")).toEqual([]);
  });

  it("counts the line of a number written as text, in a string and in a template", () => {
    const hits = (source) => forbidden(source).map(({ text, line }) => [text, line]);
    expect(hits('a = 1;\nb = "255";\nc = `x\n${"7"} y`;\nd = `\n 9 \n`;')).toEqual([["255", 2], ["7", 4], ["9", 5]]);
  });
});

describe("the builder's source", () => {
  const source = readFileSync(SOURCE, "utf8");

  it("is there, and is code (the scan finds the 0 and 1 that any builder has)", () => {
    expect(source.length).toBeGreaterThan(10_000);
    const literals = numericLiterals(source).map(({ text }) => text);
    expect(literals.filter((text) => text === "0").length).toBeGreaterThan(10);
    expect(literals.filter((text) => text === "1").length).toBeGreaterThan(10);
  });

  it("holds no numeric literal other than 0, 1 and -1: every constant comes from the bundle's constants or from the profile", () => {
    expect(forbidden(source)).toEqual([]);
  });

  it("is caught by the scan when a literal is planted in it, before the first, a middle and the last of its top-level statements", () => {
    const lines = source.split("\n");
    const statements = lines.flatMap((text, at) => (/^(?:export )?(?:const|function|class) /.test(text) ? [at] : []));
    expect(statements.length).toBeGreaterThan(10);
    const places = [statements[0], statements[Math.floor(statements.length / 2)], statements[statements.length - 1]];
    for (const plant of ["255", "0.5", "1e3", "0xff", "10n", "-2", ".25", "1_0", "1.0"]) {
      for (const at of places) {
        const planted = [...lines.slice(0, at), `const PLANTED = ${plant};`, ...lines.slice(at)].join("\n");
        const found = forbidden(planted);
        expect(found.map(({ text }) => text), `${plant} before line ${at + 1}`).toEqual([plant.replace("-", "")]);
        expect(found[0].line).toBe(at + 1);
      }
    }
  });

  it("is caught by the scan when a number is planted in it as text, a parser of text is used, or a postfix operator hides a literal", () => {
    const lines = source.split("\n");
    const statements = lines.flatMap((text, at) => (/^(?:export )?(?:const|function|class) /.test(text) ? [at] : []));
    const places = [statements[0], statements[Math.floor(statements.length / 2)], statements[statements.length - 1]];
    for (const [plant, want] of [
      ['const PLANTED = Number("255");', "255"], ["const PLANTED = +'510';", "510"], ["const PLANTED = `${'7'}`;", "7"], ["const PLANTED = `${COUNT} 7 ${COUNT}`;", "7"],
      ["const PLANTED = `255`;", "255"], ["const PLANTED = parseInt(COUNT);", "parseInt"], ["const PLANTED = Number.parseFloat(COUNT);", "parseFloat"],
      ["let PLANTED = 0; PLANTED++ / 2;", "2"], ["let PLANTED = 0; PLANTED-- / 3 / 255;", "3"],
    ]) {
      for (const at of places) {
        const planted = [...lines.slice(0, at), plant, ...lines.slice(at)].join("\n");
        const hits = forbidden(planted);
        expect(hits.map(({ text }) => text), `${plant} before line ${at + 1}`).toContain(want);
        expect(hits.find(({ text }) => text === want).line).toBe(at + 1);
      }
    }
  });

  it("is caught by the scan when a literal takes the place of a name in it (the constant behind a name copied into the code)", () => {
    const planted = source.replaceAll(/\bZERO\b/g, "0.0");
    expect(planted).not.toBe(source);
    expect(forbidden(planted).map(({ text }) => text)).toContain("0.0");
  });

  it("is not caught for a number that only looks like one: a comment, a string with a number among other text, a name", () => {
    expect(forbidden(`${source}\n// 255 is the cap\nconst a = "the cap is 510"; const b = "2h"; const weight10 = 0;\n`)).toEqual([]);
  });
});
