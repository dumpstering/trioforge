"""A tiny strict HTML reader for the site tests: a tree of nodes you can query, built with the standard library.

It is strict on purpose. The site's templates write every end tag, so an unbalanced or unexpectedly closed element is a
bug in a template and raises ``AssertionError`` here, which makes every page test also a well-formedness test.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
_SPACE = re.compile(r"\s+")


class Node:
    def __init__(self, tag: str, attrs: dict[str, str | None], parent: Node | None = None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[Node | str] = []

    def __repr__(self) -> str:
        shown = " ".join(f'{k}="{v}"' for k, v in self.attrs.items())
        return f"<{self.tag} {shown}>".replace(" >", ">")

    # ---- reading -----------------------------------------------------------------------------------------------

    def get(self, name: str, default: str | None = None) -> str | None:
        return self.attrs.get(name, default)

    def has(self, name: str) -> bool:
        return name in self.attrs

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def text(self, *, skip_hidden: bool = False) -> str:
        """The text of the node and its descendants, whitespace collapsed."""
        parts: list[str] = []

        def walk(node: Node) -> None:
            for child in node.children:
                if isinstance(child, str):
                    parts.append(child)
                elif child.tag in ("script", "style", "template"):
                    continue
                elif skip_hidden and child.has("hidden"):
                    continue
                else:
                    walk(child)

        walk(self)
        return _SPACE.sub(" ", "".join(parts)).strip()

    def raw_text(self) -> str:
        return "".join(c for c in self.children if isinstance(c, str))

    # ---- searching ---------------------------------------------------------------------------------------------

    def iter(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.iter()

    def find_all(self, tag: str | None = None, **attrs: str | bool) -> list[Node]:
        """Descendants with this tag whose attributes match. ``True`` means 'present'; ``cls`` matches one class."""
        found = []
        for node in self.iter():
            if tag is not None and node.tag != tag:
                continue
            ok = True
            for name, wanted in attrs.items():
                if name == "cls":
                    ok = wanted in node.classes
                elif name == "id_":
                    ok = node.attrs.get("id") == wanted
                else:
                    key = name.replace("_", "-")
                    if wanted is True:
                        ok = key in node.attrs
                    else:
                        ok = node.attrs.get(key) == wanted
                if not ok:
                    break
            if ok:
                found.append(node)
        return found

    def find(self, tag: str | None = None, **attrs: str | bool) -> Node:
        found = self.find_all(tag, **attrs)
        assert found, f"no <{tag}> with {attrs} under {self!r}"
        return found[0]

    def by_id(self, ident: str) -> Node:
        for node in self.iter():
            if node.attrs.get("id") == ident:
                return node
        raise AssertionError(f"no element with id {ident!r}")

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", {})
        self.current = self.root
        self.doctype: str | None = None

    def handle_decl(self, decl: str) -> None:
        self.doctype = decl

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.current)
        self.current.children.append(node)
        if tag not in VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.current)
        self.current.children.append(node)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        assert self.current.tag == tag, f"unbalanced HTML: </{tag}> closes <{self.current.tag}>"
        assert self.current.parent is not None
        self.current = self.current.parent

    def handle_data(self, data):
        self.current.children.append(data)

    def handle_comment(self, data):  # comments never belong in the output
        raise AssertionError(f"HTML comment in the output: {data[:40]!r}")


def parse(html: str) -> Node:
    builder = _Builder()
    builder.feed(html)
    builder.close()
    assert builder.current is builder.root, f"unclosed <{builder.current.tag}>"
    builder.root.doctype = builder.doctype  # type: ignore[attr-defined]
    return builder.root


def extract_main(html: str) -> str:
    """The ``<main ...>...</main>`` element of a page, as text (what the JS tests load as the page body)."""
    start = html.index("<main")
    end = html.index("</main>") + len("</main>")
    return html[start:end] + "\n"
