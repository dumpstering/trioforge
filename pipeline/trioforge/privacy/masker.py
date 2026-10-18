"""PhraseMasker: hides public game names (items, zones, NPCs) from the name check.

A private name that is also part of a real game name would otherwise be reported everywhere
that game name appears. The masker finds every whole occurrence of a known phrase in a line,
case-insensitively, and blanks it with spaces of the same length, so the columns of whatever
follows stay right. A phrase is a sequence of words (runs of letters and digits) with exact
separators between them; it matches only where the text before and after it is not a letter or a
digit. The longest phrase wins, and matches never overlap.

Phrases live in a trie keyed by word, so the cost of a line does not depend on how many phrases
there are, even when thousands of them start with the same word.

A phrase that holds a single token (see ``tokens``) must not hide it when that token is on the
denylist: a public name that is one word, and is also a private name, would then be invisible
everywhere. ``without_private_single_tokens`` drops such phrases, so the collision shows up as a
finding for a person to review (and, if harmless, to allow by digest). A phrase of several
tokens keeps masking them all.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from .textnorm import normalize_for_scan, token_spans

_WORD = re.compile(r"[^\W_]+")


def fold(text: str) -> str:
    """Lower-case ``text`` without changing its length (some characters would grow)."""
    low = text.lower()
    if len(low) == len(text):
        return low
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in text)


class _Node:
    __slots__ = ("kids", "end")

    def __init__(self) -> None:
        self.kids: dict[str, _Node] = {}
        self.end = False


class PhraseMasker:
    """Build once from the public names; call ``mask`` or ``spans`` on each line."""

    def __init__(self, phrases: Iterable[str]) -> None:
        self._root: dict[str, _Node] = {}
        self._known: set[str] = set()
        # For each phrase: the text it came from, and its plain form if that differs.
        self._sources: dict[str, tuple[str, str | None]] = {}
        for phrase in phrases:
            core = self._core(phrase)
            if core is None or core in self._known:
                continue
            self._known.add(core)
            self._insert(core)
            plain = self._core(normalize_for_scan(phrase))
            if plain is not None and plain != core:
                self._insert(plain)
            else:
                plain = None
            self._sources[core] = (phrase, plain)

    @staticmethod
    def _core(phrase: str) -> str | None:
        """The folded phrase without leading and trailing punctuation, or None if no words."""
        low = fold(phrase)
        words = list(_WORD.finditer(low))
        if not words:
            return None
        return low[words[0].start() : words[-1].end()]

    def _insert(self, core: str) -> None:
        words = list(_WORD.finditer(core))
        node = self._root.setdefault(words[0].group(), _Node())
        for before, word in zip(words, words[1:]):
            key = core[before.end() : word.start()] + word.group()
            node = node.kids.setdefault(key, _Node())
        node.end = True

    def __len__(self) -> int:
        return len(self._known)

    def without_private_single_tokens(self, is_private: Callable[[str], bool]) -> "PhraseMasker":
        """This masker without each phrase that holds exactly one token, in its own form or in
        its plain form, when ``is_private(token)`` is true. Returns ``self`` if nothing is
        dropped."""
        kept = []
        dropped = False
        for core, (phrase, plain) in self._sources.items():
            if any(self._single_private(form, is_private) for form in (core, plain) if form):
                dropped = True
            else:
                kept.append(phrase)
        return PhraseMasker(kept) if dropped else self

    @staticmethod
    def _single_private(form: str, is_private: Callable[[str], bool]) -> bool:
        found = [token for _start, _end, token in token_spans(form)]
        return len(found) == 1 and is_private(found[0])

    def spans(self, text: str) -> list[tuple[int, int]]:
        """The ``(start, end)`` index pairs of the phrases found in ``text``."""
        root = self._root
        if not root:
            return []
        folded = fold(text)
        words = list(_WORD.finditer(folded))
        found: list[tuple[int, int]] = []
        total = len(words)
        index = 0
        while index < total:
            first = words[index]
            node = root.get(first.group())
            if node is None:
                index += 1
                continue
            best_end = first.end() if node.end else -1
            best_index = index
            cursor = index
            while cursor + 1 < total:
                following = words[cursor + 1]
                key = folded[words[cursor].end() : following.start()] + following.group()
                node = node.kids.get(key)
                if node is None:
                    break
                cursor += 1
                if node.end:
                    best_end = following.end()
                    best_index = cursor
            if best_end >= 0:
                found.append((first.start(), best_end))
                index = best_index + 1
            else:
                index += 1
        return found

    def mask(self, text: str) -> str:
        """``text`` with every phrase replaced by spaces of the same length."""
        found = self.spans(text)
        if not found:
            return text
        pieces = []
        position = 0
        for start, end in found:
            pieces.append(text[position:start])
            pieces.append(" " * (end - start))
            position = end
        pieces.append(text[position:])
        return "".join(pieces)
