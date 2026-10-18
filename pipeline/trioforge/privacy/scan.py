"""The privacy scanner: keeps private names and game-log text out of the repository.

Two kinds of check run over every file (and over commit messages, ref names and history):

* a **denylist** of private names, stored as keyed digests (HMAC-SHA256). The key is not in the
  repository, so the digests cannot be used to test guesses. Text is split into tokens and each
  token is hashed and looked up. Before that the text is read in several forms (as written,
  with encodings undone, with look-alike characters folded) so a disguised name is still found.
* **content rules** (see ``logshape``): text that looks like a line from a game log, a path into
  a user's profile folder, and words that point at the game client's program file. These need no
  key.
* **rules about the maintainer's private "seen in game" flags**, which need no key either, so CI
  runs them: a file named ``seen-flags.json`` (``seen-flags``), a tracked path with a ``build``
  folder in it, where a build made with those flags is allowed to go and which git ignores
  (``build-path``), a ``.json`` file that holds a reason with the code the catalog builder gives to
  an item the maintainer has seen (``seen-reason``), and the private exporter's output under any
  name: a JSON object of exactly ``version``, ``license`` and ``keys``, whose keys are item keys
  (``seen-export``).

Besides the files, the scan covers commit messages, every blob in history, branch and tag names,
who made each commit (one allowed address, all dates in UTC) and, for a push, exactly what is
about to be sent. Git is always run without replacement objects, and a git process that fails, or
an object that comes back short, is an error, never a clean result.

Nothing the scanner prints ever contains a matched token, a matched line or an e-mail address:
a finding is reported as ``path:line:column: rule [tag]`` where the tag is the first 8 hex digits
of the digest, and a path is printed with its private tokens replaced. Without a key no name can
be recognised, so a path is then printed as a hash of itself.

Run it as ``python -m trioforge.privacy.scan``; exit code 0 is clean, 1 means findings and 2 is a
configuration error. See ``main`` for the options.
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import itertools
import json
import os
import re
import stat
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import NamedTuple

from . import logshape
from .gitio import BatchReader, FileReadError, Git, ScanError, decode_name, iter_pairs
from .masker import PhraseMasker
from .textnorm import (
    ASCII_PARTS,
    CAPITALS_THEN_LOWER,
    WRAP_HYPHENS,
    base64_segments,
    base64_spans,
    blank_hex,
    capital_run_extras,
    decode_escapes,
    digest,
    escape_end,
    generic_spans,
    load_list,
    normalize_for_scan,
    normalize_for_scan_mapped,
    normalize_unicode,
    remove_emphasis,
    split_lines,
    tokens,
)

__all__ = [
    "Finding",
    "FileReadError",
    "PhraseMasker",
    "ScanError",
    "check_identity",
    "digest",
    "load_catalog_phrases",
    "load_line_allow",
    "load_list",
    "main",
    "mask_path",
    "normalize_for_scan",
    "normalize_for_scan_mapped",
    "scan_bytes",
    "scan_history",
    "scan_paths",
    "scan_text",
    "tokens",
]

# Files are read in chunks of this many bytes; a chunk is decoded and cut into lines, and the
# unfinished last line is carried over to the next chunk.
CHUNK_SIZE = 1 << 20
# How much of the start of a file decides whether it is text, UTF-16 or binary.
SAMPLE_SIZE = 8192
# A line longer than this is scanned in pieces, so one huge line cannot fill the memory.
MAX_LINE = 1 << 20
# After this many findings in one file the scan of that file stops.
MAX_FINDINGS_PER_FILE = 10_000
# The set of tokens known to be harmless is emptied when it grows past this size.
CLEAN_CACHE_LIMIT = 200_000
# A line is decoded and folded for at most this many rounds (an encoding may hold another).
DECODE_ROUNDS = 6

# Where the maintainer keeps the key when neither --key-file nor TRIOFORGE_PRIVACY_KEY is given.
# Built from the home folder, so the public source names no user and no drive.
DEFAULT_KEY_FILE = os.path.join(os.path.expanduser("~"), "eql", "private", "privacy.key")
KEY_CHECK_TEXT = "trioforge-key-check"
SEEN_FLAGS_NAME = "seen-flags.json"
# The folder a build made with the private seen flags is written to; git ignores it, so nothing in it is tracked.
BUILD_FOLDER = "build"
# A file with one of these endings is JSON, and may not hold a reason with the code of a seen item.
JSON_SUFFIXES = (".json", ".jsonl", ".ndjson")
# The reason the catalog builder writes for an item seen in game: its code as the value of a "code" member.
# The code is followed by a quote, a colon (a suffix) or a backslash (an escape); a longer word is another code.
SEEN_REASON = re.compile(r'"code"\s*:\s*"seen-in-game(?=["\\:])', re.IGNORECASE)
# The private exporter writes an object of exactly these members, with a list of item keys as the "keys".
EXPORT_FIELDS = frozenset({"version", "license", "keys"})
ITEM_KEY = re.compile(r"(?:w[0-9]{1,15}|r[a-z0-9][a-z0-9-]{0,99})")  # the shape of a catalog item key
# A file is read whole for the exporter's shape only up to this size: its output is a few hundred kilobytes at most.
SHAPE_LIMIT = 2 << 20
ARCHIVE_EXTENSIONS = (".zip", ".gz", ".tgz", ".tar", ".7z", ".rar", ".bz2", ".xz", ".zst")
# A zip local-file header anywhere in this many leading bytes makes a file an archive: a zip can
# follow a program stub or other text, and Office and OpenDocument files are zips.
ARCHIVE_WINDOW = 1 << 16
ZIP_LOCAL_HEADER = b"PK\x03\x04"
# A PDF is refused whole, by its name or by the marker that opens it (which may follow a few
# bytes of junk).
PDF_EXTENSIONS = (".pdf",)
PDF_MAGIC = b"%PDF-"
PDF_WINDOW = 1024
LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1"
EXPLAIN_BLOCKERS = (
    "CI",
    "GITHUB_ACTIONS",
    "TF_BUILD",
    "BUILDKITE",
    "GITLAB_CI",
    "JENKINS_URL",
    "DRONE",
    "CIRCLECI",
    "TRAVIS",
    "APPVEYOR",
)
COMMIT_MSG_PATH = "<commit-msg>"
LABEL_PREFIXES_WITHOUT_NAMES = ("<commit:", "<tag:", "<identity:")


class Finding(NamedTuple):
    """One thing the scan found. ``tag`` is the first 8 hex digits of the digest for a
    ``denylist`` finding and ``-`` for every other rule; ``line`` is 0 for the path itself."""

    path: str
    line: int
    col: int
    rule: str
    tag: str


class NotRegular(Exception):
    """Raised by a reader for a file that must not be opened (a FIFO, a device, ...)."""


# ---- hashing -------------------------------------------------------------------------------


class _Mac:
    """HMAC-SHA256 with the key's two pad blocks hashed once; much faster per token."""

    def __init__(self, key: bytes) -> None:
        if len(key) > 64:
            key = hashlib.sha256(key).digest()
        key = key.ljust(64, b"\0")
        self._inner = hashlib.sha256(bytes(b ^ 0x36 for b in key))
        self._outer = hashlib.sha256(bytes(b ^ 0x5C for b in key))

    def __call__(self, data: bytes) -> bytes:
        inner = self._inner.copy()
        inner.update(data)
        outer = self._outer.copy()
        outer.update(inner.digest())
        return outer.digest()


def _digest_bytes(entries: Iterable[str] | None) -> set[bytes]:
    found = set()
    for entry in entries or ():
        try:
            raw = bytes.fromhex(entry)
        except (ValueError, TypeError):
            continue
        if len(raw) == 32:
            found.add(raw)
    return found


def _as_masker(phrases) -> PhraseMasker | None:
    if phrases is None or isinstance(phrases, PhraseMasker):
        return phrases
    return PhraseMasker(phrases)


class _Ctx:
    """What one scan run shares between files: the lists, the key and the token caches."""

    def __init__(self, key, deny, allow, phrases, line_allow, explain) -> None:
        self.explain = explain
        self.line_allow = line_allow or frozenset()
        self.masker = _as_masker(phrases)
        deny_bytes = _digest_bytes(deny)
        self.deny = deny_bytes
        self.allow = _digest_bytes(allow)
        self.mac = _Mac(key) if key is not None and deny_bytes else None
        if self.masker is not None and self.mac is not None:
            # A public name that is one denylisted word must not hide that word.
            self.masker = self.masker.without_private_single_tokens(self._is_private)
        self.clean: set[str] = set()  # ASCII parts known not to be denylisted
        self.hit_map: dict[str, str] = {}  # ASCII part -> digest (hex) of a denylisted part
        self.token_cache: dict[str, str] = {}  # folded token -> digest (hex) or ""

    # -- the denylist lookup ------------------------------------------------------------

    def _is_private(self, token: str) -> bool:
        return self.mac(token.encode("utf-8", "replace")) in self.deny

    def hits(self, text: str) -> list[tuple[int, int, str, str]]:
        """``(start, end, token, digest)`` for each denylisted token of one line of text."""
        if self.mac is None:
            return []
        found = self._ascii_hits(text) if text.isascii() else self._generic_hits(text)
        if found and self.masker is not None and len(self.masker):
            masked = self.masker.mask(text)
            found = [hit for hit in found if masked[hit[0]] == text[hit[0]]]
        return found

    def _ascii_hits(self, text: str):
        parts = ASCII_PARTS.findall(text)
        if not parts:
            return ()
        # Runs of capitals followed by lower case are also read whole and cut before the last
        # capital (see ``capital_run_extras``); such lines are rare.
        extras = capital_run_extras(text) if CAPITALS_THEN_LOWER.search(text) else ()
        keys = parts + [token for _start, _end, token in extras] if extras else parts
        clean = self.clean
        if clean.issuperset(keys):
            return ()
        hit_map = self.hit_map
        for part in set(keys).difference(clean):
            if part in hit_map:
                continue
            token = part.lower()
            if len(token) < 3:
                clean.add(part)
                continue
            value = self.mac(token.encode("ascii"))
            if value in self.deny and value not in self.allow:
                hit_map[part] = value.hex()
            else:
                if len(clean) > CLEAN_CACHE_LIMIT:
                    clean.clear()
                clean.add(part)
        if not hit_map or hit_map.keys().isdisjoint(keys):
            return ()
        found = []
        for match in ASCII_PARTS.finditer(text):
            value = hit_map.get(match.group())
            if value is not None:
                found.append((match.start(), match.end(), match.group().lower(), value))
        for start, end, token in extras:
            value = hit_map.get(token)
            if value is not None:
                found.append((start, end, token, value))
        return found

    def _generic_hits(self, text: str):
        found = []
        cache = self.token_cache
        for start, end, token in itertools.chain(generic_spans(text), capital_run_extras(text)):
            value = cache.get(token)
            if value is None:
                raw = self.mac(token.encode("utf-8", "replace"))
                value = raw.hex() if raw in self.deny and raw not in self.allow else ""
                if len(cache) > CLEAN_CACHE_LIMIT:
                    cache.clear()
                cache[token] = value
            if value:
                found.append((start, end, token, value))
        return found


# ---- scanning one file or text ---------------------------------------------------------------

_HEX16 = re.compile(r"[0-9A-Fa-f]{16}")


def _needs_variants(line: str) -> bool:
    """Whether an ASCII line might need decoding, emphasis removal or hash blanking. Nearly every
    line does not, and for those the line is checked as it stands."""
    return (
        "&" in line
        or "%" in line
        or "\\" in line
        or "*" in line
        or "_" in line
        or "`" in line
        or _HEX16.search(line) is not None
        or "sha" in line.lower()
    )


_LEAD_WORD = re.compile(r"[ \t]*([^\W\d_]+)")
_TRAIL_WORD = re.compile(r"([^\W\d_]+)[" + re.escape(WRAP_HYPHENS) + r"][ \t]*\Z")
_WRAP_END = WRAP_HYPHENS + " \t"
_STRINGS = re.compile(rb"[\x20-\x7e\t]{4,}")
_PRINTABLE_SET = bytes(range(0x20, 0x7F)) + b"\t"
_BZIP2 = re.compile(rb"BZh[1-9]\x31\x41\x59\x26\x53\x59")
_ARCHIVE_MAGIC = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"\x1f\x8b\x08",
    b"\xfd7zXZ\x00",
    b"\x28\xb5\x2f\xfd",
    b"7z\xbc\xaf\x27\x1c",
    b"Rar!\x1a\x07",
)


def _is_archive(head: bytes) -> bool:
    return (
        head.startswith(_ARCHIVE_MAGIC)
        or _BZIP2.match(head) is not None
        or head[257:262] == b"ustar"
    )


def _has_build_folder(path: str) -> bool:
    """Whether a part of the path is ``build`` (in any case, and with the dots and spaces Windows ignores
    at the end of a name)."""
    return any(part.casefold().rstrip(" .") == BUILD_FOLDER for part in re.split(r"[\\/]", path))


def _is_export(document: object) -> bool:
    """Whether a parsed JSON document has the shape of the private exporter's output."""
    if not isinstance(document, dict) or set(document) != EXPORT_FIELDS:
        return False
    keys = document["keys"]
    return isinstance(keys, list) and all(isinstance(key, str) and ITEM_KEY.fullmatch(key) for key in keys)


def _guess_utf16(sample: bytes) -> str | None:
    """UTF-16 without a BOM: almost every second byte is NUL, and not every byte is."""
    usable = len(sample) // 2 * 2
    if usable < 4:
        return None
    even, odd = sample[0:usable:2], sample[1:usable:2]
    even_nul = even.count(0) / len(even)
    odd_nul = odd.count(0) / len(odd)
    if odd_nul >= 0.9 and even_nul < 0.5:
        return "utf-16-le"
    if even_nul >= 0.9 and odd_nul < 0.5:
        return "utf-16-be"
    return None


def _detect_encoding(head: bytes) -> tuple[str | None, bytes]:
    """``(encoding, bytes to decode)``; the encoding is None for binary content."""
    if head.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return "utf-32", head
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16", head
    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8", head[3:]
    sample = head[:SAMPLE_SIZE]
    if b"\0" not in sample:
        return "utf-8", head
    return _guess_utf16(sample), head


def _chunks(source) -> Iterator[bytes]:
    """Yield the content of ``source`` (bytes or a file-like object) in chunks. The first chunk
    is at least ``SAMPLE_SIZE`` bytes unless the content is shorter. A file-like source is
    closed when the generator finishes."""
    first = max(CHUNK_SIZE, SAMPLE_SIZE)
    if isinstance(source, (bytes, bytearray, memoryview)):
        view = memoryview(source)
        position, size = 0, first
        while position < len(view):
            yield bytes(view[position : position + size])
            position += size
            size = CHUNK_SIZE
        return
    try:
        started = False
        while True:
            chunk = source.read(CHUNK_SIZE if started else first)
            if not chunk:
                break
            if not started:
                while len(chunk) < first:
                    more = source.read(first - len(chunk))
                    if not more:
                        break
                    chunk += more
                started = True
            yield chunk
    finally:
        close = getattr(source, "close", None)
        if close is not None:
            close()


def _variants(line: str) -> list[tuple[str, list[int] | None]]:
    """The forms of one line to check: as written; with encodings undone and Unicode folded,
    each step after the other until nothing changes; and each of those with emphasis markers
    between letters removed. Each carries a map from its characters to the characters of ``line``
    (None means the same positions).

    Undoing an encoding can leave characters that fold into a new escape (a fullwidth percent
    sign), folding can leave an escape that now decodes, and an escape can hold another (%2562 is
    %62 is b). So the two steps alternate, for at most ``DECODE_ROUNDS`` rounds."""
    views: list[tuple[str, list[int] | None]] = [(line, None)]
    seen = {line}

    def add(text: str, imap) -> None:
        if text not in seen:
            views.append((text, imap))
            seen.add(text)

    text, imap = line, None
    for _round in range(DECODE_ROUNDS):  # encodings inside encodings, one level at a time
        decoded, decoded_map = decode_escapes(text, imap)
        if decoded == text:
            break
        add(decoded, decoded_map)
        text, imap = decoded, decoded_map
    for text, imap in list(views):  # each of those, folded
        add(*normalize_unicode(text, imap))
    text, imap = line, None
    for _round in range(DECODE_ROUNDS):  # decoding and folding, taken in turns until both rest
        changed = False
        for step in (decode_escapes, normalize_unicode):
            stepped, stepped_map = step(text, imap)
            if stepped != text:
                changed = True
                text, imap = stepped, stepped_map
                add(text, imap)
        if not changed:
            break
    for text, imap in list(views):
        plain, plain_map = remove_emphasis(text, imap)
        if plain not in seen:
            views.append((plain, plain_map))
            seen.add(plain)
    return views


class _FileScan:
    """The scan of one file (or one message, ref name or similar): collects its findings."""

    def __init__(self, ctx: _Ctx, path: str) -> None:
        self.ctx = ctx
        self.path = path
        self.json = path.casefold().endswith(JSON_SUFFIXES)
        self.found: dict[tuple[int, int, str, str], str] = {}
        self.pending: tuple[int, int, str] | None = None  # a word split by a hyphen at line end
        self.full = False

    # -- findings -------------------------------------------------------------------------

    def add(self, line: int, col: int, rule: str, tag: str, text: str = "") -> None:
        key = (line, col, rule, tag)
        if key in self.found:
            return
        if len(self.found) >= MAX_FINDINGS_PER_FILE:
            self.full = True
            return
        self.found[key] = text

    def results(self) -> list[Finding]:
        out = []
        for (line, col, rule, tag), text in sorted(self.found.items()):
            finding = Finding(self.path, line, col, rule, tag)
            out.append(finding)
            if self.ctx.explain is not None and text:
                self.ctx.explain[finding] = text
        return out

    # -- the path ---------------------------------------------------------------------------

    def path_checks(self) -> bool:
        """Check the path itself. Returns False if the content must not be read."""
        proceed = True
        name = re.split(r"[\\/]", self.path)[-1]
        if name.casefold() == SEEN_FLAGS_NAME:
            self.add(0, 0, "seen-flags", "-")
            proceed = False
        if _has_build_folder(self.path):  # the content is still read: a name in it is found as well
            self.add(0, 0, "build-path", "-")
        if self.path.casefold().endswith(ARCHIVE_EXTENSIONS):
            self.add(0, 0, "archive", "-")
            proceed = False
        if self.path.casefold().endswith(PDF_EXTENSIONS):
            self.add(0, 0, "pdf", "-")
            proceed = False
        self.line(0, self.path, 0, logshape_on=False, wrap=False)
        return proceed

    # -- lines --------------------------------------------------------------------------------

    def line(
        self,
        number: int,
        line: str,
        offset: int = 0,
        *,
        logshape_on: bool = True,
        wrap: bool = True,
    ) -> None:
        """Check one line. ``offset`` is the number of characters of this physical line that came
        before ``line`` (when a very long line is scanned in pieces)."""
        if self.full:
            return
        if line:
            if line.isascii() and not _needs_variants(line):
                self._view(number, line, None, offset, line, logshape_on, False)
            else:
                for text, imap in _variants(line):
                    self._view(number, text, imap, offset, line, logshape_on, True)
            if len(line) >= 8:
                for start, decoded in base64_segments(line):
                    imap = [start] * len(decoded)  # every decoded character: the run's start
                    self._view(number, decoded, imap, offset, line, logshape_on, True)
        if wrap:
            self._wrap(number, line, offset)

    def _view(self, number, text, imap, offset, raw, logshape_on, check_hex) -> None:
        ctx = self.ctx
        if logshape_on:
            for rule, start, end in logshape.find(text):
                self._log_finding(number, text, imap, offset, raw, rule, start, end)
            if self.json:
                for match in SEEN_REASON.finditer(text):
                    column = (imap[match.start()] if imap is not None else match.start()) + 1 + offset
                    self.add(number, column, "seen-reason", "-", match.group())
        if ctx.mac is not None:
            subject = blank_hex(text) if check_hex else text
            for start, _end, token, value in ctx.hits(subject):
                column = (imap[start] if imap is not None else start) + 1 + offset
                self.add(number, column, "denylist", value[:8], token)

    def _log_finding(self, number, text, imap, offset, raw, rule, start, end) -> None:
        ctx = self.ctx
        if ctx.line_allow:
            digest_of_line = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()
            if (self.path, rule, digest_of_line) in ctx.line_allow:
                return
        column = (imap[start] if imap is not None else start) + 1 + offset
        self.add(number, column, rule, "-", text[start:end])

    def _wrap(self, number: int, line: str, offset: int) -> None:
        """Join a word split over two lines by a hyphen (``Zor-`` / ``blax``) and check it."""
        pending, self.pending = self.pending, None
        if pending is not None:
            lead = _LEAD_WORD.match(line)
            if lead:
                self._joined(pending, lead.group(1))
        if line and line[-1] in _WRAP_END:
            stripped = line.rstrip(" \t")
            if stripped and stripped[-1] in WRAP_HYPHENS:
                tail = line[-256:]
                match = _TRAIL_WORD.search(tail)
                if match:
                    column = offset + len(line) - len(tail) + match.start(1) + 1
                    self.pending = (number, column, match.group(1))

    def _joined(self, pending: tuple[int, int, str], first: str) -> None:
        number, column, partial = pending
        for text, imap in _variants(partial + first):
            for start, _end, token, value in self.ctx.hits(blank_hex(text)):
                where = column + (imap[start] if imap is not None else start)
                self.add(number, where, "denylist", value[:8], token)

    # -- content --------------------------------------------------------------------------------

    def scan_content(self, source) -> None:
        """Scan the content.

        A file that is not an archive, an LFS pointer or a PDF is read as text when it is UTF-8
        or UTF-16 (decoded, line by line). Anything else is binary and is read as the runs of
        printable characters in it, as ASCII and as UTF-16 in either byte order. A file whose
        byte order mark or whose content looks like UTF-16 gets the same runs checked as well,
        because the mark or the guess may be wrong: text read the wrong way round is only noise.
        """
        chunks = _chunks(source)
        try:
            held: list[bytes] = []  # the chunks of the first ARCHIVE_WINDOW bytes
            size = 0
            for chunk in chunks:
                held.append(chunk)
                size += len(chunk)
                if size >= ARCHIVE_WINDOW:
                    break
            if not held:
                return
            window = held[0] if len(held) == 1 else b"".join(held)
            window = window[:ARCHIVE_WINDOW]
            if _is_archive(window) or ZIP_LOCAL_HEADER in window:
                self.add(0, 0, "archive", "-")
                return
            if window.startswith(LFS_PREFIX):
                self.add(0, 0, "lfs", "-")
                return
            if PDF_MAGIC in window[:PDF_WINDOW]:
                self.add(0, 0, "pdf", "-")
                return
            encoding, held[0] = _detect_encoding(held[0])
            decoder = feeder = None
            passes: list = []
            if encoding is not None:
                decoder = codecs.getincrementaldecoder(encoding)("replace")
                feeder = _LineFeeder(self)
            if encoding != "utf-8":
                first_line_start = 2 if encoding == "utf-16" else 0  # past the byte order mark
                passes = [
                    _AsciiRuns(self),
                    _WideRuns(self, True, first_line_start),
                    _WideRuns(self, False, first_line_start),
                ]
            whole: list[bytes] | None = [] if encoding is not None else None  # a small text, kept for its shape
            size = 0
            for chunk in itertools.chain(held, chunks):
                if self.full:
                    return
                if feeder is not None:
                    feeder.feed(decoder.decode(chunk))
                for run_pass in passes:
                    run_pass.feed(chunk)
                if whole is not None:
                    size += len(chunk)
                    if size > SHAPE_LIMIT:
                        whole = None
                    else:
                        whole.append(chunk)
            if feeder is not None:
                feeder.feed(decoder.decode(b"", final=True), final=True)
            for run_pass in passes:
                run_pass.finish()
            if whole is not None:
                self._shape(b"".join(whole), encoding)
        finally:
            chunks.close()

    def _shape(self, data: bytes, encoding: str) -> None:
        """The rule about the whole text: it is the private exporter's output, under whatever name."""
        text = data.decode(encoding, "replace").lstrip("\ufeff \t\r\n")
        if not text.startswith("{"):
            return
        try:
            document = json.loads(text)
        except (ValueError, RecursionError):  # not JSON, or nested too deep to be a file of item keys
            return
        if _is_export(document):
            self.add(0, 0, "seen-export", "-")

    def _strings(self, body: bytes, base: int, number: int, line_start: int) -> tuple[int, int]:
        previous = 0
        for match in _STRINGS.finditer(body):
            start = match.start()
            if start > previous:
                breaks = body.count(b"\n", previous, start)
                if breaks:
                    number += breaks
                    line_start = base + body.rfind(b"\n", previous, start) + 1
            self.line(number, match.group().decode("ascii"), base + start - line_start, wrap=False)
            previous = match.end()
        breaks = body.count(b"\n", previous)
        if breaks:
            number += breaks
            line_start = base + body.rfind(b"\n", previous) + 1
        return number, line_start


class _AsciiRuns:
    """The ``strings`` pass: each run of four or more printable ASCII bytes is checked as a line.
    Chunks arrive one after the other; a run that reaches the end of one continues in the next."""

    def __init__(self, scan: _FileScan) -> None:
        self.scan = scan
        self.carry = b""
        self.base = 0  # offset of carry[0] in the content
        self.number = 1
        self.line_start = 0

    def feed(self, chunk: bytes) -> None:
        if self.scan.full:
            return
        data = self.carry + chunk
        cut = len(data.rstrip(_PRINTABLE_SET))
        body, carry = data[:cut], data[cut:]
        while len(carry) > MAX_LINE:
            body += carry[:MAX_LINE]
            carry = carry[MAX_LINE:]
        self.number, self.line_start = self.scan._strings(
            body, self.base, self.number, self.line_start
        )
        self.base += len(body)
        self.carry = carry

    def finish(self) -> None:
        if self.carry and not self.scan.full:
            self.scan._strings(self.carry, self.base, self.number, self.line_start)
        self.carry = b""


_WIDE_RUN = {
    True: re.compile(rb"(?:[\x20-\x7e\t]\x00){4,}"),  # UTF-16, little endian
    False: re.compile(rb"(?:\x00[\x20-\x7e\t]){4,}"),  # UTF-16, big endian
}
_WIDE_KEEP = 7  # a run of three characters and half of a fourth may still become a run


class _WideRuns:
    """The ``strings`` pass for UTF-16: each run of four or more printable ASCII characters that
    are each followed (little endian) or preceded (big endian) by a NUL byte. Only runs that start
    at an even offset count: text in the other byte order, read one byte off, looks the same.

    A position is reported like the decoded text of a UTF-16 file would report it, in characters
    from the start of the line, so the same place found by the text pass and by this one is a
    single finding. ``first_line_start`` is the size of the byte order mark."""

    def __init__(self, scan: _FileScan, little: bool, first_line_start: int = 0) -> None:
        self.scan = scan
        self.pattern = _WIDE_RUN[little]
        self.first_character = 0 if little else 1  # which byte of each pair is the character
        self.carry = b""
        self.base = 0  # offset of carry[0] in the content
        self.number = 1
        self.line_start = first_line_start

    def feed(self, chunk: bytes) -> None:
        self._scan(self.carry + chunk, final=False)

    def finish(self) -> None:
        self._scan(self.carry, final=True)

    def _scan(self, data: bytes, final: bool) -> None:
        if self.scan.full:
            self.carry = b""
            return
        runs = list(self.pattern.finditer(data))
        safe = len(data)
        if not final:
            # Keep the end back: a run that touches it goes on in the next chunk.
            safe = max(0, len(data) - _WIDE_KEEP)
            for run in reversed(runs):
                if run.end() <= safe:
                    break
                safe = min(safe, run.start())
            if len(data) - safe > MAX_LINE:  # one enormous run: check it in pieces
                safe = len(data) - MAX_LINE
        self._emit(data, runs, safe)
        self.carry = data[safe:]
        self.base += safe

    def _emit(self, data: bytes, runs, safe: int) -> None:
        previous = 0
        for run in runs:
            start = run.start()
            if start >= safe:
                break
            if start > previous:
                breaks = data.count(b"\n", previous, start)
                if breaks:
                    self.number += breaks
                    self.line_start = self.base + data.rfind(b"\n", previous, start) + 1
            end = min(run.end(), safe)
            previous = max(previous, end)
            if (self.base + start) % 2:
                continue  # not on a character boundary of UTF-16 text
            piece = data[start : end - (end - start) % 2]
            if len(piece) >= 8:
                offset = (self.base + start - self.line_start) // 2
                text = piece[self.first_character :: 2].decode("ascii")
                self.scan.line(self.number, text, offset, wrap=False)
        breaks = data.count(b"\n", previous, safe)
        if breaks:
            self.number += breaks
            self.line_start = self.base + data.rfind(b"\n", previous, safe) + 1


class _LineFeeder:
    """Cuts decoded text into lines (CRLF, LF or CR) as it arrives chunk by chunk."""

    def __init__(self, scan: _FileScan) -> None:
        self.scan = scan
        self.carry = ""
        self.number = 1
        self.offset = 0

    def feed(self, text: str, final: bool = False) -> None:
        data = self.carry + text if self.carry else text
        held = ""
        if not final and data.endswith("\r"):
            data, held = data[:-1], "\r"  # may be the first half of CRLF
        if "\r" in data:
            data = data.replace("\r\n", "\n").replace("\r", "\n")
        parts = data.split("\n")
        tail = parts.pop()
        for line in parts:
            self.scan.line(self.number, line, self.offset)
            self.number += 1
            self.offset = 0
            if self.scan.full:
                return
        if final:
            if tail:
                self.scan.line(self.number, tail, self.offset)
            return
        self.carry = tail + held
        while len(self.carry) > MAX_LINE and not self.scan.full:
            cut = self._cut(self.carry)
            piece, self.carry = self.carry[:cut], self.carry[cut:]
            self.scan.line(self.number, piece, self.offset, wrap=False)
            self.offset += cut

    @staticmethod
    def _cut(text: str) -> int:
        """Where to cut an over-long line: at a character that is not a letter or a digit."""
        for index in range(MAX_LINE, MAX_LINE // 2, -1):
            if not text[index].isalnum():
                return index
        return MAX_LINE


# ---- the public scanning functions ------------------------------------------------------------


def scan_text(
    path: str,
    text: str,
    key: bytes | None,
    deny: Iterable[str],
    allow: Iterable[str],
    phrases=None,
    *,
    line_allow=None,
    explain=None,
    check_path: bool = True,
) -> list[Finding]:
    """Scan ``text`` (and, unless ``check_path`` is false, its ``path``).

    ``deny`` and ``allow`` are sets of digests (lowercase hex); ``phrases`` is a ``PhraseMasker``
    (or any collection of public names); ``line_allow`` is a set of
    ``(path, rule, sha256 of the line)`` exceptions for the log-shape rules; ``explain``, if
    given, receives the matched text of each finding. Without a key only the log-shape rules run.
    """
    context = _Ctx(key, deny, allow, phrases, line_allow, explain)
    scan = _FileScan(context, path)
    if check_path and not scan.path_checks():
        return scan.results()
    if text.startswith("\ufeff"):
        text = text[1:]
    for number, line in enumerate(split_lines(text), start=1):
        if scan.full:
            break
        scan.line(number, line)
    return scan.results()


def scan_bytes(
    path: str,
    data: bytes,
    key: bytes | None,
    deny: Iterable[str],
    allow: Iterable[str],
    phrases=None,
    *,
    line_allow=None,
    explain=None,
    check_path: bool = True,
) -> list[Finding]:
    """Scan the content of one file held in memory."""
    context = _Ctx(key, deny, allow, phrases, line_allow, explain)
    scan = _FileScan(context, path)
    if check_path and not scan.path_checks():
        return scan.results()
    scan.scan_content(data)
    return scan.results()


def _scan_file(ctx: _Ctx, path: str, reader, modes, stats) -> list[Finding]:
    scan = _FileScan(ctx, path)
    proceed = scan.path_checks()
    if stats is not None:
        stats["files"] = stats.get("files", 0) + 1
    if modes and modes.get(path) == "160000":
        scan.add(0, 0, "submodule", "-")
        return scan.results()
    if proceed:
        try:
            source = reader(path)
        except NotRegular:
            if stats is not None:
                stats["skipped"] = stats.get("skipped", 0) + 1
            return scan.results()
        except FileReadError:
            raise
        except OSError as error:
            raise FileReadError(path) from error
        try:
            scan.scan_content(source)
        except OSError as error:
            raise FileReadError(path) from error
    return scan.results()


def scan_paths(
    paths: Iterable[str],
    key: bytes | None,
    deny: Iterable[str],
    allow: Iterable[str],
    reader: Callable[[str], object],
    phrases=None,
    *,
    line_allow=None,
    explain=None,
    modes: Mapping[str, str] | None = None,
    stats: dict | None = None,
) -> list[Finding]:
    """Scan files. ``reader(path)`` returns the content as bytes or as a file-like object (which
    is read in chunks and closed); it lets the staged scan read from the index. A path whose mode
    in ``modes`` is ``160000`` is a submodule and is refused. ``stats`` (a dict) receives the
    number of files and of skipped non-regular files."""
    context = _Ctx(key, deny, allow, phrases, line_allow, explain)
    found: list[Finding] = []
    for path in paths:
        found.extend(_scan_file(context, path, reader, modes, stats))
    return found


# ---- history and identity ----------------------------------------------------------------------


def _scan_label(ctx: _Ctx, label: str, text: str, found: set[Finding]) -> None:
    scan = _FileScan(ctx, label)
    for number, line in enumerate(split_lines(text), start=1):
        scan.line(number, line)
    found.update(scan.results())


def scan_history(
    key: bytes | None,
    deny: Iterable[str],
    allow: Iterable[str],
    phrases=None,
    *,
    repo: str | None = None,
    line_allow=None,
    explain=None,
    stats: dict | None = None,
    revs: Iterable[str] | None = None,
    refs: Iterable[str] | None = None,
) -> list[Finding]:
    """Scan everything reachable from any ref: every blob, every commit message, every
    annotated tag, every path that ever existed, and every branch and tag name.

    ``revs`` narrows that to what some revisions reach (the arguments of ``git rev-list``, for
    example ``[new, "--not", old]`` for what a push sends); ``refs`` names the refs whose names
    are checked (every ref of the repository when it is None)."""
    git = Git(repo)
    ctx = _Ctx(key, deny, allow, phrases, line_allow, explain)
    selector = list(revs) if revs else ["--all"]
    found: set[Finding] = set()
    count = 0

    names = git.lines("for-each-ref", "--format=%(refname)") if refs is None else list(refs)
    for ref in names:
        scan = _FileScan(ctx, f"<ref:{ref}>")
        scan.line(0, ref, 0, logshape_on=False, wrap=False)
        found.update(scan.results())
        count += 1

    for record in git.run("log", *selector, "-z", "--format=%h%n%B").split(b"\0"):
        if not record.strip():
            continue
        head, _, body = record.partition(b"\n")
        label = f"<commit:{head.decode('ascii', 'replace').strip()}>"
        _scan_label(ctx, label, body.decode("utf-8", "replace"), found)
        count += 1

    objects = list(iter_pairs(git.lines("rev-list", *selector, "--objects")))
    paths = {path for _oid, path in objects if path}
    # `rev-list --objects` names a blob once; this lists every path that ever existed.
    paths.update(
        git.nul_separated("log", *selector, "--no-renames", "--name-only", "-z", "--format=")
    )
    for path in sorted(paths):
        scan = _FileScan(ctx, path)
        scan.path_checks()
        found.update(scan.results())

    first_path: dict[str, str] = {}
    for oid, path in objects:
        first_path.setdefault(oid, path)
    if first_path:
        order = list(first_path)
        listing = git.run(
            "cat-file", "--batch-check", input=("\n".join(order) + "\n").encode("ascii")
        )
        kinds = [line.split() for line in listing.decode("ascii", "replace").splitlines()]
        if len(kinds) != len(order) or any(len(fields) < 3 for fields in kinds):
            raise ScanError("git object missing")  # never let a gap in history pass as clean
        with BatchReader(git) as batch:
            for oid, fields in zip(order, kinds):
                kind = fields[1]
                if kind not in ("blob", "tag"):
                    continue
                label = first_path[oid] if kind == "blob" else f"<tag:{oid[:7]}>"
                _kind, blob = batch.get(oid)
                scan = _FileScan(ctx, label)
                try:
                    scan.scan_content(blob)
                except OSError as error:
                    raise ScanError("cannot read git object") from error
                found.update(scan.results())
                count += 1

    if stats is not None:
        stats["files"] = stats.get("files", 0) + count
    return sorted(found)


# The fields of one commit, split by NUL: abbreviated id, author name, address and date, then
# the same for the committer. Fields are never split on tabs or spaces, so an address that
# holds one cannot shift the others.
_COMMIT_FORMAT = "%h%x00%an%x00%ae%x00%ad%x00%cn%x00%ce%x00%cd"
_COMMIT_FIELDS = 7
_TAG_FORMAT = "%(refname)%00%(objecttype)%00%(taggername)%00%(taggeremail)%00%(taggerdate:raw)"
_TAG_FIELDS = 5
_OBJECT_ID = re.compile(rb"[0-9a-f]{4,64}")
_RAW_DATE = re.compile(rb"[0-9]+ ([+-][0-9]{4})")
UNREADABLE_RECORD = Finding("<identity:unreadable>", 0, 0, "identity", "-")


def _address(raw: bytes) -> str:
    return decode_name(raw).strip().strip("<>").strip().casefold()


def check_identity(
    allowed_email: str,
    *,
    repo: str | None = None,
    stats: dict | None = None,
    key: bytes | None = None,
    deny: Iterable[str] = (),
    allow: Iterable[str] = (),
    phrases=None,
    line_allow=None,
    explain=None,
    revs: Iterable[str] | None = None,
) -> list[Finding]:
    """Every author and committer address (and every annotated-tag tagger) must be the allowed
    one, and every date in UTC (offset +0000). A mismatch is reported by commit, never by
    address or offset. The names of the people go through the name check and the log-shape rules
    as well. A record that cannot be read is a finding, not something to skip.

    ``revs`` narrows the commits to what some revisions reach (see ``scan_history``); the tags
    are then left to the check of the whole repository."""
    allowed = allowed_email.strip().casefold()
    if not allowed:
        raise ScanError("identity email missing")
    git = Git(repo)
    ctx = _Ctx(key, deny, allow, phrases, line_allow, explain)
    found: set[Finding] = set()

    def check_person(label: str, name: bytes, email: bytes, date: bytes) -> bool:
        """Check one person; False if the date cannot be read."""
        if _address(email) != allowed:
            found.add(Finding(label, 0, 0, "identity", "-"))
        scan = _FileScan(ctx, label)
        scan.line(0, decode_name(name), 0, wrap=False)
        found.update(scan.results())
        parsed = _RAW_DATE.fullmatch(date.strip())
        if parsed is None:
            return False
        if parsed.group(1) != b"+0000":
            found.add(Finding(label, 0, 0, "timezone", "-"))
        return True

    selector = list(revs) if revs else ["--all"]
    listing = git.run("log", *selector, "-z", "--date=raw", "--format=" + _COMMIT_FORMAT)
    fields = listing.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()  # the end of the last record
    if len(fields) % _COMMIT_FIELDS:
        found.add(UNREADABLE_RECORD)
    whole = len(fields) - len(fields) % _COMMIT_FIELDS
    for index in range(0, whole, _COMMIT_FIELDS):
        sha, a_name, a_email, a_date, c_name, c_email, c_date = fields[
            index : index + _COMMIT_FIELDS
        ]
        if _OBJECT_ID.fullmatch(sha) is None:
            found.add(UNREADABLE_RECORD)
            continue
        label = f"<commit:{sha.decode('ascii')}>"
        readable = check_person(label, a_name, a_email, a_date)
        readable = check_person(label, c_name, c_email, c_date) and readable
        if not readable:
            found.add(UNREADABLE_RECORD)

    if revs is None:
        listing = git.run("for-each-ref", "--format=" + _TAG_FORMAT, "refs/tags")
        for record in listing.split(b"\n"):
            if not record:
                continue
            parts = record.split(b"\0")
            if len(parts) != _TAG_FIELDS:
                found.add(UNREADABLE_RECORD)
                continue
            ref, kind, name, email, date = parts
            if kind != b"tag":
                continue  # a lightweight tag names a commit and has no tagger
            if not check_person(f"<ref:{decode_name(ref)}>", name, email, date):
                found.add(UNREADABLE_RECORD)

    if stats is not None:
        stats["files"] = stats.get("files", 0) + 1
    return sorted(found)


# ---- printing paths safely -----------------------------------------------------------------------

_SEPARATORS = "/\\"


def _component(path: str, index: int) -> tuple[int, int]:
    """The start and end of the path component that holds ``index``."""
    left = max(path.rfind(sep, 0, index) for sep in _SEPARATORS) + 1
    ends = [i for i in (path.find(sep, index) for sep in _SEPARATORS) if i >= 0]
    return left, min(ends, default=len(path))


def _original_span(path: str, imap, start: int, end: int) -> tuple[int, int]:
    """Where in ``path`` a token found at ``start:end`` of one of its views really is.

    A decoded character stands for a whole escape, so a span that ends on one is stretched to
    the end of that escape. A token whose characters all came from one place (a ligature that
    folds into letters) cannot be located more closely than the path component that holds it."""
    if imap is None:
        return start, end
    origins = imap[start:end]
    first, last = min(origins), max(origins)
    if len(origins) > 1 and first == last:
        return _component(path, first)
    stop = max(last + 1, escape_end(path, last) or 0)
    return first, stop


def _mask_with(ctx: _Ctx, path: str) -> str:
    if ctx.mac is None or path.startswith(LABEL_PREFIXES_WITHOUT_NAMES):
        return path
    spans: list[tuple[int, int, str]] = []
    for text, imap in _variants(path):
        for start, end, _token, value in ctx.hits(blank_hex(text)):
            first, stop = _original_span(path, imap, start, end)
            spans.append((first, stop, value[:8]))
    for start, end, decoded in base64_spans(path):
        found = ctx.hits(blank_hex(decoded))
        if found:
            spans.append((start, end, found[0][3][:8]))
    if not spans:
        return path
    spans.sort()
    merged: list[tuple[int, int, str]] = []
    for start, end, tag in spans:
        if merged and start < merged[-1][1]:
            previous = merged[-1]
            merged[-1] = (previous[0], max(previous[1], end), previous[2])
        else:
            merged.append((start, end, tag))
    pieces = []
    position = 0
    for start, end, tag in merged:
        pieces.append(path[position:start])
        pieces.append(f"[private:{tag}]")
        position = end
    pieces.append(path[position:])
    return "".join(pieces)


def mask_path(
    path: str, key: bytes | None, deny: Iterable[str], allow: Iterable[str] = (), phrases=None
) -> str:
    """``path`` with each private token replaced by ``[private:<tag>]``, safe to print."""
    return _mask_with(_Ctx(key, deny, allow, phrases, None, None), path)


# ---- the files in privacy/ and derived/ ---------------------------------------------------------


def _read_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8", "replace")


_DIGEST_LINE = re.compile(r"[0-9a-f]{64}")


def _read_digest_file(path: str, kind: str = "denylist") -> tuple[set[str], str | None]:
    """Digests of a list file, and the ``# key-check:`` value of its header if there is one.

    Besides comments (``#``) and blank lines, a line must be exactly 64 lower-case hex digits.
    Anything else is an error that names the line, so a damaged list never narrows the check
    unseen. ``kind`` names the list in that error."""
    digests: set[str] = set()
    check = None
    with open(path, "rb") as handle:
        text = _read_text(handle.read())  # a byte order mark is dropped here
    for number, raw in enumerate(re.split(r"\r\n|\n|\r", text), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            match = re.match(r"#\s*key-check:\s*([0-9a-fA-F]{16})\s*$", line)
            if match:
                check = match.group(1).lower()
        elif _DIGEST_LINE.fullmatch(line):
            digests.add(line)
        else:
            raise ScanError(f"{kind} malformed (line {number})")
    return digests, check


def load_line_allow(path: str) -> set[tuple[str, str, str]]:
    """Reviewed exceptions to the log-shape rules: ``path<TAB>rule<TAB>sha256 of the line``."""
    entries = set()
    with open(path, "rb") as handle:
        text = _read_text(handle.read())
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 3 or not re.fullmatch(r"[0-9a-fA-F]{64}", fields[2].strip()):
            raise ScanError(f"allowlist-lines.txt line {number} is malformed")
        entries.add((fields[0].strip(), fields[1].strip(), fields[2].strip().lower()))
    return entries


_NAME_KEYS = {"name", "zone", "npc"}
_LIST_KEYS = {"npcs", "zones"}


def load_catalog_phrases(path: str) -> set[str]:
    """Every item name, zone name and NPC name in ``derived/catalog.json``."""
    try:
        with open(path, "rb") as handle:
            data = json.loads(_read_text(handle.read()))
    except (OSError, ValueError) as error:
        raise ScanError("catalog unreadable: derived/catalog.json") from error
    phrases: set[str] = set()
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _NAME_KEYS and isinstance(value, str):
                    phrases.add(value)
                elif key in _LIST_KEYS and isinstance(value, list):
                    phrases.update(item for item in value if isinstance(item, str))
                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(node, list):
            stack.extend(item for item in node if isinstance(item, (dict, list)))
    return phrases


def _read_repo_file(path: str, label: str, loader):
    """Run ``loader(path)``; a file that cannot be read is a configuration error."""
    try:
        return loader(path)
    except OSError as error:
        raise ScanError(f"cannot read file: {label}") from error


def _parse_key(text: str) -> bytes:
    cleaned = text.lstrip("\ufeff").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", cleaned):
        raise ScanError("privacy key invalid: expected exactly 64 hex characters")
    return bytes.fromhex(cleaned)


def _find_key(key_file: str | None, env: Mapping[str, str], default_key_file: str | None):
    """The key from ``--key-file``, else the environment, else the default file; None if absent."""
    if key_file is not None:
        try:
            with open(key_file, "rb") as handle:
                return _parse_key(_read_text(handle.read()))
        except FileNotFoundError as error:
            raise ScanError("privacy key missing: the key file does not exist") from error
        except OSError as error:
            raise ScanError("privacy key missing: the key file cannot be read") from error
    if "TRIOFORGE_PRIVACY_KEY" in env:
        return _parse_key(env["TRIOFORGE_PRIVACY_KEY"])
    if default_key_file and os.path.isfile(default_key_file):
        try:
            with open(default_key_file, "rb") as handle:
                return _parse_key(_read_text(handle.read()))
        except OSError as error:
            raise ScanError("privacy key missing: the default key file cannot be read") from error
    return None


# ---- the command line ----------------------------------------------------------------------------


class _Exit(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


class _Parser(argparse.ArgumentParser):
    """An argument parser that reports to the given streams and never calls ``sys.exit``."""

    def __init__(self, out, err) -> None:
        super().__init__(
            prog="python -m trioforge.privacy.scan",
            description=(
                "Scan files, commit messages and history for private names and game-log text. "
                "Exit code 0: clean. 1: findings. 2: configuration error. The output never "
                "contains a matched token, a matched line or an e-mail address."
            ),
            allow_abbrev=False,
        )
        self._out, self._err = out, err

    def _print_message(self, message, file=None):
        if message:
            (file or self._err).write(message)

    def print_help(self, file=None):
        super().print_help(file or self._out)

    def error(self, message):
        # What was typed is never echoed: it could be a name. Only a known option is named.
        named = re.match(r"argument (-[-\w]*):", message)
        if named and named.group(1) in self._option_string_actions:
            raise ScanError(f"usage error: {named.group(1)}")
        raise ScanError("usage error")

    def exit(self, status=0, message=None):
        if message:
            self._err.write(message)
        raise _Exit(status)


def _build_parser(out, err) -> _Parser:
    parser = _Parser(out, err)
    parser.add_argument("paths", nargs="*", metavar="PATH", help="files or folders to scan")
    parser.add_argument(
        "--all",
        action="store_true",
        help="scan every tracked file and every untracked, not ignored one",
    )
    parser.add_argument(
        "--staged", action="store_true", help="scan the staged version of each changed file"
    )
    parser.add_argument("--key-file", metavar="FILE", help="file holding the 64-hex-character key")
    parser.add_argument(
        "--require-key",
        action="store_true",
        help="exit 2 if there is no key, or the denylist is missing or empty",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="also print the matched text (refused in CI and when output is not a terminal)",
    )
    parser.add_argument("--commit-msg", metavar="FILE", help="scan a commit message file")
    parser.add_argument(
        "--history", action="store_true", help="scan every blob, message and ref name in history"
    )
    parser.add_argument(
        "--identity",
        metavar="EMAIL",
        help="require every author and committer to use EMAIL, and every date to be in UTC",
    )
    parser.add_argument(
        "--identity-file",
        metavar="FILE",
        help="like --identity, with the address read from FILE (privacy/identity.txt)",
    )
    parser.add_argument(
        "--pre-push",
        metavar="REMOTE",
        help=(
            "check what a push to REMOTE sends: read git's lines for the pre-push hook from "
            "standard input"
        ),
    )
    return parser


def _explain_refusal(env: Mapping[str, str], stdout) -> str | None:
    for name in EXPLAIN_BLOCKERS:
        if name in env:
            return f"--explain is refused: {name} is set in the environment"
    isatty = getattr(stdout, "isatty", None)
    if not (callable(isatty) and isatty()):
        return "--explain is refused: standard output is not a terminal"
    return None


def _tame_stream(stream) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(errors="backslashreplace")
        except (OSError, ValueError):
            pass


def _inside(root: str, candidate: str) -> bool:
    """Whether ``candidate`` is ``root`` or lies below it (both already resolved)."""
    try:
        base = os.path.normcase(root)
        return os.path.commonpath([base, os.path.normcase(candidate)]) == base
    except ValueError:  # another drive
        return False


def _resolve_argument(root: str, argument: str) -> tuple[str, str]:
    """``(display path, real path)`` of a PATH argument, which must lie inside the repository.
    Folders in front of the last part are resolved, so a path that goes out through a link or a
    junction is refused. The last part is not: a link given as a PATH is scanned as the text of
    the link, never followed."""
    absolute = os.path.abspath(argument)
    parent, leaf = os.path.split(absolute)
    real = os.path.join(os.path.realpath(parent), leaf)
    if not _inside(root, real):
        raise ScanError("path is outside the repository")
    return os.path.relpath(real, root).replace(os.sep, "/"), real


def _unreadable_folder(root: str):
    def fail(error: OSError) -> None:
        name = error.filename if isinstance(error.filename, str) else ""
        try:
            shown = os.path.relpath(name, root).replace(os.sep, "/") if name else ""
        except ValueError:
            shown = ""
        raise FileReadError(shown)

    return fail


def _expand_paths(root: str, arguments: list[str]) -> dict[str, str]:
    """Map display path -> real path for the PATH arguments; folders are walked. A folder that
    cannot be read is an error. A link or a junction is never entered, and every path must lie
    inside the repository root."""
    real_root = os.path.realpath(root)
    mapping: dict[str, str] = {}
    for argument in arguments:
        display, real = _resolve_argument(real_root, argument)
        if (
            os.path.isdir(real)
            and not os.path.islink(real)
            and not os.path.isjunction(real)
        ):
            for folder, names, files in os.walk(real, onerror=_unreadable_folder(real_root)):
                names[:] = sorted(
                    name
                    for name in names
                    if name != ".git" and not os.path.isjunction(os.path.join(folder, name))
                )
                for name in sorted(files):
                    inner = os.path.join(folder, name)
                    shown = os.path.relpath(inner, real_root).replace(os.sep, "/")
                    mapping[shown] = inner
        else:
            mapping[display] = real
    return mapping


def _worktree_reader(real_of: Mapping[str, str], untracked: set[str], root: str | None = None):
    """A reader for files on disk. An untracked file whose folder, once resolved, lies outside
    ``root`` (it is reached through a link or a junction that leaves the repository) is never
    opened: it is skipped like any other file that is not a plain file of the repository."""

    def read(display: str):
        real = real_of[display]
        if root is not None and display in untracked:
            if not _inside(root, os.path.realpath(os.path.dirname(real))):
                raise NotRegular()
        info = os.lstat(real)
        if stat.S_ISLNK(info.st_mode):
            if display in untracked:
                raise NotRegular()
            return os.readlink(real).encode("utf-8", "surrogateescape")
        if stat.S_ISREG(info.st_mode):
            return open(real, "rb")
        raise NotRegular()

    return read


def _read_identity_file(path: str) -> str:
    """The one e-mail address in a file such as ``privacy/identity.txt``."""
    try:
        with open(path, "rb") as handle:
            text = _read_text(handle.read())
    except OSError as error:
        raise ScanError("identity file unreadable") from error
    lines = [line.strip() for line in re.split(r"\r\n|\n|\r", text) if line.strip()]
    if len(lines) != 1 or not re.fullmatch(r"[^@\s]+@[^@\s]+", lines[0]):
        raise ScanError("identity file invalid: expected one e-mail address")
    return lines[0]


def _hashed_label(path: str) -> str:
    """How a path is printed when no private name can be recognised in it (no key): as a hash of
    itself, because a name in it could not be hidden. A label that holds no name stays as it is."""
    if path == COMMIT_MSG_PATH or path.startswith(LABEL_PREFIXES_WITHOUT_NAMES):
        return path
    return "<path:" + hashlib.sha256(path.encode("utf-8", "surrogateescape")).hexdigest()[:8] + ">"


_OBJECT_NAME = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def _read_push_lines(stdin) -> list[tuple[str, str, str, str]]:
    """The lines git gives a pre-push hook: ``<local ref> <local id> <remote ref> <remote id>``."""
    try:
        data = stdin.read()
    except (OSError, ValueError) as error:
        raise ScanError("pre-push input unreadable") from error
    if isinstance(data, bytes):
        data = data.decode("utf-8", "surrogateescape")
    lines = []
    for raw in data.replace("\r\n", "\n").split("\n"):
        if not raw.strip():
            continue
        fields = raw.split(" ")
        if (
            len(fields) != 4
            or _OBJECT_NAME.fullmatch(fields[1]) is None
            or _OBJECT_NAME.fullmatch(fields[3]) is None
        ):
            raise ScanError("pre-push input malformed")
        lines.append((fields[0], fields[1], fields[2], fields[3]))
    return lines


def _run(argv, env, out, err, default_key_file, stdin) -> int:
    parser = _build_parser(out, err)
    args = parser.parse_args(argv)

    if args.all and args.staged:
        raise ScanError("usage error: --all and --staged cannot be combined")
    if args.paths and (args.all or args.staged):
        raise ScanError("usage error: PATH cannot be combined with --all or --staged")
    if args.identity is not None and args.identity_file is not None:
        raise ScanError("usage error: --identity and --identity-file cannot be combined")
    if args.pre_push is not None and (
        not args.pre_push or args.pre_push.startswith("-") or not args.pre_push.isprintable()
    ):
        raise ScanError("usage error: --pre-push needs the name of a remote")
    if not (
        args.all
        or args.staged
        or args.paths
        or args.commit_msg
        or args.history
        or args.identity is not None
        or args.identity_file is not None
        or args.pre_push is not None
    ):
        raise ScanError(
            "usage error: give --all, --staged, PATH, --commit-msg, --history, --identity, "
            "--identity-file or --pre-push"
        )
    if args.explain:
        refusal = _explain_refusal(env, out)
        if refusal:
            raise ScanError(refusal)

    git = Git()
    root = git.root()
    needs_repo = (
        args.all
        or args.staged
        or args.history
        or args.identity is not None
        or args.identity_file is not None
        or args.pre_push is not None
    )
    if root is None:
        if needs_repo:
            raise ScanError("not inside a git repository")
        root = os.getcwd()
    git = Git(root)

    # ---- key, lists, masker -------------------------------------------------------------
    key = _find_key(args.key_file, env, default_key_file)
    if key is None and args.require_key:
        raise ScanError("privacy key missing: set TRIOFORGE_PRIVACY_KEY or pass --key-file")
    notices: list[str] = []
    deny: set[str] = set()
    allow: set[str] = set()
    if key is None:
        notices.append("denylist check skipped (no key)")
    else:
        deny_path = os.path.join(root, "privacy", "denylist.hmac")
        if not os.path.isfile(deny_path):
            if args.require_key:
                raise ScanError("denylist missing: privacy/denylist.hmac")
            notices.append("denylist check skipped (denylist missing)")
        else:
            deny, check = _read_repo_file(
                deny_path,
                "privacy/denylist.hmac",
                lambda path: _read_digest_file(path, "denylist"),
            )
            if check is not None and check != digest(key, KEY_CHECK_TEXT)[:16]:
                raise ScanError("privacy key does not match the denylist")
            if not deny:
                if args.require_key:
                    raise ScanError("denylist empty: privacy/denylist.hmac has no digests")
                notices.append("denylist check skipped (denylist empty)")
        allow_path = os.path.join(root, "privacy", "allow.hmac")
        if os.path.isfile(allow_path):
            allow = _read_repo_file(
                allow_path,
                "privacy/allow.hmac",
                lambda path: _read_digest_file(path, "allow list"),
            )[0]

    line_allow: set[tuple[str, str, str]] = set()
    line_allow_path = os.path.join(root, "privacy", "allowlist-lines.txt")
    if os.path.isfile(line_allow_path):
        line_allow = _read_repo_file(
            line_allow_path, "privacy/allowlist-lines.txt", load_line_allow
        )

    masker = None
    catalog_path = os.path.join(root, "derived", "catalog.json")
    if deny and os.path.isfile(catalog_path):
        phrases = load_catalog_phrases(catalog_path)
        if phrases:
            masker = PhraseMasker(phrases)

    identity = None
    if args.identity_file is not None:
        identity = _read_identity_file(args.identity_file)
    elif args.identity is not None:
        identity = args.identity

    explain: dict[Finding, str] | None = {} if args.explain else None
    stats: dict[str, int] = {"files": 0, "skipped": 0}
    findings: list[Finding] = []
    context = _Ctx(key, deny, allow, masker, None, None)  # for masking printed paths
    # Without a key no name can be recognised, so no path can be made safe to print: it is shown
    # as a hash. (Asking for --explain, which only runs on a terminal outside CI, shows it.)
    hash_paths = context.mac is None and not args.explain

    def mask(path: str) -> str:
        return _hashed_label(path) if hash_paths else _mask_with(context, path)

    common = dict(line_allow=line_allow, explain=explain)
    try:
        if args.staged:
            findings += _run_staged(git, key, deny, allow, masker, stats, common)
        if args.all:
            findings += _run_all(git, root, key, deny, allow, masker, stats, common)
        if args.paths:
            mapping = _expand_paths(root, args.paths)
            reader = _worktree_reader(mapping, set())
            findings += scan_paths(
                sorted(mapping), key, deny, allow, reader, masker, stats=stats, **common
            )
        if args.commit_msg:
            findings += _run_commit_msg(args.commit_msg, key, deny, allow, masker, stats, common)
        if args.history:
            findings += scan_history(
                key, deny, allow, masker, repo=root, stats=stats, **common
            )
        if identity is not None:
            findings += check_identity(
                identity,
                repo=root,
                stats=stats,
                key=key,
                deny=deny,
                allow=allow,
                phrases=masker,
                **common,
            )
        if args.pre_push is not None:
            pushed = _read_push_lines(sys.stdin if stdin is None else stdin)
            findings += _run_pre_push(
                git, root, args.pre_push, pushed, identity, key, deny, allow, masker, stats, common
            )
    except FileReadError as error:
        raise ScanError(f"cannot read file: {mask(error.path)}") from None

    for notice in notices:
        print(notice, file=out)
    findings = sorted(set(findings))
    for finding in findings:
        line = f"{mask(finding.path)}:{finding.line}:{finding.col}: {finding.rule} [{finding.tag}]"
        if explain is not None and finding in explain:
            line += f"  -> {explain[finding]}"
        print(line, file=out)
    if stats["skipped"]:
        print(f"skipped {stats['skipped']} non-regular files", file=out)
    print(f"privacy scan: {stats['files']} files, {len(findings)} findings", file=out)
    return 1 if findings else 0


def _run_staged(git: Git, key, deny, allow, masker, stats, common) -> list[Finding]:
    if git.unmerged():
        raise ScanError("resolve merge conflicts first")
    entries = {entry.path: entry for entry in git.index_entries() if entry.stage == 0}
    changed = {name for name in git.staged_names() if name in entries}
    # A submodule is refused wherever the index holds one, whether or not the diff shows it.
    gitlinks = {path for path, entry in entries.items() if entry.mode == "160000"}
    paths = sorted(changed | gitlinks)
    modes = {name: entries[name].mode for name in paths}
    with BatchReader(git) as batch:

        def reader(path: str):
            return batch.get(entries[path].oid)[1]

        return scan_paths(
            paths, key, deny, allow, reader, masker, modes=modes, stats=stats, **common
        )


def _run_all(git: Git, root: str, key, deny, allow, masker, stats, common) -> list[Finding]:
    """Every tracked file as the index holds it (as ``--staged`` reads it, and as a commit would
    store it), and every untracked file that is not ignored as the working tree holds it."""
    if git.unmerged():
        raise ScanError("resolve merge conflicts first")
    entries = {entry.path: entry for entry in git.index_entries()}
    modes = {path: entry.mode for path, entry in entries.items()}
    with BatchReader(git) as batch:

        def from_index(path: str):
            return batch.get(entries[path].oid)[1]

        found = scan_paths(
            sorted(entries),
            key,
            deny,
            allow,
            from_index,
            masker,
            modes=modes,
            stats=stats,
            **common,
        )
    untracked = git.untracked_names()
    real_of = {path: os.path.join(root, *path.rstrip("/").split("/")) for path in untracked}
    reader = _worktree_reader(real_of, set(untracked), os.path.realpath(root))
    found += scan_paths(
        sorted(untracked), key, deny, allow, reader, masker, stats=stats, **common
    )
    return found


def _run_commit_msg(path, key, deny, allow, masker, stats, common) -> list[Finding]:
    """The whole message file is scanned, comment lines and everything below a scissors line
    included: git keeps all of it when a message is given with ``-m`` or ``-F``."""
    try:
        with open(path, "rb") as handle:
            text = _read_text(handle.read())
    except OSError as error:
        raise FileReadError(path) from error
    stats["files"] = stats.get("files", 0) + 1
    return scan_text(COMMIT_MSG_PATH, text, key, deny, allow, masker, check_path=False, **common)


def _run_pre_push(
    git: Git, root: str, remote: str, pushed, identity, key, deny, allow, masker, stats, common
) -> list[Finding]:
    """What a push is about to send, as git describes it to the pre-push hook: for each ref, the
    commits the remote does not have (with their files, messages and people), and the name the
    ref will have on the remote. Deleting a ref sends nothing and is left alone, so that a ref
    with a bad name can be removed."""
    found: list[Finding] = []
    for _local_ref, local_sha, remote_ref, remote_sha in pushed:
        if not local_sha.strip("0"):
            continue
        if remote_sha.strip("0") and git.has_object(remote_sha):
            revs = [local_sha, "--not", remote_sha]
        else:  # a new ref, or one whose old value is not known here: all that no remote holds
            revs = [local_sha, "--not", f"--remotes={remote}"]
        found += scan_history(
            key, deny, allow, masker, repo=root, stats=stats, revs=revs, refs=[remote_ref], **common
        )
        if identity is not None:
            found += check_identity(
                identity,
                repo=root,
                stats=stats,
                key=key,
                deny=deny,
                allow=allow,
                phrases=masker,
                revs=revs,
                **common,
            )
    return found


def main(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout=None,
    stderr=None,
    stdin=None,
    default_key_file: str | None = DEFAULT_KEY_FILE,
) -> int:
    """Run the scanner. Returns the exit code: 0 clean, 1 findings, 2 configuration error.

    Options: ``--all`` (every tracked file as the index holds it, plus untracked, not ignored
    files), ``--staged`` (the staged version of each changed file), or file/folder names;
    ``--commit-msg FILE``; ``--history``; ``--identity EMAIL`` or ``--identity-file FILE``;
    ``--pre-push REMOTE`` (read the refs of a push from standard input); ``--key-file FILE``;
    ``--require-key``; ``--explain``.

    The key comes from ``--key-file``, else the environment variable ``TRIOFORGE_PRIVACY_KEY``,
    else ``default_key_file``. ``env``, ``stdout``, ``stderr`` and ``stdin`` default to the
    process's own; tests pass their own.
    """
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    environment = os.environ if env is None else env
    _tame_stream(out)
    _tame_stream(err)
    try:
        return _run(argv, environment, out, err, default_key_file, stdin)
    except _Exit as stop:
        return stop.status
    except ScanError as error:
        print(error.message, file=err)
        return 2
    except KeyboardInterrupt:
        print("privacy scan: interrupted", file=err)
        return 2
    except Exception as error:  # a traceback could carry text from a file: say only the kind
        print(f"privacy scan: internal error ({type(error).__name__})", file=err)
        return 2


if __name__ == "__main__":
    sys.exit(main())
