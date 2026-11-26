"""``build.tighten_main``: the line breaks between two tags that no browser draws, left out of the main part of a trio page.

The page pays for its bow controls with these (the largest trio page is a few bytes under its limit), so the function must leave out nothing a browser draws:
a break between two inline tags (two spans, a link and a link, a select and what follows it) is a gap on the screen and stays, and so does everything outside the
``<main>`` (the head, the scripts, the footer). Every markup here is invented.
"""

from __future__ import annotations

import pytest

from trioforge.site import build


def tight(text: str) -> str:
    return build.tighten_main(text.encode("utf-8")).decode("utf-8")


def test_the_breaks_between_blocks_items_cells_and_options_are_left_out():
    page = '<main id="main">\n<ul class="a">\n<li>one</li>\n<li>two</li>\n</ul>\n<p>x</p>\n<p>y</p>\n<table>\n<tr role="row">\n<th scope="row">h</th>\n<td>c</td>\n</tr>\n</table>\n</main>'
    assert tight(page) == '<main id="main">\n<ul class="a"><li>one</li><li>two</li></ul><p>x</p><p>y</p><table><tr role="row"><th scope="row">h</th><td>c</td></tr></table></main>'


def test_a_break_between_two_inline_tags_stays_for_it_is_a_gap_on_the_screen():
    page = '<main>\n<p><span>a</span>\n<span>b</span>\n<a href="/x">l</a>\n<a href="/y">m</a>\n<button>k</button>\n<label>n</label></p>\n</main>'
    assert tight(page) == '<main>\n<p><span>a</span>\n<span>b</span>\n<a href="/x">l</a>\n<a href="/y">m</a>\n<button>k</button>\n<label>n</label></p></main>'


def test_a_select_is_inline_so_the_break_after_it_stays_and_the_options_inside_it_do_not_need_one():
    page = '<main>\n<select id="s">\n<option>a</option>\n<option>b</option>\n</select>\n<span>after</span>\n</main>'
    assert tight(page) == '<main>\n<select id="s">\n<option>a</option><option>b</option></select>\n<span>after</span>\n</main>'


def test_a_folded_block_loses_the_break_after_its_opening_tag_and_keeps_the_one_after_its_end():
    page = '<main>\n<details class="x" id="d">\n<summary>s</summary>\n<p>a</p>\n</details>\n<p>b</p>\n</main>'
    assert tight(page) == '<main>\n<details class="x" id="d"><summary>s</summary><p>a</p></details>\n<p>b</p></main>'


def test_the_break_before_the_closing_tag_of_a_block_goes_after_any_tag_but_a_span():
    page = '<main>\n<div class="c">\n<button>k</button>\n</div>\n<p>t <a href="/x">l</a>\n</p>\n<ul>\n<li><span>s</span>\n</li>\n</ul>\n</main>'
    assert tight(page) == '<main>\n<div class="c"><button>k</button></div><p>t <a href="/x">l</a></p><ul><li><span>s</span>\n</li></ul></main>'


def test_a_tag_whose_name_only_starts_like_a_block_is_not_one():
    page = '<main>\n<link rel="x">\n<p>a</p>\n<pre>\n</pre>\n<param name="n">\n<p>b</p>\n<dialog>\n</dialog>\n</main>'
    assert tight(page) == '<main>\n<link rel="x">\n<p>a</p><pre>\n</pre>\n<param name="n">\n<p>b</p><dialog>\n</dialog>\n</main>'


def test_what_is_outside_the_main_part_is_as_it_was():
    head = '<head>\n<title>t</title>\n<script>\nvar a = "<li>\\n<li>";\n</script>\n</head>\n<body>\n<header>\n<p>a</p>\n<p>b</p>\n</header>\n'
    foot = "\n<footer>\n<p>c</p>\n<p>d</p>\n</footer>\n<script>\n</script>\n</body>"
    page = head + "<main>\n<p>x</p>\n<p>y</p>\n</main>" + foot
    assert tight(page) == head + "<main>\n<p>x</p><p>y</p></main>" + foot


def test_a_page_with_no_main_is_as_it_was():
    assert tight("<p>a</p>\n<p>b</p>\n") == "<p>a</p>\n<p>b</p>\n"
    assert tight("<main>\n<p>a</p>\n<p>b</p>\n") == "<main>\n<p>a</p>\n<p>b</p>\n"


@pytest.mark.parametrize(
    "page",
    [
        '<main>\n<ul>\n<li>a</li>\n<li>b <span>c</span>\n<span>d</span></li>\n</ul>\n<p>x <a href="/q">q</a>\n</p>\n</main>',
        "<main>\n</main>",
        '<main>\n<div>\n<div class="x">\n<span>s</span>\n</div>\n</div>\n</main>',
    ],
)
def test_it_only_takes_line_breaks_away_and_does_it_once(page):
    once = tight(page)
    assert tight(once) == once
    assert once.replace("\n", "") == page.replace("\n", "")


def test_an_apostrophe_or_a_quote_in_a_text_is_written_as_itself_and_one_in_a_tag_or_outside_the_main_part_stays_escaped():
    """The template's autoescape writes an apostrophe as five characters and a quote as five: in a text they are the character (4 bytes each, some 150 in a trio page), and in a tag (where a
    quote would end the value) and outside the main part they are as they were. The other escapes (the ampersand, the angle brackets) stay in every place."""
    page = (
        "<head><title>It&#39;s</title></head><main>\n<p title=\"a&#39;b &#34;c&#34;\">Ivandyr&#39;s &#34;Hoop&#34; &amp; &lt;b&gt; &#39;x</p>\n<p>y</p>\n</main><footer>Don&#39;t &#34;</footer>"
    )
    assert tight(page) == (
        "<head><title>It&#39;s</title></head><main>\n<p title=\"a&#39;b &#34;c&#34;\">Ivandyr's \"Hoop\" &amp; &lt;b&gt; 'x</p><p>y</p></main><footer>Don&#39;t &#34;</footer>"
    )
