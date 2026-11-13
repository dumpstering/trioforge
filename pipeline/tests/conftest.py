"""Fixtures that every test of the pipeline gets."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def folder_of_the_scheduled_checks_is_the_tests_own(tmp_path_factory, monkeypatch):
    """The scheduled checks leave their stamps, logs and reports in one folder outside every worktree, and the release build reads the stamps from it (see
    ``trioforge.checks_dir``). That folder is a place on the maintainer's computer: a test must neither read nor write it, so each test gets a folder of its own
    in ``TRIOFORGE_CHECKS_DIR`` (a test that wants the variable unset or another says so)."""
    monkeypatch.setenv("TRIOFORGE_CHECKS_DIR", str(tmp_path_factory.mktemp("checks-folder")))


@pytest.fixture(scope="session", autouse=True)
def the_fixture_results_are_not_made_from_the_real_catalog():
    """The site build makes the pictures of the armor from the catalog the results were made from, and stops when the catalog in ``derived/`` is not that one (it is the release's own, so a release
    never meets this). The synthetic results of the tests were not made from it, so a test that builds them is built without the item catalog, as the command line's ``--no-item-catalog`` says,
    unless the test gives a ``catalog`` or says ``without_item_catalog`` itself (the tests of the gate do: ``test_site_icons.py``). A process of its own (the command line) never meets this. The
    patch is made once for the session, since the builds of a module are made by fixtures of the module's scope."""
    import sys

    module = sys.modules.get("trioforge.site.build")
    if module is None:  # (no test module of this run has imported the build)
        yield
        return
    real = module.build

    def built(**kwargs):
        if "catalog" not in kwargs:
            kwargs.setdefault("without_item_catalog", True)
        return real(**kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module, "build", built)
        yield
