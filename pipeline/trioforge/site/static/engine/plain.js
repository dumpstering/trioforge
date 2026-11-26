// Two small functions of plain data that the readers of the engine's data share, in a module with no import: a name from the data made safe to put in a message (`safe`), and the test for plain data
// (`isPlainObject`: an object whose prototype is Object.prototype or null). The item reader, the tier rules and the profile reader need these and nothing else of the evaluator or of the protocol,
// so a lazy chunk that has them (the weights, the Upgrade section) does not pull the evaluator in with them; evaluate.js and protocol.js give them out again under their own names.

/** A name from the data, safe to put in a message: short, and only letters, digits and a few signs (the + of a twin buff set is one). */
export function safe(name) {
  if (typeof name !== "string" || name.length === 0 || name.length > 32) return "?";
  for (let i = 0; i < name.length; i += 1) {
    const code = name.charCodeAt(i);
    if (!((code >= 0x30 && code <= 0x39) || (code >= 0x41 && code <= 0x5a) || (code >= 0x61 && code <= 0x7a) || code === 0x5f || code === 0x2b || code === 0x2d || code === 0x2e)) return "?";
  }
  return name;
}

export function isPlainObject(value) {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}
