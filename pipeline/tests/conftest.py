"""Fixtures that every test of the pipeline gets."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def folder_of_the_scheduled_checks_is_the_tests_own(tmp_path_factory, monkeypatch):
    """The scheduled checks leave their stamps, logs and reports in one folder outside every worktree, and the release build reads the stamps from it (see
    ``trioforge.checks_dir``). That folder is a place on the maintainer's computer: a test must neither read nor write it, so each test gets a folder of its own
    in ``TRIOFORGE_CHECKS_DIR`` (a test that wants the variable unset or another says so)."""
    monkeypatch.setenv("TRIOFORGE_CHECKS_DIR", str(tmp_path_factory.mktemp("checks-folder")))


@pytest.fixture(autouse=True)
def the_build_settings_of_the_shell_do_not_reach_a_test(monkeypatch):
    """The site build takes two optional settings from the environment, page counts (``$TRIOFORGE_ANALYTICS_TOKEN``) and the Search Console file (``$TRIOFORGE_GOOGLE_VERIFICATION``), which a maintainer
    sets in the shell to build a release (CONTRIBUTING.md suggests it). A test must not build a counting site, or write the file, because of what the shell holds: both are cleared for every test (a test that
    wants one sets it itself). ``test_site_analytics.py`` runs a probe in a process of its own with both set, to show it."""
    monkeypatch.delenv("TRIOFORGE_ANALYTICS_TOKEN", raising=False)
    monkeypatch.delenv("TRIOFORGE_GOOGLE_VERIFICATION", raising=False)


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


def pytest_addoption(parser):
    parser.addoption(
        "--shard",
        default=None,
        metavar="I/N",
        help="run only the test files of shard I of N (the CI job runs the suite as a matrix of shards; see shards.py): a file is in exactly one shard",
    )


def pytest_collection_modifyitems(config, items):
    """With ``--shard I/N`` keep the tests of the files that belong to shard I (shards.py); the rest are deselected, so a run without the option is the whole suite."""
    text = config.getoption("--shard")
    if text is None:
        return
    import shards

    try:
        index, count = shards.parse(text)
    except ValueError as error:
        raise pytest.UsageError(str(error)) from None
    kept, dropped = [], []
    for item in items:
        (kept if shards.shard_of(item.path.name, count) == index else dropped).append(item)
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = kept
