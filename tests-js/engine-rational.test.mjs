import { describe, expect, it } from "vitest";
import { MAX_DIGITS, ONE, Rational, RationalError, ZERO } from "../pipeline/trioforge/site/static/engine/rational.js";
import { mulberry32 } from "./engine-models.mjs";
import { FULL, SAMPLE } from "./engine-fixtures.mjs";
import { expectWithin, stopwatch } from "./timing.mjs";

// Exact rationals on BigInt: what the exact evaluator builds on, and what the weights follow. The text is the one the Python
// fixtures write: a reduced "p/q" with the denominator always there ("255/1", never "255").

const R = (p, q = 1n) => new Rational(p, q);
const text = (value) => value.toString();

describe("making a rational", () => {
  it("reduces to lowest terms with a positive denominator, and zero is 0/1", () => {
    expect(text(R(6n, 4n))).toBe("3/2");
    expect(text(R(6n, -4n))).toBe("-3/2");
    expect(text(R(-6n, -4n))).toBe("3/2");
    expect(text(R(0n, 5n))).toBe("0/1");
    expect(text(R(0n, -5n))).toBe("0/1");
    expect(text(R(-7n))).toBe("-7/1");
    expect(text(R(255n))).toBe("255/1");
    expect(text(R(10n ** 30n, 10n ** 28n))).toBe("100/1");
  });

  it("holds a numerator and a positive denominator that are BigInts, and is frozen", () => {
    const value = R(-6n, 4n);
    expect(value.numerator).toBe(-3n);
    expect(value.denominator).toBe(2n);
    expect(Object.isFrozen(value)).toBe(true);
    expect(() => {
      "use strict";
      value.numerator = 1n;
    }).toThrow(TypeError);
    expect(value.numerator).toBe(-3n);
  });

  it("takes whole numbers that are safe integers, as well as BigInts", () => {
    expect(text(new Rational(6, -4))).toBe("-3/2");
    expect(text(new Rational(5))).toBe("5/1");
    expect(text(new Rational(Number.MAX_SAFE_INTEGER, 1n))).toBe("9007199254740991/1");
  });

  it("refuses a zero denominator", () => {
    expect(() => R(1n, 0n)).toThrow(RationalError);
    expect(() => R(0n, 0n)).toThrow(RationalError);
    expect(() => new Rational(1, 0)).toThrow(RationalError);
    expect(() => new Rational(1, -0)).toThrow(RationalError);
  });

  it("refuses anything that is not a whole number", () => {
    for (const bad of [1.5, NaN, Infinity, -Infinity, 2 ** 53, "1", "1/2", null, undefined, {}, [], true, Symbol("x")]) {
      expect(() => new Rational(bad), String(typeof bad)).toThrow(RationalError);
      if (bad !== undefined) expect(() => new Rational(1n, bad), String(typeof bad)).toThrow(RationalError); // undefined is the default, 1
    }
  });

  it("is an error of its own kind with a message", () => {
    let caught;
    try {
      R(1n, 0n);
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(Error);
    expect(caught.name).toBe("RationalError");
    expect(caught.message).toMatch(/zero/);
  });

  it("has ZERO and ONE", () => {
    expect(text(ZERO)).toBe("0/1");
    expect(text(ONE)).toBe("1/1");
  });

  it("is not a number to an operator, which would compare the texts: < and + and Number() refuse it", () => {
    const [a, b] = [R(1n, 2n), R(1n, 3n)];
    expect(() => a < b).toThrow(RationalError);
    expect(() => a + b).toThrow(RationalError);
    expect(() => a * 2).toThrow(RationalError);
    expect(() => Number(a)).toThrow(RationalError);
    expect(() => +a).toThrow(RationalError);
    expect(`${a}`).toBe("1/2"); // the text is still there
    expect(String(a)).toBe("1/2");
    expect([R(3n), R(1n), R(2n)].sort((x, y) => x.compare(y)).map(text)).toEqual(["1/1", "2/1", "3/1"]);
  });
});

describe("the text of a rational (the way the fixtures write it)", () => {
  it("prints the denominator always, even for a whole number", () => {
    expect(String(R(5n))).toBe("5/1");
    expect(String(R(-5n, 3n))).toBe("-5/3");
    expect(`${R(0n)}`).toBe("0/1");
    expect(JSON.stringify({ value: R(3n, 6n) })).toBe('{"value":"1/2"}');
  });

  it("reads the reduced p/q text and prints it back", () => {
    for (const written of ["0/1", "1/1", "-1/1", "255/1", "1/2", "-3/4", "1111/5000", "1/1000000000000", "10/1", "60/1"]) {
      const value = Rational.parse(written);
      expect(value).toBeInstanceOf(Rational);
      expect(text(value)).toBe(written);
    }
  });

  it("reads and prints back every rational the bundle of the sample writes", () => {
    const bundle = SAMPLE.read("profiles/pal-mnk-ber-l50.bundle.json");
    const found = [];
    const stack = [bundle.constants, bundle.monk_bins, bundle.tier_rules, bundle.weapon_rules, bundle.weight_groups, bundle.regen_ratios];
    while (stack.length > 0) {
      const node = stack.pop();
      if (typeof node === "string") {
        if (/^-?[0-9]+\/[0-9]+$/.test(node)) found.push(node);
      } else if (Array.isArray(node)) stack.push(...node);
      else if (node !== null && typeof node === "object") stack.push(...Object.values(node));
    }
    expect(found.length).toBeGreaterThan(300);
    const wrong = found.filter((written) => text(Rational.parse(written)) !== written);
    expect(wrong).toEqual([]);
  });

  /** The "p/q" texts under a value (a walk with a stack of its own), as [numerator digits, denominator digits, text]. */
  function ratioTexts(root) {
    const found = [];
    const stack = [root];
    while (stack.length > 0) {
      const node = stack.pop();
      if (typeof node === "string") {
        const match = /^(-?[0-9]+)\/([0-9]+)$/.exec(node);
        if (match !== null) found.push([match[1].replace("-", "").length, match[2].length, node]);
      } else if (Array.isArray(node)) stack.push(...node);
      else if (node !== null && typeof node === "object") stack.push(...Object.values(node));
    }
    return found;
  }

  it("takes every text of every bundle with a wide margin: the longest has 6 digits of numerator and 13 of denominator, the cap is 64", () => {
    const bundles = [["the sample", SAMPLE.read("profiles/pal-mnk-ber-l50.bundle.json")]];
    if (FULL !== null) {
      for (const path of FULL.paths("profiles").filter((p) => p.endsWith(".bundle.json"))) bundles.push([path, FULL.read(path)]);
    }
    let numerator = 0;
    let denominator = 0;
    for (const [label, bundle] of bundles) {
      const texts = ratioTexts([bundle.constants, bundle.monk_bins, bundle.tier_rules, bundle.weapon_rules, bundle.weight_groups, bundle.regen_ratios, bundle.profile_common.pools]);
      expect(texts.length, label).toBeGreaterThan(100);
      for (const [n, d] of texts) {
        numerator = Math.max(numerator, n);
        denominator = Math.max(denominator, d);
      }
    }
    expect(numerator).toBe(6);
    expect(denominator).toBe(13);
    expect(MAX_DIGITS).toBe(64);
    expect(MAX_DIGITS).toBeGreaterThanOrEqual(4 * Math.max(numerator, denominator)); // the cap is at least four times the longest text there is
  });

  it("refuses text that is not a reduced p/q, as the Python reader does", () => {
    const refused = [
      "", "5", "-5", "5/0", "0/0", "6/4", "-6/4", "4/-2", "+1/2", "1/+2", " 1/2", "1/2 ", "1 /2", "1/ 2", "1/2\n", "\n1/2", "1.5/2", "1/2.5", "1/2/3",
      "1//2", "/2", "1/", "/", "a/b", "abc", "1e3/1", "0x10/1", "0b11/1", "1_000/1", "--1/2", "-/2", "007/1", "-0/1", "1/007", "0/2",
      "١/٢", "１/２", "NaN", "Infinity", "-Infinity", "null", "1/1\u0000", "1/1e2",
    ];
    for (const written of refused) {
      expect(() => Rational.parse(written), JSON.stringify(written)).toThrow(RationalError);
    }
  });

  it("refuses what is not text", () => {
    for (const bad of [5, 5n, 1.5, null, undefined, {}, [], ["1/2"], true, R(1n), Symbol("x"), () => "1/2", { toString: () => "1/2" }]) {
      expect(() => Rational.parse(bad), typeof bad).toThrow(RationalError);
    }
  });

  it("refuses a text so long that reducing it could stall the page", () => {
    expect(() => Rational.parse(`${"9".repeat(10_000)}/1`)).toThrow(RationalError);
    expect(() => Rational.parse(`1/${"9".repeat(10_000)}`)).toThrow(RationalError);
    expect(() => Rational.parseLong(`${"9".repeat(10_000)}/1`)).toThrow(RationalError);
    expect(() => Rational.parseLong(`1/${"9".repeat(10_000)}`)).toThrow(RationalError);
    // but a long value is fine through the way for texts that are not in a bundle: 300 digits
    const big = `${"9".repeat(300)}/1`;
    expect(text(Rational.parseLong(big))).toBe(big);
  });

  it("takes the most digits that a text of a bundle may have in the numerator and in the denominator, and no more", () => {
    const longest = `${"1".padEnd(MAX_DIGITS, "0")}/${"7".repeat(MAX_DIGITS)}`; // 10^63 over 77...7: in lowest terms
    expect(text(Rational.parse(longest))).toBe(longest);
    expect(text(Rational.parse(`-${longest}`))).toBe(`-${longest}`); // the sign is not a digit
    for (const written of [`${"1".padEnd(MAX_DIGITS + 1, "0")}/7`, `1/${"7".repeat(MAX_DIGITS + 1)}`, `-${"1".padEnd(MAX_DIGITS + 1, "0")}/7`, `${"1".padEnd(200, "0")}/7`]) {
      expect(() => Rational.parse(written), written.slice(0, 30)).toThrow(RationalError);
    }
  });

  it("has a way for the texts that are not in a bundle (a value that toString printed): up to 4096 digits, and the same rules otherwise", () => {
    const written = `${"1".padEnd(4096, "0")}/${"7".repeat(4096)}`;
    expect(text(Rational.parseLong(written))).toBe(written);
    expect(() => Rational.parseLong(`${"1".padEnd(4097, "0")}/7`)).toThrow(RationalError);
    expect(() => Rational.parseLong(`1/${"7".repeat(4097)}`)).toThrow(RationalError);
    for (const bad of ["", "5", "6/4", "5/0", "+1/2", "01/2", " 1/2", 5, null, undefined, {}]) expect(() => Rational.parseLong(bad), String(bad)).toThrow(RationalError);
    for (const good of ["0/1", "-7/3", "255/1", `${"9".repeat(80)}/1`]) expect(text(Rational.parseLong(good))).toBe(good);
  });

  it("reduces a text of the most digits in well under a millisecond, whatever its digits (the worst case for Euclid: consecutive Fibonacci numbers)", () => {
    let a = 1n;
    let b = 1n;
    while (b.toString().length < MAX_DIGITS) [a, b] = [b, a + b];
    const worst = `${b}/${a}`;
    expect(b.toString()).toHaveLength(MAX_DIGITS);
    for (let i = 0; i < 200; i += 1) Rational.parse(worst); // warm-up
    const watch = stopwatch();
    for (let i = 0; i < 1000; i += 1) Rational.parse(worst);
    const each = watch.stop().per(1000);
    expectWithin(each, 0.5, "reducing a text of the most digits"); // about 0.05 ms on the machine this was measured on
    expect(text(Rational.parse(worst))).toBe(worst);
  });
});

describe("arithmetic", () => {
  it("adds, subtracts, multiplies and divides exactly", () => {
    const [a, b] = [R(1n, 3n), R(1n, 6n)];
    expect(text(a.add(b))).toBe("1/2");
    expect(text(a.sub(b))).toBe("1/6");
    expect(text(b.sub(a))).toBe("-1/6");
    expect(text(a.mul(b))).toBe("1/18");
    expect(text(a.div(b))).toBe("2/1");
    expect(text(b.div(a))).toBe("1/2");
    expect(text(a.neg())).toBe("-1/3");
    expect(text(ZERO.neg())).toBe("0/1");
    expect(text(R(-3n, 4n).abs())).toBe("3/4");
    expect(text(R(3n, 4n).abs())).toBe("3/4");
  });

  it("keeps the result reduced with a positive denominator", () => {
    expect(text(R(1n, 2n).add(R(1n, 2n)))).toBe("1/1");
    expect(text(R(1n, 2n).sub(R(1n, 2n)))).toBe("0/1");
    expect(text(R(-1n, 2n).mul(R(-4n, 3n)))).toBe("2/3");
    expect(text(R(1n, 2n).div(R(-1n, 4n)))).toBe("-2/1");
    expect(text(R(-1n, 2n).div(R(-1n, 4n)))).toBe("2/1");
    expect(text(R(0n).div(R(-7n, 3n)))).toBe("0/1");
  });

  it("refuses to divide by zero", () => {
    expect(() => R(1n, 2n).div(ZERO)).toThrow(RationalError);
    expect(() => R(1n, 2n).div(0n)).toThrow(RationalError);
    expect(() => R(1n, 2n).div(0)).toThrow(RationalError);
    expect(() => ZERO.div(ZERO)).toThrow(RationalError);
  });

  it("takes a BigInt or a safe integer for the other side, and nothing else", () => {
    expect(text(R(1n, 2n).add(1n))).toBe("3/2");
    expect(text(R(1n, 2n).mul(4))).toBe("2/1");
    expect(text(R(1n, 2n).sub(1))).toBe("-1/2");
    expect(text(R(1n, 2n).div(-2))).toBe("-1/4");
    for (const bad of [0.5, NaN, Infinity, "1/2", "1", null, undefined, {}, [], true, 2 ** 53]) {
      expect(() => R(1n, 2n).add(bad), String(bad)).toThrow(RationalError);
      expect(() => R(1n, 2n).mul(bad), String(bad)).toThrow(RationalError);
      expect(() => R(1n, 2n).compare(bad), String(bad)).toThrow(RationalError);
      expect(() => R(1n, 2n).equals(bad), String(bad)).toThrow(RationalError);
    }
  });

  it("compares by value, not by form", () => {
    expect(R(1n, 3n).compare(R(1n, 2n))).toBe(-1);
    expect(R(1n, 2n).compare(R(1n, 3n))).toBe(1);
    expect(R(2n, 4n).compare(R(1n, 2n))).toBe(0);
    expect(R(-1n, 2n).compare(R(1n, 3n))).toBe(-1);
    expect(R(-1n, 3n).compare(R(-1n, 2n))).toBe(1);
    expect(R(-1n, 2n).compare(R(-3n, 6n))).toBe(0);
    expect(R(1n, 2n).equals(R(3n, 6n))).toBe(true);
    expect(R(1n, 2n).equals(R(1n, 3n))).toBe(false);
    expect(R(1n, 2n).equals(1n)).toBe(false);
    expect(R(4n).equals(4)).toBe(true);
    expect(R(0n).equals(R(0n, -3n))).toBe(true);
  });

  it("gives the sign, whether it is whole, and its floor and ceiling as BigInts", () => {
    expect([R(-1n, 2n).sign(), R(0n).sign(), R(1n, 3n).sign()]).toEqual([-1, 0, 1]);
    expect([R(4n, 2n).isInteger(), R(1n, 2n).isInteger(), R(0n).isInteger()]).toEqual([true, false, true]);
    expect([R(7n, 2n).floor(), R(7n, 2n).ceil(), R(-7n, 2n).floor(), R(-7n, 2n).ceil(), R(4n).floor(), R(-4n).ceil(), R(0n).floor()]).toEqual([
      3n, 4n, -4n, -3n, 4n, -4n, 0n,
    ]);
  });

  it("is exact where doubles are not", () => {
    const tenth = Rational.fromNumber(0.1);
    const fifth = Rational.fromNumber(0.2);
    expect(0.1 + 0.2).not.toBe(0.3);
    expect(tenth.add(fifth).equals(Rational.fromNumber(0.3))).toBe(true);
    expect(text(tenth.add(fifth))).toBe("3/10");
    expect(text(Rational.fromNumber(1.1).mul(Rational.fromNumber(1.1)))).toBe("121/100");
  });

  it("obeys the field laws on random values (a seeded series)", () => {
    const next = mulberry32(20261014);
    const whole = () => {
      const digits = 1 + Math.floor(next() * 40);
      let value = 0n;
      for (let i = 0; i < digits; i += 1) value = value * 10n + BigInt(Math.floor(next() * 10));
      return next() < 0.5 ? -value : value;
    };
    const rational = () => {
      let q = whole();
      while (q === 0n) q = whole();
      return R(whole(), q);
    };
    for (let i = 0; i < 300; i += 1) {
      const [a, b, c] = [rational(), rational(), rational()];
      expect(a.add(b).equals(b.add(a))).toBe(true);
      expect(a.mul(b).equals(b.mul(a))).toBe(true);
      expect(a.add(b).add(c).equals(a.add(b.add(c)))).toBe(true);
      expect(a.mul(b.add(c)).equals(a.mul(b).add(a.mul(c)))).toBe(true);
      expect(a.add(b).sub(b).equals(a)).toBe(true);
      if (b.sign() !== 0) expect(a.mul(b).div(b).equals(a)).toBe(true);
      expect(a.sub(a).sign()).toBe(0);
      expect(a.compare(b)).toBe(-b.compare(a));
      expect(a.compare(b)).toBe(a.sub(b).sign());
      // always reduced, denominator positive
      for (const value of [a.add(b), a.mul(c), a.sub(c)]) {
        expect(value.denominator > 0n).toBe(true);
        expect(Rational.parseLong(text(value)).equals(value)).toBe(true);
        expect(text(value)).toBe(text(Rational.parseLong(text(value))));
      }
    }
  });
});

describe("very large values", () => {
  const factorial = (n) => {
    let value = 1n;
    for (let i = 2n; i <= n; i += 1n) value *= i;
    return value;
  };

  it("stay exact: 100 digits and more, in the numerator and in the denominator", () => {
    const googol = 10n ** 100n;
    expect(text(R(googol).add(R(1n)))).toBe(`${googol + 1n}/1`);
    expect(text(R(1n, googol).mul(R(googol)))).toBe("1/1");
    expect(text(R(factorial(100n), factorial(98n)))).toBe("9900/1");
    expect(text(R(factorial(60n), factorial(62n)))).toBe("1/3782");
    const huge = R(10n ** 400n + 1n, 10n ** 400n);
    expect(text(huge.sub(R(1n)))).toBe(`1/${10n ** 400n}`);
    expect(huge.compare(R(1n))).toBe(1);
    expect(text(R(2n ** 4000n, 2n ** 3998n))).toBe("4/1");
  });

  it("go through the text and back unchanged", () => {
    const value = R(3n ** 800n, 7n ** 300n);
    expect(Rational.parseLong(text(value)).equals(value)).toBe(true);
    expect(text(Rational.parseLong(text(value)))).toBe(text(value));
  });

  it("add up without losing a digit where a double would", () => {
    const big = R(2n ** 80n);
    expect(text(big.add(R(1n)).sub(big))).toBe("1/1");
    expect(Number(2n ** 80n) + 1 - Number(2n ** 80n)).toBe(0);
  });
});

describe("a double read as the decimal it prints as (the Python fr)", () => {
  it("reads 4.8 as 24/5 and 0.2222 as 1111/5000, not the binary value", () => {
    expect(text(Rational.fromNumber(4.8))).toBe("24/5");
    expect(text(Rational.fromNumber(0.2222))).toBe("1111/5000");
    expect(text(Rational.fromNumber(0.1))).toBe("1/10");
    expect(text(Rational.fromNumber(12.75))).toBe("51/4");
    expect(text(Rational.fromNumber(-0.5))).toBe("-1/2");
    expect(text(Rational.fromNumber(0.05))).toBe("1/20");
  });

  it("reads whole numbers, zero and minus zero", () => {
    expect(text(Rational.fromNumber(0))).toBe("0/1");
    expect(text(Rational.fromNumber(-0))).toBe("0/1");
    expect(text(Rational.fromNumber(600))).toBe("600/1");
    expect(text(Rational.fromNumber(-12))).toBe("-12/1");
    expect(text(Rational.fromNumber(Number.MAX_SAFE_INTEGER))).toBe("9007199254740991/1");
  });

  it("reads the exponent forms a double prints with", () => {
    expect(text(Rational.fromNumber(1e-7))).toBe("1/10000000");
    expect(text(Rational.fromNumber(1.5e-10))).toBe("3/20000000000");
    expect(text(Rational.fromNumber(1e21))).toBe(`${10n ** 21n}/1`);
    expect(text(Rational.fromNumber(1e23))).toBe(`${10n ** 23n}/1`);
    expect(text(Rational.fromNumber(1.5e300))).toBe(`${15n * 10n ** 299n}/1`);
    expect(Rational.fromNumber(5e-324).equals(R(5n, 10n ** 324n))).toBe(true);
    expect(text(Rational.fromNumber(0.30000000000000004))).toBe("7500000000000001/25000000000000000");
  });

  it("refuses what is not a finite number", () => {
    for (const bad of [NaN, Infinity, -Infinity, "1.5", null, undefined, 5n, {}, [1], true]) {
      expect(() => Rational.fromNumber(bad), String(bad)).toThrow(RationalError);
    }
  });
});

describe("a rational as a double (for display, and the one rounding of the weights)", () => {
  // the values Python's float(Fraction) gives
  const known = [
    [R(1n, 3n), 0.3333333333333333, "3fd5555555555555"],
    [R(2n, 3n), 0.6666666666666666, "3fe5555555555555"],
    [R(1n, 10n), 0.1, "3fb999999999999a"],
    [R(2n ** 53n + 1n), 9007199254740992, "4340000000000000"], // a tie: to even
    [R(2n ** 53n + 3n), 9007199254740996, "4340000000000002"], // a tie: to even, upward
    [R(2n ** 54n + 2n), 18014398509481984, "4350000000000000"],
    [R(2n ** 54n + 6n), 18014398509481990, "4350000000000002"],
    [R(123456789n, 1000n), 123456.789, "40fe240c9fbe76c9"],
    [R(7n, 10n ** 12n), 7e-12, "3d9ec94ca210599e"],
    [R(10n ** 23n), 1e23, "44b52d02c7e14af6"],
  ];
  const bits = (value) => {
    const view = new DataView(new ArrayBuffer(8));
    view.setFloat64(0, value);
    return view.getBigUint64(0).toString(16).padStart(16, "0");
  };

  it("rounds to the nearest double, ties to even, as Python does", () => {
    for (const [value, want, hex] of known) {
      expect(value.toNumber(), String(value)).toBe(want);
      if (hex !== null) expect(bits(value.toNumber()), String(value)).toBe(hex);
    }
  });

  it("is exact for whole numbers a double holds, and for halves, quarters and the like", () => {
    for (const whole of [0n, 1n, -1n, 255n, 2n ** 52n, 2n ** 53n, -(2n ** 53n), 2n ** 100n, 3n * 2n ** 200n]) {
      expect(R(whole).toNumber()).toBe(Number(whole));
    }
    expect([R(3n, 2n).toNumber(), R(-5n, 4n).toNumber(), R(51n, 4n).toNumber(), R(1n, 1024n).toNumber()]).toEqual([1.5, -1.25, 12.75, 2 ** -10]);
  });

  it("equals the division of two doubles where IEEE makes it correctly rounded (a seeded series)", () => {
    const next = mulberry32(7);
    let checked = 0;
    for (let i = 0; i < 20_000; i += 1) {
      const scale = Math.floor(next() * 53);
      const magnitude = Math.floor(next() * 2 ** scale);
      const a = next() < 0.5 ? -magnitude || 0 : magnitude; // never minus zero
      const b = 1 + Math.floor(next() * 2 ** Math.floor(next() * 53));
      expect(R(BigInt(a), BigInt(b)).toNumber(), `${a}/${b}`).toBe(a / b);
      checked += 1;
    }
    expect(checked).toBe(20_000);
  });

  it("gives plus zero for zero, and keeps the sign of a negative value", () => {
    expect(Object.is(ZERO.toNumber(), 0)).toBe(true);
    expect(Object.is(R(0n, 7n).toNumber(), 0)).toBe(true);
    expect(R(-1n, 4n).toNumber()).toBe(-0.25);
    expect(R(-(2n ** 53n) - 1n).toNumber()).toBe(-9007199254740992);
  });

  it("is correct among the subnormals, at the edge of zero and of overflow", () => {
    expect(R(1n, 2n ** 1074n).toNumber()).toBe(5e-324);
    expect(R(1n, 2n ** 1075n).toNumber()).toBe(0); // the tie goes to even: zero
    expect(R(3n, 2n ** 1075n).toNumber()).toBe(1e-323);
    expect(R(5n, 2n ** 1075n).toNumber()).toBe(1e-323);
    expect(R(1n, 2n ** 1076n).toNumber()).toBe(0);
    expect(R(2n ** 1075n + 1n, 2n ** 2150n).toNumber()).toBe(5e-324); // a hair over the tie goes up
    expect(bits(R(2n ** 53n - 1n, 2n ** 1074n).toNumber())).toBe("001fffffffffffff");
    expect(R(2n ** 1024n - 2n ** 971n).toNumber()).toBe(Number.MAX_VALUE);
    expect(R(2n ** 1024n - 2n ** 970n - 1n).toNumber()).toBe(Number.MAX_VALUE);
    expect(() => R(2n ** 1024n - 2n ** 970n).toNumber()).toThrow(RationalError); // the tie goes to even: past the largest, and Python's float() raises
    expect(() => R(2n ** 1024n).toNumber()).toThrow(RationalError);
    expect(() => R(-(2n ** 1030n)).toNumber()).toThrow(RationalError);
    expect(R(1n, 10n ** 400n).toNumber()).toBe(0);
  });

  it("throws a RationalError where Python's float(Fraction) raises OverflowError, for either sign, and not a value earlier", () => {
    // pipeline/tests/test_export_browser.py (test_float_of_a_fraction_overflows_at_the_tie_below_two_to_the_1024th_for_either_sign) finds this
    // boundary by asking float() itself: a whole number has a double up to 2^1024 - 2^970 - 1, and none from 2^1024 - 2^970 on (the tie
    // between the largest double and 2^1024 goes to the even one, 2^1024)
    const overflow = 2n ** 1024n - 2n ** 970n;
    for (const sign of [1n, -1n]) {
      const largest = sign < 0n ? -Number.MAX_VALUE : Number.MAX_VALUE;
      expect(R(sign * (overflow - 1n)).toNumber()).toBe(largest);
      expect(() => R(sign * overflow).toNumber()).toThrow(RationalError);
      expect(() => R(sign * (overflow + 1n)).toNumber()).toThrow(RationalError);
      for (const denominator of [2n, 3n, 7n, 10n ** 6n, 10n ** 400n + 7n]) {
        // ratios, at the tie and a hair on either side of it
        expect(R(sign * (overflow * denominator - 1n), denominator).toNumber(), `${sign} ${denominator}`).toBe(largest);
        expect(() => R(sign * (overflow * denominator + 1n), denominator).toNumber(), `${sign} ${denominator}`).toThrow(RationalError);
      }
      for (const far of [2n ** 1030n, 10n ** 400n]) expect(() => R(sign * far).toNumber()).toThrow(RationalError);
    }
    expect(R(3n * 10n ** 400n + 1n, 10n ** 400n).toNumber()).toBe(3); // a huge ratio that is in range has its double
    expect(() => R(10n ** 709n + 1n, 10n ** 400n).toNumber()).toThrow(RationalError);
    expect(() => R(2n ** 1024n).toNumber()).toThrow(/double/); // and the message says what is wrong
  });

  it("is the same for a value and for a huge one that has the same ratio", () => {
    const scale = 10n ** 300n + 7n;
    for (const [p, q] of [[1n, 3n], [22n, 7n], [123456789n, 1000n], [-355n, 113n]]) {
      expect(R(p * scale, q * scale).toNumber()).toBe(R(p, q).toNumber());
    }
    expect(R(10n ** 400n + 1n, 10n ** 400n).toNumber()).toBe(1);
    expect(R(2n ** 200n + 1n, 2n ** 200n).toNumber()).toBe(1);
    expect(R(2n ** 60n - 1n, 3n * 2n ** 60n).toNumber()).toBe(0.3333333333333333);
  });
});
