"""Not a test of the suite (the name is not collected): ``test_site_analytics.py`` runs it in a process of its own with the two build settings in the environment, and it must find neither."""

import os


def test_the_two_settings_of_the_site_build_are_not_in_the_environment_of_a_test():
    # (only the names are looked at and shown: a failed assertion about os.environ itself would print the whole environment, secrets of the shell included)
    present = [name for name in ("TRIOFORGE_ANALYTICS_TOKEN", "TRIOFORGE_GOOGLE_VERIFICATION") if name in os.environ]
    assert present == []
