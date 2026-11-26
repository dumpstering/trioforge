"""The Google Search Console ownership file as a setting of the build (Part J3).

The build takes an optional file name (``google`` and 16 hex digits and ``.html``: the name Google gives the site; ``--google-verification`` or ``$TRIOFORGE_GOOGLE_VERIFICATION``) and writes that file at the
root of the site with the one line Google expects. It is no page: it is not in the sitemap, nothing links to it, the page counts do not hold it. Without the option there is no such file. The name is
not committed: every name here is invented.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_site_build import (  # noqa: F401  (site is a fixture of test_site_build: the plain build of the fixture, once for this module as well)
    need_node,
    read,
    run_build,
    site,
)

from trioforge.site import build

VERIFICATION = "google0123456789abcdef.html"  # (invented)


def spy_on_the_command(monkeypatch):
    """The build is replaced by a function that records what the command gave it and stops, so the command line can be read without a build."""
    seen = []

    def stop(**kwargs):
        seen.append(kwargs)
        raise build.BuildError("stop here")

    monkeypatch.setattr(build, "build", stop)
    return seen


def html_files(out: Path):
    """The pages of a build (the Search Console file, which ends in .html as well, is none)."""
    return sorted(p.relative_to(out).as_posix() for p in out.rglob("*.html") if not p.name.startswith("google"))


def every_file(out: Path):
    return sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())


@pytest.fixture(scope="module")
def verified(tmp_path_factory):
    need_node()
    tmp = tmp_path_factory.mktemp("site-verified")
    out = tmp / "dist"
    return out, run_build(out, tmp, verification_file=VERIFICATION)



@pytest.mark.parametrize("name", [VERIFICATION, "google" + "0" * 16 + ".html", "googleabcdefabcdefabcd.html"[:0] + "googlefedcba9876543210.html"])
def test_a_verification_file_name_is_google_and_16_hex_digits_and_dot_html(name):
    assert build.check_verification_file(name) == name


@pytest.mark.parametrize(
    "name",
    ["", VERIFICATION[:-6], "google0123456789abcde.html", "google0123456789abcdef0.html", "google0123456789ABCDEF.html", "Google0123456789abcdef.html", "google0123456789abcdeg.html",
     VERIFICATION + "\n", " " + VERIFICATION, "./" + VERIFICATION, "sub/" + VERIFICATION, "../" + VERIFICATION, "\\" + VERIFICATION, VERIFICATION + ".txt", "google0123456789abcdef.htm",
     "google0123456789abcdef.html/", "robots.txt", "index.html", "_headers", None, 7],
    ids=lambda value: repr(value)[:36],
)
def test_any_other_verification_file_name_is_refused(name):
    with pytest.raises(build.BuildError, match="google"):
        build.check_verification_file(name)


def test_the_verification_file_is_one_line_at_the_root_and_nowhere_else(verified, site):  # noqa: F811
    out, summary = verified
    plain, plain_summary = site
    assert (out / VERIFICATION).read_bytes() == f"google-site-verification: {VERIFICATION}".encode("ascii")
    assert summary.files == plain_summary.files + 1
    assert summary.pages == plain_summary.pages, "it is no page: the page counts do not hold it"
    assert not (plain / VERIFICATION).exists() and [n for n in every_file(plain) if n.startswith("google")] == []
    assert [n for n in every_file(out) if n != VERIFICATION] == every_file(plain), "no other file is added or changed"
    for name in every_file(plain):
        assert (plain / name).read_bytes() == (out / name).read_bytes(), name
    assert VERIFICATION not in read(out, "sitemap.xml") and "google" not in read(out, "sitemap.xml")
    for name in html_files(out):
        assert "google" not in read(out, name).lower(), name  # (no page links to it or names it)


def test_a_bad_verification_file_name_stops_the_build_before_anything_is_made(tmp_path):
    out = tmp_path / "dist"
    with pytest.raises(build.BuildError, match="google"):
        run_build(out, tmp_path, verification_file="google-site.html")
    assert not out.exists()


def test_the_command_takes_the_verification_file_from_an_option_or_from_the_environment(tmp_path, monkeypatch, capsys):
    seen = spy_on_the_command(monkeypatch)
    monkeypatch.delenv(build.VERIFICATION_ENV, raising=False)
    assert build.main(["--results", str(tmp_path), "--out", str(tmp_path / "o")]) == 2
    assert seen[-1]["verification_file"] is None
    assert build.main(["--results", str(tmp_path), "--out", str(tmp_path / "o"), "--google-verification", VERIFICATION]) == 2
    assert seen[-1]["verification_file"] == VERIFICATION
    monkeypatch.setenv(build.VERIFICATION_ENV, "google" + "1" * 16 + ".html")
    assert build.main(["--results", str(tmp_path), "--out", str(tmp_path / "o")]) == 2
    assert seen[-1]["verification_file"] == "google" + "1" * 16 + ".html"
    assert build.main(["--results", str(tmp_path), "--out", str(tmp_path / "o"), "--google-verification", VERIFICATION]) == 2
    assert seen[-1]["verification_file"] == VERIFICATION, "the option wins over the variable"
    before = len(seen)
    monkeypatch.setenv(build.VERIFICATION_ENV, "notgoogle.html")
    capsys.readouterr()
    assert build.main(["--results", str(tmp_path), "--out", str(tmp_path / "o")]) == 2
    message = capsys.readouterr().err
    assert len(seen) == before and "google" in message and "notgoogle" not in message


def test_the_list_of_the_files_of_a_site_names_the_verification_file_when_there_is_one():
    assets = ["assets/site-AAAAAAAA.css", "assets/boot-BBBBBBBB.js", "assets/app-CCCCCCCC.js"]
    plain = build.site_files([], assets=assets)
    named = build.site_files([], assets=assets, verification=VERIFICATION)
    assert sorted(named) == sorted([*plain, VERIFICATION])
    assert len(named) == len(plain) + 1
    with pytest.raises(build.BuildError, match="google"):
        build.site_files([], assets=assets, verification="robots.txt")
