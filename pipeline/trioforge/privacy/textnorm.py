"""Text handling for the privacy scanner: digests, tokens, normalization and decoding.

Everything here works on one line of text at a time (except ``tokens`` and
``normalize_for_scan``, which accept several). Functions that change a line also return a map
from each character of the new text to the index of the character it came from, so a finding in
a decoded or normalized view is reported at the column of the original text.
"""

from __future__ import annotations

import binascii
import hmac
import html
import re
import unicodedata
from collections.abc import Iterator
from functools import lru_cache
from urllib.parse import unquote_to_bytes

MIN_TOKEN = 3

# ---- digests and lists --------------------------------------------------------------------


def digest(key: bytes, token: str) -> str:
    """Lowercase hex of HMAC-SHA256(key, token as UTF-8)."""
    return hmac.new(key, token.encode("utf-8", "replace"), "sha256").hexdigest()


def load_list(path) -> set[str]:
    """One entry per line, stripped and lowercased; blank lines and ``#`` comments are skipped."""
    entries: set[str] = set()
    with open(path, encoding="utf-8-sig", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if line and not line.startswith("#"):
                entries.add(line.lower())
    return entries


# ---- lines ----------------------------------------------------------------------------------


def split_lines(text: str) -> list[str]:
    """Split on CRLF, LF or a lone CR. The last element is whatever follows the final break."""
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.split("\n")


# ---- tokens -----------------------------------------------------------------------------------

# For ASCII text, one pattern finds every part of every alphanumeric run: a word in lower case
# that may start with one capital, a run of capitals, and a run of digits. A new part starts
# exactly at a lower -> Upper boundary, at a letter <-> digit boundary, and where a run of two or
# more capitals gives way to lower case, as the rules say.
ASCII_PARTS = re.compile(r"[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
ALNUM_RUN = re.compile(r"[^\W_]+")
# Two or more capitals followed by lower case. The tokenizer cuts such a run where the capitals
# end; the name check also looks at it whole and cut before its last capital (see
# ``capital_run_extras``).
CAPITALS_THEN_LOWER = re.compile(r"[A-Z]{2,}[a-z]+")

_LATIN_NAMES = ("LATIN", "FULLWIDTH LATIN")


@lru_cache(maxsize=4096)
def _is_latin(letter: str) -> bool:
    """Whether a letter belongs to the Latin script (the fullwidth forms count as Latin)."""
    return letter.isascii() or unicodedata.name(letter, "").startswith(_LATIN_NAMES)


def _split_run(run: str) -> list[tuple[int, int]]:
    cuts = [0]
    before = run[0]
    for index in range(1, len(run)):
        after = run[index]
        if (before.islower() and after.isupper()) or before.isalpha() != after.isalpha():
            cuts.append(index)
        elif before.isalpha() and after.isalpha() and _is_latin(before) != _is_latin(after):
            cuts.append(index)  # a change of script: Latin letters against any other
        elif before.isupper() and after.islower() and index >= 2 and run[index - 2].isupper():
            cuts.append(index)  # two or more capitals, then lower case
        before = after
    cuts.append(len(run))
    return list(zip(cuts, cuts[1:]))


def ascii_spans(line: str) -> Iterator[tuple[int, int, str]]:
    for match in ASCII_PARTS.finditer(line):
        start, end = match.span()
        if end - start >= MIN_TOKEN:
            yield start, end, match.group().lower()


def generic_spans(line: str) -> Iterator[tuple[int, int, str]]:
    for run in ALNUM_RUN.finditer(line):
        base = run.start()
        text = run.group()
        for start, end in _split_run(text):
            token = text[start:end].casefold()
            if len(token) >= MIN_TOKEN:
                yield base + start, base + end, token


def token_spans(line: str) -> Iterator[tuple[int, int, str]]:
    """``(start, end, token)`` for each token of one line; start and end are 0-based indexes."""
    return ascii_spans(line) if line.isascii() else generic_spans(line)


def _capital_run_pieces(line: str, start: int, capitals_end: int, end: int):
    """The three extra readings of a run of capitals followed by lower case: the whole run, the
    capitals without the last one, and the last capital with the lower case after it."""
    yield start, end, line[start:end].casefold()
    if capitals_end - 1 - start >= MIN_TOKEN:
        yield start, capitals_end - 1, line[start : capitals_end - 1].casefold()
    yield capitals_end - 1, end, line[capitals_end - 1 : end].casefold()


def capital_run_extras(line: str) -> list[tuple[int, int, str]]:
    """Extra ``(start, end, token)`` readings for each run of two or more capitals followed by
    lower case, such as ``ZOrblax`` (the name with two capitals), ``ZORBLAXBis`` (capitals, then a
    capitalised word) and ``ZORBLAXgear``. The tokens of ``tokens`` cut such a run where the
    capitals end; a name check that looked only at those would miss the first two forms."""
    found: list[tuple[int, int, str]] = []
    if line.isascii():
        for match in CAPITALS_THEN_LOWER.finditer(line):
            start, end = match.span()
            text = match.group()
            capitals = len(text) - len(text.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
            found.extend(_capital_run_pieces(line, start, start + capitals, end))
        return found
    for run in ALNUM_RUN.finditer(line):
        base = run.start()
        text = run.group()
        size = len(text)
        index = 0
        while index < size:
            if not text[index].isupper():
                index += 1
                continue
            stop = index
            while stop < size and text[stop].isupper():
                stop += 1
            if stop - index >= 2 and stop < size and text[stop].islower():
                end = stop
                while end < size and text[end].islower():
                    end += 1
                found.extend(_capital_run_pieces(line, base + index, base + stop, base + end))
                index = end
            else:
                index = stop
    return found


def tokens(text: str, first_line: int = 1) -> Iterator[tuple[int, int, str]]:
    """Yield ``(line, column, token)``; lines and columns are 1-based.

    Tokens are the pieces left by splitting on every non-alphanumeric character, on lower ->
    Upper camelCase boundaries, on letter <-> digit boundaries, where a run of two or more
    capitals gives way to lower case (``ZORBLAXgear`` is ``zorblax`` and ``gear``), and where the
    script changes between Latin letters and any other; they are case-folded, and those shorter
    than three characters are dropped. A name written with its capitals scattered, such as
    ``zOrBlAx``, is a known limit: it is not one token. For a path, pass the path as the text and
    ``first_line=0``.
    """
    for offset, line in enumerate(split_lines(text)):
        for start, _end, token in token_spans(line):
            yield first_line + offset, start + 1, token


# ---- normalization ----------------------------------------------------------------------------

_CONFUSABLE_PAIRS = {
    # Cyrillic lower case, then upper case
    "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c",
    "\u0443": "y", "\u0445": "x", "\u043a": "k", "\u043c": "m", "\u0442": "t",
    "\u0432": "b", "\u043d": "h", "\u0456": "i", "\u0458": "j", "\u0455": "s",
    "\u0410": "A", "\u0415": "E", "\u041e": "O", "\u0420": "P", "\u0421": "C",
    "\u0423": "Y", "\u0425": "X", "\u041a": "K", "\u041c": "M", "\u0422": "T",
    "\u0412": "B", "\u041d": "H", "\u0406": "I", "\u0408": "J", "\u0405": "S",
    # Cyrillic and Latin letters that only look like a Latin letter
    "\u0501": "d", "\u04bb": "h", "\u04cf": "l", "\u051b": "q", "\u051d": "w",
    "\u0475": "v", "\u0251": "a", "\u0261": "g", "\u0131": "i", "\u0237": "j",
    # Greek lower case, then upper case
    "\u03b1": "a", "\u03b2": "b", "\u03b5": "e", "\u03b9": "i", "\u03ba": "k",
    "\u03bd": "v", "\u03bf": "o", "\u03c1": "p", "\u03c4": "t", "\u03c5": "u",
    "\u03c7": "x",
    "\u0391": "A", "\u0392": "B", "\u0395": "E", "\u0399": "I", "\u039a": "K",
    "\u039d": "N", "\u039f": "O", "\u03a1": "P", "\u03a4": "T", "\u03a5": "Y",
    "\u03a7": "X", "\u0396": "Z", "\u0397": "H", "\u039c": "M",
}
_CONFUSABLES = str.maketrans(_CONFUSABLE_PAIRS)

_NON_ASCII = re.compile(r"[^\x00-\x7f]+")


_CACHE_LIMIT = 64  # only short runs are cached, so one huge run cannot fill the cache


def _normalize_text(run: str) -> str:
    """The Unicode steps of ``normalize_for_scan`` on text that holds no line breaks."""
    text = unicodedata.normalize("NFKC", run)
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", text).translate(_CONFUSABLES)


_normalize_cached = lru_cache(maxsize=16384)(_normalize_text)


def _normalize_run(run: str) -> str:
    return _normalize_cached(run) if len(run) <= _CACHE_LIMIT else _normalize_text(run)


def _map_text(run: str) -> tuple[str, tuple[int, ...]]:
    """Like ``_normalize_run``, plus for each output character the index of the input
    character (or combining sequence) it came from."""
    whole = _normalize_run(run)
    pieces = []
    origin: list[int] = []
    start = 0
    for index in range(1, len(run) + 1):
        if index == len(run) or unicodedata.combining(run[index]) == 0:
            piece = _normalize_run(run[start:index])
            pieces.append(piece)
            origin.extend([start] * len(piece))
            start = index
    if "".join(pieces) == whole:
        return whole, tuple(origin)
    return whole, (0,) * len(whole)  # a sequence that only works as a whole: coarse positions


_map_cached = lru_cache(maxsize=16384)(_map_text)


def _normalize_run_mapped(run: str) -> tuple[str, tuple[int, ...]]:
    return _map_cached(run) if len(run) <= _CACHE_LIMIT else _map_text(run)


def _origins(imap, start: int, stop: int):
    if imap is None:
        return range(start, stop)
    return imap[start:stop]


def normalize_unicode(text: str, imap=None):
    """NFKC, drop format characters (Cf), NFKD, drop combining marks (Mn), recompose, and fold
    look-alike Cyrillic and Greek letters to Latin. Returns ``(text, imap)``."""
    if text.isascii():
        return text, imap
    out: list[str] = []
    origin: list[int] = []
    position = 0
    for match in _NON_ASCII.finditer(text):
        start, end = match.span()
        if start > position:
            out.append(text[position:start])
            origin.extend(_origins(imap, position, start))
        normalized, relative = _normalize_run_mapped(match.group())
        out.append(normalized)
        if imap is None:
            origin.extend(start + r for r in relative)
        else:
            origin.extend(imap[start + r] for r in relative)
        position = end
    out.append(text[position:])
    origin.extend(_origins(imap, position, len(text)))
    result = "".join(out)
    if result == text:
        return text, imap
    return result, origin


# What a line may end with when a word is hyphenated across the break: hyphen-minus, hyphen,
# non-breaking hyphen and soft hyphen (text copied from a PDF or a word processor has the last
# three).
WRAP_HYPHENS = "-" + chr(0x2010) + chr(0x2011) + chr(0xAD)
_EMPHASIS = re.compile(r"(?<=[^\W\d_])[*_`]+(?=[^\W\d_])")
_WRAP = re.compile(
    r"(?<=[^\W\d_])[" + re.escape(WRAP_HYPHENS) + r"][ \t]*(?:\r\n|\n|\r)[ \t]*(?=[^\W\d_])"
)


def remove_emphasis(text: str, imap=None):
    """Remove ``*``, ``_`` and backtick runs that sit between two letters."""
    if "*" not in text and "_" not in text and "`" not in text:
        return text, imap
    out: list[str] = []
    origin: list[int] = []
    position = 0
    for match in _EMPHASIS.finditer(text):
        start, end = match.span()
        out.append(text[position:start])
        origin.extend(_origins(imap, position, start))
        position = end
    if not out and position == 0:
        return text, imap
    out.append(text[position:])
    origin.extend(_origins(imap, position, len(text)))
    return "".join(out), origin


def normalize_for_scan(text: str) -> str:
    """The text as the scanner reads it: hyphenated line wraps joined, Unicode folded (see
    ``normalize_unicode``), and emphasis markers between two letters removed. The wraps are
    joined first because folding would drop a soft hyphen, which is one way to hyphenate."""
    if "\n" in text or "\r" in text:
        text = _WRAP.sub("", text)
    text, _ = normalize_unicode(text)
    return _EMPHASIS.sub("", text) if ("*" in text or "_" in text or "`" in text) else text


def normalize_for_scan_mapped(text: str) -> tuple[str, list[int]]:
    """``normalize_for_scan``, and for each character of the result the index in ``text`` of the
    character it came from. A finding in the folded text can be located, and hidden, at the
    original span. A character that stands for several (a folded ligature) points at the first;
    one that was joined across a line wrap points at its own place after the wrap."""
    imap = None
    if "\n" in text or "\r" in text:
        out: list[str] = []
        origin: list[int] = []
        position = 0
        for match in _WRAP.finditer(text):
            start, end = match.span()
            out.append(text[position:start])
            origin.extend(range(position, start))
            position = end
        out.append(text[position:])
        origin.extend(range(position, len(text)))
        text, imap = "".join(out), origin
    text, imap = normalize_unicode(text, imap)
    text, imap = remove_emphasis(text, imap)
    return text, list(range(len(text))) if imap is None else list(imap)


# ---- decoding passes ------------------------------------------------------------------------

_ESCAPE = re.compile(
    r"&(?:#[0-9]{1,8};?|#[xX][0-9a-fA-F]{1,8};?|[A-Za-z][A-Za-z0-9]{1,31};)"
    r"|(?:%[0-9a-fA-F]{2})+"
    r"|\\u[dD][89abAB][0-9a-fA-F]{2}\\u[dD][c-fC-F][0-9a-fA-F]{2}"
    r"|\\u\{[0-9a-fA-F]{1,6}\}|\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8}|\\x[0-9a-fA-F]{2}"
    r"|\\[nrtbfv0\"'\\/]"
)
_SIMPLE_ESCAPES = {
    "n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0",
    '"': '"', "'": "'", "\\": "\\", "/": "/",
}


def _code_point(value: int) -> str:
    return chr(value) if value <= 0x10FFFF else "\ufffd"


def _decode_escape(match: re.Match[str]) -> str:
    text = match.group()
    lead = text[0]
    if lead == "&":
        return html.unescape(text)
    if lead == "%":
        return unquote_to_bytes(text).decode("utf-8", "replace")
    kind = text[1]
    if kind == "u":
        if text[2] == "{":
            return _code_point(int(text[3:-1], 16))
        if len(text) == 12:  # a surrogate pair
            high, low = int(text[2:6], 16), int(text[8:12], 16)
            return chr(0x10000 + ((high - 0xD800) << 10) + (low - 0xDC00))
        return chr(int(text[2:6], 16))
    if kind == "U":
        return _code_point(int(text[2:], 16))
    if kind == "x":
        return chr(int(text[2:], 16))
    return _SIMPLE_ESCAPES[kind]


def escape_end(text: str, index: int) -> int | None:
    """The end of the escape sequence that starts at ``index`` of ``text``, or None if none does
    (a decoded character is mapped to the start of its escape; this finds the rest of it)."""
    match = _ESCAPE.match(text, index)
    return match.end() if match else None


def decode_escapes(text: str, imap=None):
    """Decode HTML entities, URL escapes and JSON/JavaScript escapes (one level)."""
    if "&" not in text and "%" not in text and "\\" not in text:
        return text, imap
    out: list[str] = []
    origin: list[int] = []
    position = 0
    changed = False
    for match in _ESCAPE.finditer(text):
        start, end = match.span()
        replacement = _decode_escape(match)
        if replacement == match.group():
            continue
        changed = True
        out.append(text[position:start])
        origin.extend(_origins(imap, position, start))
        out.append(replacement)
        source = start if imap is None else imap[start]
        origin.extend([source] * len(replacement))
        position = end
    if not changed:
        return text, imap
    out.append(text[position:])
    origin.extend(_origins(imap, position, len(text)))
    return "".join(out), origin


# Runs of base64 characters (standard or URL-safe alphabet), padded or not. A run longer than one
# window is decoded in overlapping windows, each starting at a multiple of four characters of the
# run, so that a name that crosses the end of one window lies whole in the next.
_BASE64 = re.compile(r"[A-Za-z0-9+/_-]{8,}={0,2}")
_URLSAFE_TO_STANDARD = str.maketrans("-_", "+/")
_PRINTABLE = bytes(range(0x20, 0x7F)) + b"\t\n\r"
_BASE64_WINDOW = 4096
_BASE64_OVERLAP = 64
_BASE64_STEP = _BASE64_WINDOW - _BASE64_OVERLAP  # a multiple of four
_BASE64_CACHE_RUN = 256  # only runs up to this long are remembered ...
_BASE64_CACHE_SIZE = 20000  # ... and at most this many of them
_base64_cache: dict[str, str | None] = {}


def _decode_base64(core: str) -> str | None:
    """The text a run of base64 decodes to, or None if it is not mostly printable ASCII."""
    if core in _base64_cache:
        return _base64_cache[core]
    result = None
    if len(core) % 4 != 1:
        padded = core.translate(_URLSAFE_TO_STANDARD) + "=" * (-len(core) % 4)
        try:
            data = binascii.a2b_base64(padded, strict_mode=True)
        except (binascii.Error, ValueError):
            data = b""
        if len(data) >= 4:
            unprintable = len(data.translate(None, _PRINTABLE))
            if unprintable * 10 <= len(data):
                result = data.decode("ascii", "replace")
    if len(core) <= _BASE64_CACHE_RUN:  # long runs are rare; do not let them fill the cache
        if len(_base64_cache) > _BASE64_CACHE_SIZE:
            _base64_cache.clear()
        _base64_cache[core] = result
    return result


def base64_spans(text: str) -> list[tuple[int, int, str]]:
    """``(start, end, decoded)`` for each run of 8 or more base64 characters that decodes to at
    least 90% printable ASCII; ``start`` and ``end`` are the run's. A run longer than 4,096
    characters comes back once per window that decodes, with the same ``start``. Every run is
    tried, whatever case its letters are in."""
    found = []
    for match in _BASE64.finditer(text):
        core = match.group().rstrip("=")
        start, end = match.start(), match.start() + len(core)
        if len(core) <= _BASE64_WINDOW:
            decoded = _decode_base64(core)
            if decoded is not None:
                found.append((start, end, decoded))
            continue
        for offset in range(0, len(core), _BASE64_STEP):
            window = core[offset : offset + _BASE64_WINDOW]
            if len(window) % 4 == 1:
                window = window[:-1]  # a lone last character is not a whole group
            if len(window) >= 8:
                decoded = _decode_base64(window)
                if decoded is not None:
                    found.append((start, end, decoded))
            if offset + _BASE64_WINDOW >= len(core):
                break
    return found


def base64_segments(text: str) -> list[tuple[int, str]]:
    """``(start, decoded)`` for each base64 run (or window of one) that decodes to text; see
    ``base64_spans``."""
    return [(start, decoded) for start, _end, decoded in base64_spans(text)]


# ---- hashes ----------------------------------------------------------------------------------

# A hash is not a word: its letters would only ever match a name by accident. Blanked are runs of
# 16 or more hex digits that are all in one case (digests, commit ids) and package-lock style
# integrity values ("sha512-" followed by base64). A run that mixes cases is not a digest: it is
# letters that may well be a name.
_HASH_RUN = re.compile(
    r"(?P<hex>[0-9A-Fa-f]{16,})"
    r"|(?P<integrity>(?i:sha(?:1|224|256|384|512))-[A-Za-z0-9+/]{16,}={0,2})"
)


def _blank_hash(match: re.Match[str]) -> str:
    text = match.group()
    if match.group("hex") is not None and text != text.lower() and text != text.upper():
        return text
    return " " * len(text)


def blank_hex(text: str) -> str:
    """Replace each hash in ``text`` by spaces, keeping the length, so the letters in it are not
    read as words."""
    if len(text) < 16 or _HASH_RUN.search(text) is None:
        return text
    return _HASH_RUN.sub(_blank_hash, text)
