"""The static site generator: precompute results in, a folder of pages and files out.

* :mod:`trioforge.site.data` is the **only** reader of the precompute's result files. It turns them into a small
  documented model, and writes the compact files the browser fetches.
* :mod:`trioforge.site.view` words everything the pages show (labels, numbers, the trio page's contents).
* :mod:`trioforge.site.content` reads the other inputs of the pages (the rules file, the sources manifest, the
  changelog).
* :mod:`trioforge.site.build` is the command line and the orchestration: ``python -m trioforge.site.build``.

``templates/`` holds the Jinja2 templates (autoescape on, undefined values are errors) and ``static/`` the
stylesheet and the browser code, which esbuild bundles into content-hashed files.
"""
