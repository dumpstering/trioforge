// Exact rationals on BigInt: what the weights (weights.js) and the exact evaluator build on.
//
// A Rational is a numerator and a denominator, both BigInt, always in lowest terms with a positive denominator (zero is 0/1), and it never
// changes. Its text is the one the Python side writes (`rat` in pipeline/trioforge/export/browser.py): "p/q", reduced, with the denominator
// always there, so a whole number is "255/1" and never "255". `Rational.parse` takes exactly the texts that `unrat` there takes (up to MAX_DIGITS
// digits in the numerator and in the denominator: the texts of a bundle), and refuses the rest: a bare number, a ratio not in lowest terms, a
// zero denominator, a sign or a space or a digit that is not 0 to 9. `Rational.parseLong` is the same for the texts that are not in a bundle.
//
// `Rational.fromNumber` reads a double as the decimal it prints as (4.8 is 24/5, 0.2222 is 1111/5000), as Python's `fr` does: the
// weights and the rules are written as decimals, and the exact arithmetic is on those decimals. `toNumber` rounds once to the nearest
// double, ties to even (what Python's float(Fraction) does), so a result that Python rounded once is the same double here; one that rounds past
// the largest double is a RationalError, where Python raises OverflowError.
//
// No arithmetic here goes through a double. Nothing here uses a feature newer than Safari 15.0 has (BigInt, which is 14.0).

/** A value that is not a rational, text that is not a rational, a division by zero. */
export class RationalError extends Error {
  constructor(message) {
    super(message);
    this.name = "RationalError";
  }
}

/**
 * The most digits `parse` takes in the numerator and in the denominator: the cap on the texts of a bundle. Reducing a text costs about the square
 * of its digits (Euclid's algorithm on BigInts, slowest on consecutive Fibonacci numbers): measured here, 1.2 us for 13 digits, 47 us for 64,
 * 0.26 ms for 256 and 43 ms for 4,096; a bundle of 400 texts of 4,096 digits (3.3 MB) took the reader 24 s. The longest text in the sample
 * bundle and in the six bundles of the full set has 6 digits in its numerator and 13 in its denominator (and no test parses a longer one
 * from a fixture), so 64 is a margin of almost five times, and a text longer than that is no rule.
 */
export const MAX_DIGITS = 64;
/** The most digits `parseLong` takes: for the texts that are not in a bundle (a value that `toString` printed, such as an exact result). */
const MAX_LONG_DIGITS = 4096;
/** The longest text `parse` can take: two runs of MAX_DIGITS digits, a sign and a slash. */
export const MAX_TEXT_LENGTH = 2 * MAX_DIGITS + 2;
const CANONICAL = /^(-?[0-9]+)\/([0-9]+)$/;

/** The rational of a reduced "p/q" text of at most `maxDigits` digits in the numerator (not counting its sign) and in the denominator. */
function readText(text, maxDigits) {
  if (typeof text !== "string") throw new RationalError("a rational is written as text, p/q");
  const match = text.length <= 2 * maxDigits + 2 ? CANONICAL.exec(text) : null;
  const signs = match !== null && match[1].charCodeAt(0) === 0x2d ? 1 : 0;
  if (match === null || match[1].length - signs > maxDigits || match[2].length > maxDigits) {
    throw new RationalError(`not a reduced rational p/q: ${JSON.stringify(text.length > 40 ? `${text.slice(0, 40)}...` : text)}`);
  }
  const value = new Rational(BigInt(match[1]), BigInt(match[2]));
  if (value.toString() !== text) throw new RationalError(`not a reduced rational p/q: ${JSON.stringify(text)}`);
  return value;
}

function whole(value, what) {
  if (typeof value === "bigint") return value;
  if (typeof value === "number" && Number.isSafeInteger(value)) return BigInt(value);
  throw new RationalError(`${what} must be a whole number (a BigInt, or a safe integer)`);
}

function gcd(a, b) {
  let x = a < 0n ? -a : a;
  let y = b < 0n ? -b : b;
  while (y !== 0n) {
    const rest = x % y;
    x = y;
    y = rest;
  }
  return x;
}

/** The number of bits of a positive BigInt. */
function bitLength(value) {
  return value.toString(2).length;
}

// 2 to a whole power, built from its bits so that it is exact whatever the engine's pow does: -1074 up to 1023.
const POWER = new DataView(new ArrayBuffer(8));
function powerOfTwo(exponent) {
  if (exponent >= -1022) {
    POWER.setUint32(0, (exponent + 1023) << 20);
    POWER.setUint32(4, 0);
  } else {
    const bit = exponent + 1074; // a subnormal: one bit of the fraction, 0 to 51
    POWER.setUint32(0, bit >= 32 ? 2 ** (bit - 32) : 0);
    POWER.setUint32(4, bit >= 32 ? 0 : 2 ** bit);
  }
  return POWER.getFloat64(0);
}

export class Rational {
  /** `numerator` and `denominator` are BigInts or safe integers; the result is reduced. A zero denominator is refused. */
  constructor(numerator, denominator = 1n) {
    let p = whole(numerator, "the numerator");
    let q = whole(denominator, "the denominator");
    if (q === 0n) throw new RationalError("the denominator is zero");
    if (q < 0n) {
      p = -p;
      q = -q;
    }
    if (p === 0n) {
      q = 1n;
    } else {
      const divisor = gcd(p, q);
      if (divisor !== 1n) {
        p /= divisor;
        q /= divisor;
      }
    }
    this.numerator = p;
    this.denominator = q;
    Object.freeze(this);
  }

  /** The rational of a reduced "p/q" text of a bundle, as `unrat` reads it (at most MAX_DIGITS digits a part); RationalError for anything else. */
  static parse(text) {
    return readText(text, MAX_DIGITS);
  }

  /** As `parse`, for a text that is not in a bundle: up to 4,096 digits a part, which takes some 40 ms to reduce when it is that long. */
  static parseLong(text) {
    return readText(text, MAX_LONG_DIGITS);
  }

  /** A finite double read as the decimal it prints as (so 0.1 is 1/10), as Python's `fr` reads a float. */
  static fromNumber(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) throw new RationalError("a finite number is needed");
    let digits = String(value);
    if (digits.charCodeAt(0) === 0x2d) digits = digits.slice(1);
    const negative = value < 0;
    let exponent = 0;
    const mark = digits.indexOf("e");
    if (mark >= 0) {
      exponent = Number(digits.slice(mark + 1));
      digits = digits.slice(0, mark);
    }
    const point = digits.indexOf(".");
    let decimals = 0;
    if (point >= 0) {
      decimals = digits.length - point - 1;
      digits = digits.slice(0, point) + digits.slice(point + 1);
    }
    const scale = exponent - decimals; // the value is digits x 10^scale
    let numerator = BigInt(digits);
    if (negative) numerator = -numerator;
    return scale >= 0 ? new Rational(numerator * 10n ** BigInt(scale)) : new Rational(numerator, 10n ** BigInt(-scale));
  }

  /** A Rational as it is; a BigInt or a safe integer as the whole number it is. */
  static from(value) {
    return value instanceof Rational ? value : new Rational(value);
  }

  add(other) {
    const that = Rational.from(other);
    return new Rational(this.numerator * that.denominator + that.numerator * this.denominator, this.denominator * that.denominator);
  }

  sub(other) {
    const that = Rational.from(other);
    return new Rational(this.numerator * that.denominator - that.numerator * this.denominator, this.denominator * that.denominator);
  }

  mul(other) {
    const that = Rational.from(other);
    return new Rational(this.numerator * that.numerator, this.denominator * that.denominator);
  }

  div(other) {
    const that = Rational.from(other);
    if (that.numerator === 0n) throw new RationalError("division by zero");
    return new Rational(this.numerator * that.denominator, this.denominator * that.numerator);
  }

  neg() {
    return new Rational(-this.numerator, this.denominator);
  }

  abs() {
    return this.numerator < 0n ? this.neg() : this;
  }

  /** -1, 0 or 1: whether this is below, equal to or above the other. */
  compare(other) {
    const that = Rational.from(other);
    const left = this.numerator * that.denominator;
    const right = that.numerator * this.denominator;
    return left < right ? -1 : left > right ? 1 : 0;
  }

  equals(other) {
    const that = Rational.from(other);
    return this.numerator === that.numerator && this.denominator === that.denominator;
  }

  sign() {
    return this.numerator < 0n ? -1 : this.numerator > 0n ? 1 : 0;
  }

  isInteger() {
    return this.denominator === 1n;
  }

  /** The greatest BigInt not above this (Python's math.floor). */
  floor() {
    const quotient = this.numerator / this.denominator;
    return this.numerator < 0n && this.numerator % this.denominator !== 0n ? quotient - 1n : quotient;
  }

  /** The least BigInt not below this (Python's math.ceil). */
  ceil() {
    const quotient = this.numerator / this.denominator;
    return this.numerator > 0n && this.numerator % this.denominator !== 0n ? quotient + 1n : quotient;
  }

  /**
   * The nearest double, ties to even: the double Python's float(Fraction) gives, subnormals included. A value that rounds past the largest double
   * (from 2^1024 - 2^970 on, in either sign) is a RationalError, as Python's float(Fraction) raises OverflowError there, and one below half the
   * least subnormal is a zero that keeps its sign.
   */
  toNumber() {
    if (this.numerator === 0n) return 0;
    const negative = this.numerator < 0n;
    const top = negative ? -this.numerator : this.numerator;
    const bottom = this.denominator;
    // scale so that the quotient has 55 or 56 bits: two more than a double keeps, and the rest of the division is a single "sticky" test
    const shift = 55 - (bitLength(top) - bitLength(bottom));
    let quotient;
    let rest;
    if (shift >= 0) {
      const scaled = top << BigInt(shift);
      quotient = scaled / bottom;
      rest = scaled % bottom;
    } else {
      const scaled = bottom << BigInt(-shift);
      quotient = top / scaled;
      rest = top % scaled;
    }
    const bits = bitLength(quotient);
    const precision = Math.min(53, bits - 1 - shift + 1075); // the bits the value has room for: fewer among the subnormals
    if (precision < -1) return negative ? -0 : 0;
    const drop = BigInt(bits - precision);
    let mantissa = quotient >> drop;
    const lost = quotient - (mantissa << drop);
    const half = 1n << (drop - 1n);
    if (lost > half || (lost === half && (rest !== 0n || (mantissa & 1n) === 1n))) mantissa += 1n;
    if (mantissa === 0n) return negative ? -0 : 0;
    const exponent = Number(drop) - shift; // the value is mantissa x 2^exponent, and so a multiple of the least subnormal
    const magnitude = exponent > 1023 ? Infinity : Number(mantissa) * powerOfTwo(exponent);
    if (magnitude === Infinity) throw new RationalError("the value is too large for a double (Python's float(Fraction) raises OverflowError there)");
    return negative ? -magnitude : magnitude;
  }

  /** "p/q", reduced, the denominator always there. */
  toString() {
    return `${this.numerator}/${this.denominator}`;
  }

  toJSON() {
    return this.toString();
  }

  /** A Rational has no number to be added or compared with an operator: that would compare the texts. Use `add`, `compare` or `toNumber`. */
  valueOf() {
    throw new RationalError("a Rational has no numeric value for an operator; use add, compare or toNumber");
  }
}

export const ZERO = new Rational(0n);
export const ONE = new Rational(1n);
