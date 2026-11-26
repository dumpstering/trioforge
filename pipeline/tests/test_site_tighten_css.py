"""The guard of ``build.tighten_main`` against the stylesheet: no line break is left out next to an element that the site's own CSS draws inline.

``tighten_main`` leaves out the line breaks between two tags of the main part of a trio page where the tag is that of a block, a list item, a table cell, an option or a summary,
and before the closing tag of a block, because a browser draws no gap there. That is true of such elements only while the stylesheet leaves them blocks: an ``li`` made
``display: inline-block`` draws the gap between two of them, and without the line break the words of two items would run together. So this test builds a real site, keeps what
``tighten_main`` was given, finds every element next to a line break that it took out, and reads the built stylesheet for a rule that makes such an element inline (a rule's
subject compound, tag, classes and id, is matched; the rules above it in the selector are ignored, so the check can only be too careful). A later change to the CSS that makes one
of these elements inline fails here, and the answer is to make the pass leave that break alone (or to keep the element a block). Every markup and style here is invented but the
real ones that the build reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from test_site_build import need_node, run_build

from trioforge.site import build

#: the values of ``display`` that draw the whitespace between two siblings
INLINE_DISPLAYS = ("inline", "inline-block", "inline-flex", "inline-grid", "inline-table")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# ---- the stylesheet ----------------------------------------------------------------------------------------------------------------


def css_rules(text: str) -> list[tuple[str, str]]:
    """The ``(selectors, declarations)`` of every style rule of a stylesheet, those inside ``@media`` and ``@supports`` too."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    rules: list[tuple[str, str]] = []

    def walk(src: str) -> None:
        i = 0
        while i < len(src):
            j = src.find("{", i)
            if j < 0:
                return
            head, depth, k = src[i:j].strip(), 1, j + 1
            while depth and k < len(src):
                depth += {"{": 1, "}": -1}.get(src[k], 0)
                k += 1
            body = src[j + 1 : k - 1]
            if head.startswith("@"):
                if head.startswith(("@media", "@supports", "@layer", "@container")):
                    walk(body)
            else:
                rules.append((head, body))
            i = k

    walk(text)
    return rules


def top_level(text: str, separators: str) -> list[str]:
    """``text`` cut at the characters of ``separators`` that are outside parentheses and brackets."""
    parts, depth, start = [], 0, 0
    for n, char in enumerate(text):
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif depth == 0 and char in separators:
            parts.append(text[start:n])
            start = n + 1
    parts.append(text[start:])
    return [part for part in (p.strip() for p in parts) if part]


@dataclass(frozen=True)
class Compound:
    tag: str | None
    classes: frozenset[str]
    ident: str | None


def subject_of(selector: str) -> Compound | None:
    """The compound selector a rule is about (the last one of the selector), with the pseudo-classes left out (the rule may then apply more often than it does: only too careful).
    None for a selector of a pseudo-element, which styles the generated content and not the element."""
    last = _last_compound(selector)
    if "::" in last or re.search(r":(before|after|first-line|first-letter)\b", last):
        return None
    last = re.sub(r"::?[a-zA-Z-]+(\((?:[^()]|\([^()]*\))*\))?", "", last)  # (a pseudo-class, with the selector it takes, if it takes one)
    last = re.sub(r"\[[^\]]*\]", "", last)
    tag = re.match(r"^[a-zA-Z][a-zA-Z0-9]*", last)
    return Compound(
        tag.group(0).lower() if tag else None, frozenset(re.findall(r"\.([\w-]+)", last)), (re.findall(r"#([\w-]+)", last) or [None])[0]
    )


def _last_compound(selector: str) -> str:
    """The last compound of a selector: what follows the last combinator that is outside parentheses and brackets."""
    depth, cut = 0, 0
    for n, char in enumerate(selector):
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif depth == 0 and char in " >+~":
            cut = n + 1
    return selector[cut:].strip()


def inline_subjects(css: str) -> list[tuple[str, Compound, str]]:
    """``(selector, subject, display)`` of every rule of the stylesheet that makes its subject inline."""
    found = []
    for head, body in css_rules(css):
        shown = re.search(r"(?<![\w-])display\s*:\s*(" + "|".join(INLINE_DISPLAYS) + r")\s*(?:;|!|$)", body.strip() + ";")
        if not shown:
            continue
        for selector in top_level(head, ","):
            subject = subject_of(selector)
            if subject is not None:
                found.append((selector, subject, shown.group(1)))
    return found


# ---- the page ----------------------------------------------------------------------------------------------------------------------


@dataclass
class Element:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)

    @property
    def classes(self) -> frozenset[str]:
        return frozenset(self.attrs.get("class", "").split())

    def describe(self) -> str:
        return f"<{self.tag}" + "".join(f' {k}="{v}"' for k, v in self.attrs.items() if k in ("class", "id")) + ">"


TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)((?:\s+[^<>]*?)?)\s*(/?)>")
ATTR = re.compile(r'([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+)))?')


def tags_of(html: str) -> list[tuple[int, int, bool, Element]]:
    """The tags of ``html`` as ``(start, end, closes, element)``, the element of a closing tag being the one it closes."""
    out, stack = [], []
    for m in TAG.finditer(html):
        closing, name, rest, selfclosing = m.group(1) == "/", m.group(2).lower(), m.group(3), m.group(4)
        if closing:
            while stack and stack[-1].tag != name:
                stack.pop()  # (an element with no closing tag in the markup)
            element = stack.pop() if stack else Element(name)
            out.append((m.start(), m.end(), True, element))
        else:
            attrs = {a.group(1): (a.group(2) or a.group(3) or a.group(4) or "") for a in ATTR.finditer(rest)}
            element = Element(name, attrs)
            out.append((m.start(), m.end(), False, element))
            if name not in VOID and not selfclosing:
                stack.append(element)
    return out


def left_out(raw: bytes) -> list[tuple[str, Element, str]]:
    """The elements that stand at a line break that ``tighten_main`` leaves out of this main part: for a break after the tag of a block, that block; for a break before the
    closing tag of a block, that block. ``(where, element, kind)``, the kind ``open`` (after an opening tag), ``close`` (after a closing tag) or ``end`` (before a closing tag)."""
    html = raw.decode("utf-8")
    start, end = html.find("<main"), html.find("</main>")
    main = html[start : end + 1]
    tags = tags_of(main)
    by_end = {t[1]: t for t in tags}
    by_start = {t[0]: t for t in tags}
    found = []
    for pattern in (build._BLOCK_GAP, build._BLOCK_END):
        for m in re.finditer(pattern.pattern.decode("ascii"), main):
            gap_start, gap_end = m.start(), m.end()  # (the tag before the break ends the match without its break: the break is the last character)
            before = by_end.get(gap_end - 1)
            after = by_start.get(gap_end)
            if pattern is build._BLOCK_GAP and after is not None and after[2]:
                # (a break before the closing tag of the parent is the end of its line, whatever stands before it: it is the parent that must not be inline)
                found.append(("before the closing tag of", after[3], "end"))
            elif pattern is build._BLOCK_GAP and before is not None:
                found.append(("after the closing tag of" if before[2] else "after the opening tag of", before[3], "close" if before[2] else "open"))
            if pattern is build._BLOCK_END and after is not None:
                found.append(("before the closing tag of", after[3], "end"))
            if after is None and before is None:
                raise AssertionError(f"a break that the pass leaves out is between no two tags: {main[max(0, gap_start - 40):gap_end + 40]!r}")
    return found


def matches(element: Element, subject: Compound) -> bool:
    if subject.tag not in (None, "*") and subject.tag != element.tag:
        return False
    if subject.ident is not None and subject.ident != element.attrs.get("id"):
        return False
    return subject.classes <= element.classes


def guard(raw_pages: dict[str, bytes], css: str) -> list[str]:
    """What is wrong: an element next to a line break that the pass leaves out that a rule of ``css`` makes inline."""
    rules = inline_subjects(css)
    wrong: dict[str, str] = {}
    for name, raw in raw_pages.items():
        for where, element, kind in left_out(raw):
            for selector, subject, display in rules:
                # (the white space after the closing tag of an inline element is drawn between it and the next, whatever kind of inline it is; the white space inside one, at its
                # start or its end, is drawn only if the element is `inline`: an inline-block, a flex or a grid container drops it)
                if (kind == "close" or display == "inline") and matches(element, subject):
                    wrong[f"{where} {element.describe()} {selector}"] = f"{name}: a line break {where} {element.describe()} is left out, and the stylesheet draws it inline by {selector}"
    return sorted(wrong.values())


# ---- the tests ---------------------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """A real build of the site fixture, with the trio pages that ``tighten_main`` was given kept, and the stylesheet that was built."""
    need_node()
    tmp = tmp_path_factory.mktemp("tighten-css")
    seen: dict[str, bytes] = {}
    real = build.tighten_main

    def keep(html: bytes) -> bytes:
        seen[f"page-{len(seen) + 1}"] = html
        return real(html)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(build, "tighten_main", keep)
        run_build(tmp / "dist", tmp)
    sheets = sorted((tmp / "dist" / "assets").glob("*.css"))
    assert seen and sheets
    return seen, "\n".join(sheet.read_text(encoding="utf-8") for sheet in sheets)


def test_no_line_break_is_left_out_next_to_an_element_that_the_stylesheet_draws_inline(built):
    pages, css = built
    assert guard(pages, css) == []


def test_the_pass_leaves_out_breaks_in_the_pages_it_is_given(built):
    pages, _ = built
    assert sum(len(left_out(raw)) for raw in pages.values()) > 100  # (the guard looks at something)
    assert {kind for raw in pages.values() for _, _, kind in left_out(raw)} == {"open", "close", "end"}


def test_the_guard_sees_an_element_made_inline_and_does_not_mind_one_that_is_not():
    page = b'<html><main>\n<ul>\n<li class="chip">a</li>\n<li class="chip">b</li>\n</ul>\n<div class="x">\n<span class="s">t</span>\n</div>\n</main></html>'
    plain = ".other { display: inline-block }\n.s { display: inline }\n.chip::before { display: inline-block; content: '' }\nli.x { display: inline }\n"
    assert guard({"p": page}, plain) == []  # (a span is no block; a pseudo-element is no element; a class that is not there is not there)
    for rule in (".chip { display: inline-block }", "ul .chip, .foo { display: inline }", "li { display: inline-flex }", "@media (min-width: 1px) { .chip:hover { display: inline } }", "#a, li.chip { display: inline-table; color: red }"):
        wrong = guard({"p": page}, rule)
        assert wrong and "line break" in wrong[0], rule
    assert guard({"p": page}, ".x { display: inline }")  # the div that closes after a break is the one
    assert guard({"p": page}, "div { display: block }\n.chip { display: flex }") == []
    # inside an inline-block or a flex container the white space at its start and end is not drawn, after its closing tag it is
    inside = b'<main>\n<div class="box">\n<span>a</span>\n</div>\n<div class="next">b</div>\n</main>'
    assert guard({"p": inside}, ".box { display: inline-flex }")  # (the break after the closing tag of the box, before the next block)
    assert [w for w in guard({"p": inside}, ".box { display: inline-flex }") if "after the opening tag" in w or "before the closing tag" in w] == []
    assert any("after the opening tag" in w for w in guard({"p": inside}, ".box { display: inline }"))


def test_the_selectors_of_the_stylesheet_are_read_to_their_subject():
    assert subject_of("ul.plain > li.chip:hover") == Compound("li", frozenset({"chip"}), None)
    assert subject_of(".kit tbody th:not(:has(> .art))::before") is None
    assert subject_of("#runnerups-body td[data-f='x']:nth-child(2)") == Compound("td", frozenset(), None)
    assert subject_of("a#top.nav") == Compound("a", frozenset({"nav"}), "top")
    assert [(s, d) for s, _, d in inline_subjects("a, b { display: inline-block }\nc { display: inline-size; }")] == [("a", "inline-block"), ("b", "inline-block")]
