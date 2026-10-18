"""Page handlers for the catalog build tests: a worker process imports one of these by name.

A real handler (``trioforge.data.catalog:parse_and_normalize``) cannot be made to hang, crash or raise by any
page text, so the tests use this one to check that the build survives all three.
"""

import os
import time

from trioforge.data.catalog import parse_and_normalize


def target(page):
    title = page.get("title")
    if title == "Slow Page":
        time.sleep(120)
    elif title == "Crash Page":
        os._exit(3)
    elif title == "Raise Page":
        raise RuntimeError("a page the handler cannot read")
    return parse_and_normalize(page)
