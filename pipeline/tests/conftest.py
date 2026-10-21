"""Fixtures that every test of the pipeline gets."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def folder_of_the_scheduled_checks_is_the_tests_own(tmp_path_factory, monkeypatch):
    """The scheduled checks leave their stamps, logs and reports in one folder outside every worktree, and the release build reads the stamps from it (see
    ``trioforge.checks_dir``). That folder is a place on the maintainer's computer: a test must neither read nor write it, so each test gets a folder of its own
    in ``TRIOFORGE_CHECKS_DIR`` (a test that wants the variable unset or another says so)."""
    monkeypatch.setenv("TRIOFORGE_CHECKS_DIR", str(tmp_path_factory.mktemp("checks-folder")))
