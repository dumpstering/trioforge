"""Checks on repository files: CI workflows, issue forms, licences, docs and the dependency lock.

Nothing here imports ``trioforge``. The tests read files, and one section loads
``scripts/lock_hashes.py`` (the script that adds hashes to ``requirements.lock``) with its
network access replaced by a stub, so no test needs the network.

YAML is read with PyYAML, which follows YAML 1.1: the workflow key ``on`` arrives as the
boolean ``True`` (see ``_triggers``), and an unquoted ``+1`` is the integer 1.
"""

import codecs
import fnmatch
import importlib.util
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
import urllib.error
from collections import Counter
from importlib import metadata
from pathlib import Path

import pytest
import yaml

# Installed with pytest and pinned in requirements.lock; used only to evaluate the
# environment markers of installed packages in the lock-completeness test.
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
ISSUE_DIR = ROOT / ".github" / "ISSUE_TEMPLATE"

PRIVACY_WARNING = (
    "Do not include character names, player names, chat lines or screenshots of chat. "
    "Item names, zones and NPC names are fine."
)
DISCLAIMER = (
    "TrioForge is a fan project, not affiliated with or endorsed by Daybreak Game Company. "
    "EverQuest is a registered trademark of Daybreak Game Company LLC."
)
CC_BY_SA_LINK = "creativecommons.org/licenses/by-sa/4.0"
EQLWIKI_URI = "https://eqlwiki.com/"
DAYBREAK_EXCLUSION = (
    "Game facts derived from Daybreak Game Company's files are Daybreak's and fall "
    "outside this grant. This includes `derived/client/` and the race base stats "
    "and class modifiers in `rules/races.json`"
)
EQEMU_ACKNOWLEDGEMENT = (
    "Some formulas and constants are modelled on the EQEmu server project "
    "(https://github.com/EQEmu/Server, GPL-3.0); no EQEmu code is used"
)

# Built by concatenation so that a repo-wide search for the forbidden trigger stays empty.
FORBIDDEN_TRIGGER = "pull_request" + "_target"
# The opening of a GitHub Actions expression, split so this file has no such expression.
EXPRESSION_OPEN = "$" + "{{"

# The privacy job. The privacy key never goes to GitHub: any code that reaches the repository
# can read a CI secret, and the published digests would become a dictionary of names. So CI runs
# only the checks that need no key (log shapes, local paths, program-file words, archives, who
# made each commit); the denylist is checked by the git hooks on the maintainer's computer.
PRIVACY_SCAN = "python -m trioforge.privacy.scan --all --history"
# The address comes from the committed file. It is checked only on a push to main: on a pull
# request, actions/checkout builds a merge commit that GitHub authors, which would never pass.
IDENTITY_SCAN = "python -m trioforge.privacy.scan --identity-file privacy/identity.txt"
IDENTITY_CONDITION = "github.event_name == 'push'"
# The placeholder identity of the maintainers until the public account exists.
IDENTITY_FILE_CONTENT = "maintainers@trioforge.invalid\n"

# One entry per issue form: its labels; the required fields (casefolded label -> element
# type, or None where the type is left open); the optional fields; and the dropdown choices
# (casefolded).
ISSUE_FORMS = {
    "wrong-item.yml": {
        "labels": ["data"],
        "required": {"page": None, "item": None, "what is wrong": "textarea", "source": None},
        "optional": {},
        "choices": {},
    },
    "page-problem.yml": {
        "labels": ["site"],
        "required": {"page": None, "what is wrong": "textarea"},
        "optional": {},
        "choices": {},
    },
    "seen-in-game.yml": {
        "labels": ["seen-report", "needs-check"],
        "required": {
            "item": None,
            "zone": None,
            "how obtained": "dropdown",
            "tier seen": "dropdown",
            "evidence": "textarea",
            "image check": "checkboxes",
        },
        "optional": {},
        "choices": {
            "how obtained": ["loot", "quest reward", "vendor", "crafted", "other"],
            "tier seen": [f"+{n}" for n in range(11)],
        },
    },
    "rule-correction.yml": {
        "labels": ["rules"],
        "required": {
            "rule id": None,
            "what the rule should be": None,
            "evidence": None,
            "confidence": "dropdown",
        },
        "optional": {},
        "choices": {"confidence": ["client file", "developer", "measured", "player reports"]},
    },
}

# Public files that must never point at a private location (a drive path, a user profile
# directory, or the private tree next to this repository).
PUBLIC_TEXT_FILES = [
    "README.md",
    "NOTICE.md",
    "LICENSE-DATA",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/RESUME.md",
    "docs/runbook-moderation.md",
    "scripts/lock_hashes.py",
    ".github/pull_request_template.md",
    ".github/workflows/test.yml",
    ".github/ISSUE_TEMPLATE/wrong-item.yml",
    ".github/ISSUE_TEMPLATE/page-problem.yml",
    ".github/ISSUE_TEMPLATE/seen-in-game.yml",
    ".github/ISSUE_TEMPLATE/rule-correction.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
]
PRIVATE_LOCATION = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]|[\\/]Users[\\/]|eql[\\/]", re.IGNORECASE)

# Wording that points at the private planning documents: a numbered task, an appendix, a
# section sign, a numbered phase's plan, or a statement of what the plan demands. Nothing in
# a public file may cite them.
SECTION_SIGN = chr(0xA7)
RIGHT_SINGLE_QUOTE = chr(0x2019)
PRIVATE_DOCUMENT_REFERENCE = re.compile(
    "|".join(
        [
            r"\b[Tt]ask \d",
            r"\bAppendix [A-Z]\b",
            re.escape(SECTION_SIGN),
            r"\bPhase \d plan\b",
            r"\b[Pp]lan(?:'s|" + RIGHT_SINGLE_QUOTE + r"s| table)\b",
            r"\b(?:[Tt]he|[Tt]his|[Oo]ur) plan (?:requires|asks|says|leaves|lists|specifies)\b",
            r"\bspec (?:v\d|Appendix)\b",
        ]
    )
)

# Files that still cite those documents and are being rewritten by other work in progress.
# fnmatch patterns on the posix path relative to the repository root. Delete an entry as
# soon as its file is clean; nothing else may be added.
PENDING_CITATION_CLEANUP = ()
SKIPPED_DIRECTORIES = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".hypothesis",
    "dist",
    ".wrangler",
}


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Collapse all whitespace so a sentence wrapped over several lines still matches."""
    return " ".join(text.split())


# ---- YAML --------------------------------------------------------------------------------


class _UniqueKeyLoader(yaml.SafeLoader):
    """The loader behind ``yaml.safe_load``, which also refuses a mapping that repeats a key.

    PyYAML silently keeps the last of two equal keys, so a second ``permissions:`` block
    could override the first without any test noticing.
    """


def _refuse_duplicate_keys(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        if isinstance(key_node, yaml.ScalarNode):
            key = loader.construct_object(key_node, deep=True)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found the key {key!r} twice",
                    key_node.start_mark,
                )
            seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _refuse_duplicate_keys
)


def load_yaml(text: str):
    """Parse one YAML document with the safe loader; a repeated mapping key is an error."""
    return yaml.load(text, Loader=_UniqueKeyLoader)  # a SafeLoader subclass, never the full loader


def _triggers(workflow: dict):
    """The ``on`` block. YAML 1.1 (PyYAML) reads the bare key ``on`` as the boolean True."""
    keys = [key for key in ("on", True) if key in workflow]
    assert len(keys) == 1, f"expected exactly one 'on' block, found keys {list(workflow)}"
    return workflow[keys[0]]


def test_yaml_loader_refuses_a_repeated_key_at_any_depth():
    with pytest.raises(yaml.YAMLError):
        load_yaml("a: 1\na: 2\n")
    with pytest.raises(yaml.YAMLError):
        load_yaml("outer:\n  inner: 1\n  inner: 2\n")
    assert load_yaml("a: 1\nb: 2\n") == {"a": 1, "b": 2}


def test_yaml_loader_reads_the_on_key_as_true_and_triggers_copes_with_both_readings():
    assert load_yaml("on:\n  push:\n") == {True: {"push": None}}
    assert _triggers({True: "pushed"}) == "pushed"
    assert _triggers({"on": "quoted"}) == "quoted"


# ---- workflows: the hardening rules, applied to every file under .github/workflows -------

USES_REF = re.compile(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}")
VERSION_COMMENT = re.compile(
    r"^[ \t]*(?:-[ \t]+)?uses:[ \t]*[\"']?(?P<ref>[^\s\"'#]+)[\"']?[ \t]+#[ \t]*v\d",
    re.MULTILINE,
)
NPM_CI = re.compile(r"(?:^|\s)npm\s+(?:ci|clean-install|ic|install-clean|isntall-clean)(?=\s|$)")
PIP_INSTALL = re.compile(r"(?:^|\s)(?:pip3?|(?:py|python3?)\s+-m\s+pip3?)\s+install(?=\s|$)")
SAFE_PERMISSION_LEVELS = ("read", "none")
MAX_TIMEOUT_MINUTES = 30


def _workflow_files() -> list[Path]:
    files = sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")])
    assert files, "no workflow files under .github/workflows"
    return files


def _walk(node, path=()):
    """Yield (path, node) for every node of a parsed YAML tree, the root first."""
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, (*path, key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, (*path, index))


def _where(path) -> str:
    return ".".join(str(part) for part in path) or "<root>"


def _commands(script: str) -> list[str]:
    """The simple commands of a ``run:`` script, split at line ends, ``&&``, ``||``, ``;``, ``|``."""
    joined = script.replace("\\\n", " ")
    return [part.strip() for part in re.split(r"&&|\|\||[;|\n]", joined) if part.strip()]


def _permission_problems(where: str, permissions) -> list[str]:
    if not isinstance(permissions, dict):
        return [f"{where}: must be a mapping of scope to read or none, not {permissions!r}"]
    return [
        f"{where}.{scope}: {level!r} is not read or none"
        for scope, level in permissions.items()
        if level not in SAFE_PERMISSION_LEVELS
    ]


def _run_problems(where: str, script: str) -> list[str]:
    problems = []
    if EXPRESSION_OPEN in script:
        problems.append(f"{where}: run contains a {EXPRESSION_OPEN} expression")
    for command in _commands(script):
        tokens = command.split()
        if NPM_CI.search(command) and "--ignore-scripts" not in tokens:
            problems.append(f"{where}: npm ci without --ignore-scripts")
        if PIP_INSTALL.search(command) and "--require-hashes" not in tokens:
            problems.append(f"{where}: pip install without --require-hashes")
    return problems


def workflow_problems(text: str) -> list[str]:
    """Every way the workflow ``text`` breaks the hardening rules. Empty means it keeps them."""
    problems = []
    if FORBIDDEN_TRIGGER in text:
        problems.append(f"mentions {FORBIDDEN_TRIGGER}")
    try:
        workflow = load_yaml(text)
    except yaml.YAMLError as error:
        return [*problems, f"not valid YAML: {error}"]
    if not isinstance(workflow, dict):
        return [*problems, "not a mapping"]

    permissions = workflow.get("permissions")
    problems += _permission_problems("permissions", permissions)
    if isinstance(permissions, dict) and permissions.get("contents") != "read":
        problems.append("permissions.contents must be read")

    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        problems.append("jobs: none")
        jobs = {}
    for name, job in jobs.items():
        where = f"jobs.{name}"
        if not isinstance(job, dict):
            problems.append(f"{where}: not a mapping")
            continue
        if "permissions" in job:
            problems += _permission_problems(f"{where}.permissions", job["permissions"])
        timeout = job.get("timeout-minutes")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or not 1 <= timeout <= MAX_TIMEOUT_MINUTES
        ):
            problems.append(
                f"{where}: timeout-minutes must be a whole number from 1 to {MAX_TIMEOUT_MINUTES}"
            )

    pinned = []
    for path, node in _walk(workflow):
        if not isinstance(node, dict):
            continue
        where = _where(path)
        if "continue-on-error" in node:
            problems.append(f"{where}: continue-on-error")
        if isinstance(node.get("run"), str):
            problems += _run_problems(f"{where}.run", node["run"])
        if "uses" in node:
            ref = node["uses"]
            if isinstance(ref, str) and USES_REF.fullmatch(ref):
                pinned.append(ref)
            else:
                problems.append(f"{where}: uses {ref!r} is not owner/repo@<40 hex digits>")
            if isinstance(ref, str) and ref.startswith("actions/setup-node@"):
                options = node.get("with") or {}
                if options.get("package-manager-cache") is not False:
                    problems.append(f"{where}: setup-node needs package-manager-cache: false")

    # The tag comment is not part of the parsed tree, so it is read from the text: every
    # pinned reference needs a line that carries it.
    commented = [match["ref"] for match in VERSION_COMMENT.finditer(text)]
    for ref in Counter(pinned) - Counter(commented):
        problems.append(f"uses {ref}: no ' # v<tag>' comment naming the tag")
    return problems


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda path: path.name)
def test_workflow_keeps_the_hardening_rules(path):
    assert workflow_problems(path.read_text(encoding="utf-8")) == []


GOOD_WORKFLOW = """\
name: demo
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0
        with:
          node-version: "24"
          package-manager-cache: false
      - run: npm ci --ignore-scripts
      - run: python -m pip install --require-hashes -r requirements.lock
"""


def _broken(old: str, new: str) -> str:
    assert GOOD_WORKFLOW.count(old) == 1, f"{old!r} must occur exactly once in GOOD_WORKFLOW"
    return GOOD_WORKFLOW.replace(old, new)


# (case id, a workflow with one defect, a fragment the reported problems must contain)
BAD_WORKFLOWS = [
    (
        "continue-on-error on a step",
        _broken(
            "      - run: npm ci --ignore-scripts\n",
            "      - run: npm ci --ignore-scripts\n        continue-on-error: true\n",
        ),
        "continue-on-error",
    ),
    (
        "continue-on-error on a job",
        _broken("    timeout-minutes: 10\n", "    timeout-minutes: 10\n    continue-on-error: true\n"),
        "continue-on-error",
    ),
    ("no top-level permissions", _broken("permissions:\n  contents: read\n", ""), "permissions"),
    (
        "top-level contents write",
        _broken("  contents: read\n", "  contents: write\n"),
        "permissions.contents",
    ),
    (
        "top-level extra write scope",
        _broken("  contents: read\n", "  contents: read\n  id-token: write\n"),
        "permissions.id-token",
    ),
    (
        "job-level write scope",
        _broken(
            "    runs-on: ubuntu-latest\n",
            "    runs-on: ubuntu-latest\n    permissions:\n      contents: write\n",
        ),
        "jobs.check.permissions.contents",
    ),
    (
        "job-level write-all",
        _broken("    runs-on: ubuntu-latest\n", "    runs-on: ubuntu-latest\n    permissions: write-all\n"),
        "jobs.check.permissions",
    ),
    (
        "expression inside run",
        _broken(
            "      - run: python -m pip install --require-hashes -r requirements.lock\n",
            "      - run: echo ${{ github.event.pull_request.title }}\n",
        ),
        EXPRESSION_OPEN,
    ),
    (
        "action pinned to a tag",
        _broken(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
            "actions/checkout@v7 # v7.0.1",
        ),
        "actions/checkout@v7",
    ),
    (
        "action pinned to a short sha",
        _broken(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
            "actions/checkout@3d3c42e # v7.0.1",
        ),
        "actions/checkout@3d3c42e",
    ),
    (
        "unpinned action in flow style, which a line regex would miss",
        _broken(
            "      - run: npm ci --ignore-scripts\n",
            '      - {uses: "actions/cache@v4"}\n      - run: npm ci --ignore-scripts\n',
        ),
        "actions/cache@v4",
    ),
    (
        "pinned action without the tag comment",
        _broken(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
        ),
        "no ' # v<tag>' comment",
    ),
    ("job without a timeout", _broken("    timeout-minutes: 10\n", ""), "timeout-minutes"),
    (
        "timeout above the limit",
        _broken("timeout-minutes: 10", "timeout-minutes: 31"),
        "timeout-minutes",
    ),
    (
        "timeout written as a string",
        _broken("timeout-minutes: 10", 'timeout-minutes: "10"'),
        "timeout-minutes",
    ),
    (
        "setup-node with the package-manager cache left on",
        _broken("          package-manager-cache: false\n", ""),
        "package-manager-cache",
    ),
    (
        "setup-node with the package-manager cache switched on",
        _broken("package-manager-cache: false", "package-manager-cache: true"),
        "package-manager-cache",
    ),
    (
        "npm ci that runs install scripts",
        _broken("npm ci --ignore-scripts", "npm ci"),
        "npm ci without --ignore-scripts",
    ),
    (
        "npm ci that hides behind another command's flag",
        _broken("npm ci --ignore-scripts", "npm ci && npm test --ignore-scripts"),
        "npm ci without --ignore-scripts",
    ),
    (
        "pip install without hashes",
        _broken("pip install --require-hashes -r", "pip install -r"),
        "pip install without --require-hashes",
    ),
    (
        "the privileged pull-request trigger",
        _broken("on:\n  push:\n    branches: [main]\n", "on:\n  " + FORBIDDEN_TRIGGER + ":\n"),
        FORBIDDEN_TRIGGER,
    ),
    (
        "a second permissions block that would override the first",
        GOOD_WORKFLOW + "permissions:\n  contents: write\n",
        "not valid YAML",
    ),
]


def test_the_workflow_guard_accepts_a_hardened_workflow():
    assert workflow_problems(GOOD_WORKFLOW) == []


@pytest.mark.parametrize(
    ("text", "fragment"),
    [pytest.param(text, fragment, id=case) for case, text, fragment in BAD_WORKFLOWS],
)
def test_the_workflow_guard_rejects_each_defect(text, fragment):
    problems = workflow_problems(text)
    assert any(fragment in problem for problem in problems), problems


def test_the_command_splitter_finds_each_command_of_a_script():
    script = "npm ci \\\n  --ignore-scripts && npm test\necho a; echo b | cat"
    assert _commands(script) == ["npm ci    --ignore-scripts", "npm test", "echo a", "echo b", "cat"]


# ---- test.yml: the shape it must have -----------------------------------------------------


def _workflow(name: str = "test.yml") -> dict:
    return load_yaml((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def _job(name: str) -> dict:
    return _workflow()["jobs"][name]


def _step_actions(job: dict) -> list[str]:
    return [step["uses"].split("@")[0] for step in job["steps"] if "uses" in step]


def _step_commands(job: dict) -> list[str]:
    return [step["run"] for step in job["steps"] if "run" in step]


def _step_with_condition(job: dict, condition: str) -> dict:
    matches = [step for step in job["steps"] if step.get("if") == condition]
    assert len(matches) == 1, f"expected exactly one step with the condition {condition!r}"
    return matches[0]


def test_workflow_runs_on_push_to_main_and_on_pull_requests_only():
    triggers = _triggers(_workflow())
    assert set(triggers) == {"push", "pull_request"}
    assert triggers["push"] == {"branches": ["main"]}


def test_workflow_has_exactly_the_python_js_and_privacy_jobs_on_ubuntu():
    jobs = _workflow()["jobs"]
    assert set(jobs) == {"python", "js", "privacy"}
    for name, job in jobs.items():
        # the image is pinned like the actions are: GitHub moves ubuntu-latest to Ubuntu 26 on 2026-10-19, and a move of the runner should be a commit of ours
        assert job["runs-on"] == "ubuntu-24.04", name


def test_checkout_never_persists_the_token():
    for path in _workflow_files():
        for name, job in load_yaml(path.read_text(encoding="utf-8"))["jobs"].items():
            for step in job["steps"]:
                if step.get("uses", "").startswith("actions/checkout@"):
                    assert step.get("with", {}).get("persist-credentials") is False, (
                        f"{path.name}:{name}"
                    )


def test_python_job_installs_the_hashed_lock_and_runs_pytest():
    job = _job("python")
    # Node and esbuild come with it (L9): the tests of the site build need them, and the step of pytest requires them (the test after the js job's, below)
    assert _step_actions(job) == ["actions/checkout", "actions/setup-node", "actions/setup-python"]
    setup = next(step for step in job["steps"] if "setup-python" in step.get("uses", ""))
    assert setup["with"]["python-version"] == "3.12"
    assert _step_commands(job) == [
        "npm ci --ignore-scripts",
        "python -m pip install --require-hashes -r requirements.lock",
        'python -m pytest --shard "$SHARD"',  # (Q2: the job is a matrix of shards; test_shards.py holds the matrix)
    ]


FIXTURES_COMMAND = "python -m trioforge.export.fixtures --out build/fixtures --seed 20261014"


def test_js_job_installs_from_the_lockfile_without_scripts_and_runs_the_tests():
    job = _job("js")
    # the parity tests of the engine read the full fixtures, which the job makes with Python first (the next test)
    assert _step_actions(job) == ["actions/checkout", "actions/setup-node", "actions/setup-python"]
    setup = next(step for step in job["steps"] if "setup-node" in step.get("uses", ""))
    assert setup["with"] == {"node-version": "24", "package-manager-cache": False}
    assert _step_commands(job) == [
        "npm ci --ignore-scripts",
        "python -m pip install --require-hashes -r requirements.lock",
        FIXTURES_COMMAND,
        "npm test",
    ]


def test_js_job_makes_the_full_fixtures_before_the_tests_and_makes_the_tests_ask_for_them():
    job = _job("js")
    steps = job["steps"]
    python = next(step for step in steps if "setup-python" in step.get("uses", ""))
    assert python["with"] == {"python-version": "3.12"}
    make = next(step for step in steps if step.get("run") == FIXTURES_COMMAND)
    test = next(step for step in steps if step.get("run") == "npm test")
    assert steps.index(python) < steps.index(make) < steps.index(test)
    assert make["env"] == {"PYTHONPATH": "pipeline"}
    # with this set, a missing full set fails the tests instead of skipping them; the value is a text, as the runner passes it
    assert test["env"] == {"TRIOFORGE_FULL_FIXTURES": "1"}


def test_privacy_job_checks_out_the_whole_history_and_installs_nothing():
    job = _job("privacy")
    assert _step_actions(job) == ["actions/checkout", "actions/setup-python"]
    checkout = job["steps"][0]
    assert checkout["with"] == {"fetch-depth": 0, "persist-credentials": False}
    assert not [command for command in _step_commands(job) if "install" in command]


def test_privacy_job_runs_only_the_checks_that_need_no_key():
    job = _job("privacy")
    scans = [step for step in job["steps"] if step.get("run") == PRIVACY_SCAN]
    assert len(scans) == 1, "expected exactly one step with the keyless scan"
    scan = scans[0]
    assert "if" not in scan  # it runs for every event: a push and a pull request alike
    assert scan["env"] == {"PYTHONPATH": "pipeline"}

    identity = _step_with_condition(job, IDENTITY_CONDITION)
    assert identity["run"] == IDENTITY_SCAN
    assert identity["env"] == {"PYTHONPATH": "pipeline"}

    assert [step for step in job["steps"] if "run" in step] == [scan, identity]


def test_the_commit_identity_is_checked_only_on_a_push():
    job = _job("privacy")
    checking = [step for step in job["steps"] if "--identity" in step.get("run", "")]
    assert len(checking) == 1
    assert checking[0]["if"] == IDENTITY_CONDITION
    # The push trigger is the branch main only (see the test of the triggers).
    assert _triggers(_workflow())["push"] == {"branches": ["main"]}


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda path: path.name)
def test_no_workflow_gives_the_privacy_key_to_github_or_asks_for_a_key(path):
    text = path.read_text(encoding="utf-8")
    assert "privacy_key" not in text.casefold()
    workflow = load_yaml(text)
    for name, job in workflow["jobs"].items():
        for step in job["steps"]:
            command = step.get("run", "")
            assert "--key-file" not in command and "--require-key" not in command, (
                f"{path.name}:{name}: a CI step must not need the key"
            )


def test_the_test_workflow_uses_no_secret_at_all():
    text = (WORKFLOW_DIR / "test.yml").read_text(encoding="utf-8")
    assert "secrets." not in text and "secrets[" not in text


def test_the_identity_file_names_the_placeholder_address():
    assert _read("privacy/identity.txt") == IDENTITY_FILE_CONTENT


@pytest.mark.parametrize("name", ["pre-commit", "commit-msg", "pre-push"])
def test_the_hooks_on_the_maintainers_computer_check_with_the_key(name):
    commands = [
        line
        for line in _read(f"scripts/hooks/{name}").splitlines()
        if "trioforge.privacy.scan" in line or line.lstrip().startswith("--")
    ]
    assert "--require-key" in " ".join(commands)


def test_the_pre_push_hook_reads_the_pushed_refs_and_the_committed_identity():
    text = _flat(_read("scripts/hooks/pre-push"))
    assert '--pre-push "$1"' in text
    assert "--identity-file privacy/identity.txt" in text
    assert "--history" in text and "--all" in text


def test_every_step_that_runs_the_package_sets_pythonpath_to_pipeline():
    checked = 0
    for path in _workflow_files():
        for name, job in load_yaml(path.read_text(encoding="utf-8"))["jobs"].items():
            for step in job["steps"]:
                if "python -m trioforge" in step.get("run", ""):
                    checked += 1
                    env = step.get("env", {})
                    assert env.get("PYTHONPATH") == "pipeline", f"{path.name}:{name}"
    assert checked, "no step runs python -m trioforge"


def test_scanner_imports_with_only_the_standard_library():
    # The privacy job installs nothing, so the scanner must run on a bare interpreter:
    # -I ignores the environment and -S skips site-packages, which holds every dependency.
    if not (ROOT / "pipeline" / "trioforge" / "privacy" / "scan.py").is_file():
        pytest.skip("the privacy scanner is not in the tree yet")
    code = "import sys; sys.path.insert(0, sys.argv[1]); import trioforge.privacy.scan"
    done = subprocess.run(
        [sys.executable, "-I", "-S", "-c", code, str(ROOT / "pipeline")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr


# ---- issue forms --------------------------------------------------------------------------


def _is_required(element) -> bool:
    """Whether a field of an issue form must be filled in: its validations say so; a group of checkboxes has no validations, and is required when an option of it is."""
    if element["type"] == "checkboxes":
        return any(option.get("required") is True for option in element["attributes"]["options"])
    return element.get("validations", {}).get("required") is True


@pytest.mark.parametrize("filename", sorted(ISSUE_FORMS))
def test_issue_form_parses_warns_about_privacy_and_requires_its_fields(filename):
    spec = ISSUE_FORMS[filename]
    form = load_yaml((ISSUE_DIR / filename).read_text(encoding="utf-8"))

    for key in ("name", "description"):
        assert isinstance(form[key], str) and form[key].strip(), f"{filename}: empty {key}"
    assert form["labels"] == spec["labels"]

    # The privacy warning comes first, as a markdown block, word for word.
    first = form["body"][0]
    assert first["type"] == "markdown"
    assert PRIVACY_WARNING in _flat(first["attributes"]["value"])

    fields = {}
    ids = []
    for element in form["body"]:
        if element["type"] == "markdown":
            continue
        label = element["attributes"]["label"].casefold()
        assert label not in fields, f"{filename}: duplicate label {label!r}"
        fields[label] = element
        if "id" in element:
            assert re.fullmatch(r"[A-Za-z0-9_-]+", element["id"]), element["id"]
            ids.append(element["id"])
    assert len(ids) == len(set(ids)), f"{filename}: duplicate ids"

    # Exactly the planned fields, nothing more.
    assert set(fields) == set(spec["required"]) | set(spec["optional"])

    for label, kind in spec["required"].items():
        element = fields[label]
        assert _is_required(element), f"{filename}: {label!r} must have validations.required: true (a group of checkboxes: an option that is required)"
        if kind is not None:
            assert element["type"] == kind, f"{filename}: {label!r} should be a {kind}"
    for label, kind in spec["optional"].items():
        element = fields[label]
        assert not _is_required(element)
        assert element["type"] == kind

    for label, expected in spec["choices"].items():
        options = fields[label]["attributes"]["options"]
        assert all(isinstance(option, str) for option in options), (
            f"{filename}: {label!r} options must all be strings (quote '+1' and the like)"
        )
        assert [option.casefold() for option in options] == expected
        assert len(set(options)) == len(options)


def test_seen_in_game_evidence_field_says_to_crop_your_name_out():
    form = load_yaml((ISSUE_DIR / "seen-in-game.yml").read_text(encoding="utf-8"))
    evidence = next(
        element for element in form["body"]
        if element["type"] != "markdown" and element["attributes"]["label"] == "Evidence"
    )
    assert "crop your name out" in evidence["attributes"]["description"].casefold()


SEEN_FORM = ISSUE_DIR / "seen-in-game.yml"
IMAGE_CHECK = "My image shows only the item window: no names, no chat"


def _seen_form():
    return load_yaml(SEEN_FORM.read_text(encoding="utf-8"))


def test_seen_in_game_form_has_a_required_checkbox_that_the_image_shows_only_the_item_window():
    boxes = [element for element in _seen_form()["body"] if element["type"] == "checkboxes"]
    assert len(boxes) == 1
    options = boxes[0]["attributes"]["options"]
    assert [option["label"] for option in options] == [IMAGE_CHECK]
    assert all(option.get("required") is True for option in options)  # (a group of checkboxes has no validations: each option says for itself)
    assert "validations" not in boxes[0]


def test_seen_in_game_form_asks_for_a_crop_of_the_item_window_only_as_an_upload_and_for_no_log_line():
    form = _seen_form()
    evidence = next(
        element for element in form["body"]
        if element["type"] != "markdown" and element["attributes"]["label"] == "Evidence"
    )
    assert evidence["type"] == "textarea" and evidence["validations"]["required"] is True  # (a text box takes an image dragged into it)
    text = _flat(evidence["attributes"]["description"]).casefold()
    for needle in ("drag", "crop", "item window", "chat", "every other window"):
        assert needle in text, needle
    assert "/outputfile" not in text and "log line" not in text  # a line of the log holds a character name
    assert "item window" in _flat(form["body"][0]["attributes"]["value"]).casefold()  # the opening block says what a maintainer will check


def test_seen_in_game_form_flags_the_report_for_the_maintainers_check_and_never_says_it_is_checked():
    labels = _seen_form()["labels"]
    assert "needs-check" in labels and "seen-report" in labels
    assert "screenshot-checked" not in labels  # that label is the maintainer's, set after the check


def test_issue_chooser_config_disables_blank_issues():
    config = load_yaml((ISSUE_DIR / "config.yml").read_text(encoding="utf-8"))
    assert config["blank_issues_enabled"] is False


def test_issue_chooser_config_links_to_the_security_policy_of_a_real_account_or_not_at_all():
    """The link to the security policy needs the account that will own the repository. Until there is one the file has no link:
    the placeholder account name is a real account of someone else, and the chooser must never send a reader there. When the
    link is added it is still the policy of the repository and says that the report is private."""
    text = (ISSUE_DIR / "config.yml").read_text(encoding="utf-8")
    assert "OWNER" not in text  # the placeholder is not in the file
    config = load_yaml(text)
    links = config.get("contact_links", [])
    assert len(links) <= 1
    for link in links:
        for key in ("name", "url", "about"):
            assert isinstance(link[key], str) and link[key].strip(), f"contact link: empty {key}"
        assert re.fullmatch(r"https://github\.com/[^/\s]+/[^/\s]+/security/policy", link["url"])
        assert "/OWNER/" not in link["url"]
        assert "private" in link["about"].casefold()


# ---- the moderation runbook ---------------------------------------------------------------

RUNBOOK = "docs/runbook-moderation.md"
REPORT_REASONS = ["withdrawn", "wrong-item", "rejected", "duplicate"]  # the reasons of a retraction (trioforge.community.REASONS; this file imports nothing of trioforge)


def _runbook() -> str:
    return _flat(_read(RUNBOOK)).casefold()


def test_the_runbook_says_how_to_check_a_report_and_that_the_wiki_outweighs_it():
    text = _runbook()
    for needle in ("item window", IMAGE_CHECK.casefold(), "`needs-check`", "`screenshot-checked`", "outweigh", "derived/catalog.json", "no free text"):
        assert needle in text, needle


def test_the_runbook_says_what_outweighs_a_report_and_when_a_report_that_was_outweighed_counts():
    """The wiki's marks and a zone that is closed outweigh a report; the report waits, and counts from the release in which the mark goes or the zone opens, which is a
    release whose report of results says so (an edit of the wiki must not put an item in the kits without the maintainer reading that)."""
    text = _runbook()
    for needle in (
        "every zone is unreleased or not part of eql",
        "a screenshot shows that the item is in the game's data, not that anyone can get it",
        "from the release in which the mark is taken off or the zone is opened",
        "strict now because of a report",
        "release.json",
        "no longer strict, the report retracted",
        "no longer strict, the report outweighed",
        "recorded in this release for the first time",
    ):
        assert needle in text, needle


def test_the_runbook_has_the_command_to_add_and_the_command_to_retract_with_every_reason():
    text = _runbook()
    assert "python -m trioforge.community add --key" in text and "--screenshot-checked" in text and "--kind seen" in text
    assert "python -m trioforge.community retract --issue" in text and "--reason" in text
    for reason in REPORT_REASONS:
        assert f"`{reason}`" in text, reason
    for needle in ("results diff", "community evidence", "next release"):
        assert needle in text, needle  # a retraction shows in the report of the next release


def test_the_runbook_says_how_to_delete_revisions_and_ask_github_support_to_purge_an_attachment():
    text = _runbook()
    for needle in ("delete revision", "edited", "github support", "purge", "attachment", "character name", "chat"):
        assert needle in text, needle


def test_the_runbook_says_how_to_set_the_interaction_limits():
    text = _runbook()
    for needle in ("interaction limits", "existing users", "prior contributors", "repository collaborators", "moderation options"):
        assert needle in text, needle


def test_the_runbook_lists_every_label_of_the_issue_forms_and_the_ones_of_the_check_and_how_to_create_them():
    text = _runbook()
    labels = {label for spec in ISSUE_FORMS.values() for label in spec["labels"]} | {"needs-check", "screenshot-checked", "retracted"}
    assert labels >= {"seen-report", "data", "site", "rules"}
    for label in sorted(labels):
        assert f"`{label}`" in text, label
    assert "gh label create" in text


def test_the_runbook_has_no_reason_that_labels_the_account_of_a_reporter():
    """A reason stays in a public file beside an issue number for good, so the list holds none that says what the person did."""
    text = _runbook()
    assert "`abuse`" not in text and "`rejected`" in text
    assert "says nothing about the person" in text


def _incident_steps() -> tuple[str, list[str]]:
    """The section of the runbook about a name or chat in an attachment (flattened, casefolded) and its numbered steps."""
    section = _read(RUNBOOK).split("## A name or chat in an attachment", 1)[1].split("\n## ", 1)[0]
    steps = [_flat(line.split(". ", 1)[1]).casefold() for line in section.splitlines() if re.match(r"\d+\. ", line)]
    return _flat(section).casefold(), steps


def test_the_first_step_of_an_incident_is_to_hide_or_delete_the_content():
    section, steps = _incident_steps()
    assert len(steps) >= 5 and steps[0].startswith("hide or delete")
    assert "make the content unreachable first" in section


def test_nothing_public_is_added_to_an_incident_until_the_attachment_is_gone():
    """Between hiding the content and the purge of the attachment, a label, a comment, a retraction or a commit that names the issue would point at a picture that can still be opened."""
    section, steps = _incident_steps()
    purge = next(number for number, step in enumerate(steps) if "ask github support to purge" in step)
    wait = next(number for number, step in enumerate(steps) if "add nothing public" in step)
    retract = next(number for number, step in enumerate(steps) if "retract it" in step)
    assert purge < wait < retract
    for needle in ("until the attachment is gone", "no label", "no comment", "no retraction", "no commit"):
        assert needle in steps[wait], needle
    for number in range(wait):
        assert not any(word in steps[number] for word in ("retract it", "set the label", "close the issue")), (number, steps[number])
    assert "before the attachment is gone" in _runbook()  # the table of labels says so beside `retracted`


def _documented_commands() -> list[list[str]]:
    """The commands of the reports that the runbook shows in its code blocks, each as its words."""
    blocks = re.findall(r"```\n(.*?)```", _read(RUNBOOK), re.DOTALL)
    return [shlex.split(line) for block in blocks for line in block.splitlines() if "trioforge.community" in line]


def test_the_commands_of_the_runbook_are_written_the_way_the_repository_runs_a_module():
    """``PYTHONPATH=pipeline python -m trioforge.<module>`` from the root, as the pull request template and the guide for contributors write it; on PowerShell the path is set first."""
    commands = _documented_commands()
    assert [words[words.index("-m") + 2] for words in commands] == ["add", "retract"]
    assert all(words[:4] == ["PYTHONPATH=pipeline", "python", "-m", "trioforge.community"] for words in commands), commands
    assert '$env:pythonpath = "pipeline"' in _runbook()


def test_the_commands_of_the_runbook_run_as_written_from_the_root_of_a_repository(tmp_path):
    """Run word for word, from the root of a repository of the test's own (a copy of the package and a catalog of one invented wearable), with the environment the line sets
    and no other path to the package: the first command adds the report the second retracts."""
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "pipeline" / "trioforge", root / "pipeline" / "trioforge", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (root / "derived").mkdir()
    (root / "derived" / "catalog.json").write_text(json.dumps({"items": [{"key": "w123", "name": "Invented Cap", "slots": ["HEAD"]}]}), encoding="utf-8")
    commands = _documented_commands()
    assert len(commands) == 2
    for words in commands:
        words = list(words)
        environment = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
        while "=" in words[0] and not words[0].startswith("-"):
            name, value = words.pop(0).split("=", 1)
            environment[name] = value
        assert words[:3] == ["python", "-m", "trioforge.community"]
        done = subprocess.run([sys.executable, *words[1:]], cwd=root, env=environment, capture_output=True, text=True, timeout=120, check=False)
        assert done.returncode == 0 and done.stderr == "", (words, done.stderr)
    document = json.loads((root / "rules" / "community-seen.json").read_text(encoding="utf-8"))
    assert document["reports"] == [] and [(entry["key"], entry["issue"], entry["reason"]) for entry in document["retracted"]] == [("w123", 5, "withdrawn")]


def test_the_command_of_the_runbook_needs_the_path_it_names(tmp_path):
    """Without PYTHONPATH=pipeline the module is not found: the line of the runbook is not a decoration."""
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "pipeline" / "trioforge", root / "pipeline" / "trioforge", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    environment = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    done = subprocess.run([sys.executable, "-m", "trioforge.community", "--help"], cwd=root, env=environment, capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode != 0 and "No module named" in done.stderr


def test_the_runbook_names_no_person_and_no_account_only_the_owner_of_the_build_as_a_placeholder():
    text = _read(RUNBOOK)
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text), "an e-mail address"
    assert not re.search(r"(?<![\w.])github\.com/(?!<owner>)", text), "an address of a concrete account"
    assert "<owner>" in text


# ---- licences -----------------------------------------------------------------------------


@pytest.mark.parametrize("filename", ["README.md", "NOTICE.md", "LICENSE-DATA"])
def test_licence_texts_carry_the_disclaimer_and_the_cc_by_sa_link(filename):
    text = _flat(_read(filename))
    assert DISCLAIMER in text
    assert CC_BY_SA_LINK in text


def test_data_licence_covers_rules_excludes_daybreaks_facts_and_gives_the_eqlwiki_uri():
    text = _read("LICENSE-DATA")
    covered = text.split("This licence covers:")[1].split("The code in this repository")[0]
    assert [line for line in covered.splitlines() if line.startswith("- ")] == [
        "- derived/",
        "- fixtures/",
        "- rules/",
        "- the generated site data",
    ]
    assert DAYBREAK_EXCLUSION in _flat(text)
    assert EQLWIKI_URI in text


def test_readme_names_rules_among_the_data_covered_by_cc_by_sa():
    assert "`rules/`" in _flat(_read("README.md"))


def test_notice_gives_the_eqlwiki_uri_and_the_eqemu_acknowledgement():
    text = _flat(_read("NOTICE.md"))
    assert EQLWIKI_URI in text
    assert EQEMU_ACKNOWLEDGEMENT in text


def test_package_manifests_declare_the_mit_licence():
    assert _read("LICENSE").startswith("MIT License")
    assert json.loads(_read("package.json"))["license"] == "MIT"
    assert tomllib.loads(_read("pyproject.toml"))["project"]["license"] == "MIT"


# ---- requirements.lock --------------------------------------------------------------------

PIN_LINE = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[A-Za-z0-9.!+_-]+)"
    r"(?P<options>(?:\s+--hash=sha256:[0-9a-f]{64})*)"
)
_PLATFORMS = (
    {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt"},
    {"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix"},
    {"sys_platform": "darwin", "platform_system": "Darwin", "os_name": "posix"},
)


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _read_pins(relative: str) -> dict[str, tuple[str, list[str]]]:
    """name -> (version, hashes) for a requirements file; a hashed pin spans several lines."""
    pins = {}
    for line in _read(relative).replace("\\\n", " ").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN_LINE.fullmatch(line)
        assert match, f"{relative}: not an exact name==version pin with --hash options: {line!r}"
        name = _canonical(match["name"])
        assert name not in pins, f"{relative}: {name} is pinned twice"
        pins[name] = (match["version"], re.findall(r"--hash=sha256:([0-9a-f]{64})", match["options"]))
    return pins


def _dependency_closure(roots, environment: dict) -> set[str]:
    """Names of the installed distributions reachable from ``roots`` under ``environment``."""
    seen: set[str] = set()
    todo = list(roots)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            requires = metadata.distribution(name).requires or []
        except metadata.PackageNotFoundError:
            continue  # a dependency of another platform, not installed here
        for text in requires:
            requirement = Requirement(text)
            marker = requirement.marker
            if marker is None or marker.evaluate({**environment, "extra": ""}):
                todo.append(_canonical(requirement.name))
    return seen


def test_requirements_txt_holds_plain_exact_pins_including_pyyaml():
    requirements = _read_pins("requirements.txt")
    assert requirements, "requirements.txt is empty"
    assert all(not hashes for _, hashes in requirements.values())
    assert requirements["pyyaml"][0] == "6.0.3"


def test_lock_pins_every_requirement_at_the_same_version():
    requirements = _read_pins("requirements.txt")
    lock = _read_pins("requirements.lock")
    for name, (version, _) in requirements.items():
        found = lock.get(name, (None, []))[0]
        assert found == version, f"{name}: requirements.txt says {version}, lock says {found}"


def test_lock_is_lf_only_and_ends_with_a_newline():
    data = (ROOT / "requirements.lock").read_bytes()
    assert data.endswith(b"\n")
    assert b"\r" not in data


def test_every_lock_pin_carries_sha256_hashes_in_sorted_order_without_repeats():
    lock = _read_pins("requirements.lock")
    assert lock, "requirements.lock is empty"
    for name, (version, hashes) in lock.items():
        assert hashes, f"{name}=={version}: no --hash=sha256 option"
        assert hashes == sorted(set(hashes)), f"{name}=={version}: hashes unsorted or repeated"


def test_lock_is_the_full_transitive_pin_set():
    requirements = set(_read_pins("requirements.txt"))
    lock = set(_read_pins("requirements.lock"))

    # Every platform needs its own conditional dependencies, and --require-hashes refuses
    # one that is not pinned, so the lock must name them all, whichever machine made it.
    possible = _dependency_closure(requirements, {})
    for environment in _PLATFORMS:
        possible |= _dependency_closure(requirements, environment)

    missing = possible - lock
    assert not missing, f"dependencies missing from the lock: {sorted(missing)}"
    stale = lock - possible
    assert not stale, f"lock pins packages nothing depends on: {sorted(stale)}"


# ---- scripts/lock_hashes.py: adds the hashes, offline here ---------------------------------

HASH_A, HASH_B, HASH_C = "a" * 64, "b" * 64, "c" * 64


@pytest.fixture(scope="module")
def lock_hashes():
    path = ROOT / "scripts" / "lock_hashes.py"
    if not path.is_file():
        pytest.fail("scripts/lock_hashes.py does not exist")
    spec = importlib.util.spec_from_file_location("lock_hashes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release(name: str, version: str, *digests: str) -> dict:
    """The part of a PyPI JSON release document that the script reads."""
    return {
        "info": {"name": name, "version": version},
        "urls": [{"filename": f"file{n}", "digests": {"sha256": d}} for n, d in enumerate(digests)],
    }


def test_script_reads_plain_and_hashed_pins_alike(lock_hashes):
    plain = "# comment\nAlpha==1.0\n\nbeta_two==2.5.1\n"
    hashed = (
        f"# header\nAlpha==1.0 \\\n    --hash=sha256:{HASH_A} \\\n    --hash=sha256:{HASH_B}\n"
        f"beta_two==2.5.1 \\\n    --hash=sha256:{HASH_C}\n"
    )
    expected = [("Alpha", "1.0"), ("beta_two", "2.5.1")]
    assert lock_hashes.parse_lock(plain) == expected
    assert lock_hashes.parse_lock(hashed) == expected


@pytest.mark.parametrize(
    "text",
    [
        "alpha>=1.0\n",
        "alpha\n",
        "-e .\n",
        "alpha==1.0 ; python_version < '3.13'\n",
        "git+https://example.invalid/alpha.git\n",
        "alpha==1.0 --hash=md5:" + "a" * 32 + "\n",
        "alpha==1.0\nAlpha==1.0\n",  # the same package twice
        "# only a comment\n",  # no pins at all
        "",
    ],
)
def test_script_refuses_anything_but_exact_pins(lock_hashes, text):
    with pytest.raises(lock_hashes.LockError):
        lock_hashes.parse_lock(text)


def test_script_collects_the_sha256_of_every_file_sorted_and_without_repeats(lock_hashes):
    release = _release("alpha", "1.0", HASH_B, HASH_A, HASH_B)
    assert lock_hashes.sha256_digests(release) == [HASH_A, HASH_B]


@pytest.mark.parametrize(
    "release",
    [
        {"info": {}, "urls": []},
        {"info": {}},
        {"urls": [{"filename": "f", "digests": {}}]},
        {"urls": [{"filename": "f", "digests": {"md5": "a" * 32}}]},
        {"urls": [{"filename": "f", "digests": {"sha256": "A" * 64}}]},
        {"urls": [{"filename": "f", "digests": {"sha256": "a" * 63}}]},
    ],
)
def test_script_refuses_a_release_without_a_usable_sha256_for_every_file(lock_hashes, release):
    with pytest.raises(lock_hashes.LockError):
        lock_hashes.sha256_digests(release)


def test_script_renders_pins_sorted_by_name_with_one_hash_per_continuation_line(lock_hashes):
    entries = [
        (lock_hashes.Pin("Zeta_pkg", "2.0"), [HASH_C]),
        (lock_hashes.Pin("alpha", "1.0"), [HASH_A, HASH_B]),
    ]
    text = lock_hashes.render_lock(entries)
    assert text == (
        lock_hashes.HEADER
        + f"alpha==1.0 \\\n    --hash=sha256:{HASH_A} \\\n    --hash=sha256:{HASH_B}\n"
        + f"Zeta_pkg==2.0 \\\n    --hash=sha256:{HASH_C}\n"
    )
    assert lock_hashes.HEADER.startswith("#")
    assert lock_hashes.parse_lock(text) == [("alpha", "1.0"), ("Zeta_pkg", "2.0")]


def test_script_fetches_the_json_of_the_exact_release_from_pypi_only(lock_hashes):
    seen = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout=None):
        seen["url"], seen["timeout"] = request.full_url, timeout
        return Response(json.dumps(_release("typing-extensions", "4.16.0", HASH_A)).encode())

    release = lock_hashes.fetch_release("typing_extensions", "4.16.0", urlopen=urlopen)
    assert seen["url"] == "https://pypi.org/pypi/typing-extensions/4.16.0/json"
    assert isinstance(seen["timeout"], (int, float)) and seen["timeout"] > 0
    assert lock_hashes.sha256_digests(release) == [HASH_A]


@pytest.mark.parametrize(
    "answer",
    [
        json.dumps(_release("other-package", "4.16.0", HASH_A)).encode(),  # another package
        json.dumps(_release("typing-extensions", "4.15.0", HASH_A)).encode(),  # another version
        b"not json",
        b"[]",
        urllib.error.URLError("unreachable"),
    ],
)
def test_script_refuses_an_answer_that_is_not_the_requested_release(lock_hashes, answer):
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout=None):
        if isinstance(answer, Exception):
            raise answer
        return Response(answer)

    with pytest.raises(lock_hashes.LockError):
        lock_hashes.fetch_release("typing_extensions", "4.16.0", urlopen=urlopen)


def _fake_fetch(releases: dict):
    def fetch(name, version):
        return releases[(name, version)]

    return fetch


def test_script_rewrites_the_lock_with_the_hashes_and_a_second_run_changes_nothing(
    lock_hashes, tmp_path
):
    lock = tmp_path / "requirements.lock"
    lock.write_text("zeta==2.0\nalpha==1.0\n", encoding="utf-8", newline="\n")
    fetch = _fake_fetch(
        {
            ("alpha", "1.0"): _release("alpha", "1.0", HASH_B, HASH_A),
            ("zeta", "2.0"): _release("zeta", "2.0", HASH_C),
        }
    )

    assert lock_hashes.main(["--lock", str(lock)], fetch=fetch) == 0
    first = lock.read_bytes()
    assert first.decode("utf-8") == (
        lock_hashes.HEADER
        + f"alpha==1.0 \\\n    --hash=sha256:{HASH_A} \\\n    --hash=sha256:{HASH_B}\n"
        + f"zeta==2.0 \\\n    --hash=sha256:{HASH_C}\n"
    )
    assert b"\r" not in first

    assert lock_hashes.main(["--lock", str(lock)], fetch=fetch) == 0
    assert lock.read_bytes() == first


def test_script_leaves_the_lock_untouched_when_any_lookup_fails(lock_hashes, tmp_path, capsys):
    lock = tmp_path / "requirements.lock"
    original = "alpha==1.0\nzeta==2.0\n"
    lock.write_text(original, encoding="utf-8", newline="\n")

    def fetch(name, version):
        if name == "zeta":
            raise lock_hashes.LockError("PyPI lists no files for this release")
        return _release(name, version, HASH_A)

    assert lock_hashes.main(["--lock", str(lock)], fetch=fetch) == 1
    assert lock.read_text(encoding="utf-8") == original
    assert "zeta==2.0" in capsys.readouterr().err


def test_script_reads_a_lock_with_a_utf8_bom_and_names_the_problem_with_utf16(
    lock_hashes, tmp_path, capsys
):
    fetch = _fake_fetch({("alpha", "1.0"): _release("alpha", "1.0", HASH_A)})

    with_bom = tmp_path / "bom.lock"
    with_bom.write_bytes(codecs.BOM_UTF8 + b"alpha==1.0\n")
    assert lock_hashes.main(["--lock", str(with_bom)], fetch=fetch) == 0
    assert not with_bom.read_bytes().startswith(codecs.BOM_UTF8)

    # Windows PowerShell 5 writes UTF-16 when it redirects with ">".
    utf16 = tmp_path / "utf16.lock"
    utf16.write_bytes("alpha==1.0\n".encode("utf-16"))
    before = utf16.read_bytes()
    assert lock_hashes.main(["--lock", str(utf16)], fetch=fetch) == 1
    assert utf16.read_bytes() == before
    assert "UTF-8" in capsys.readouterr().err


def test_lock_file_is_exactly_what_the_script_writes(lock_hashes):
    # Catches a hand edit: the order, the header and the layout must be the script's own.
    hashes = {name: found for name, (_, found) in _read_pins("requirements.lock").items()}
    pins = lock_hashes.parse_lock(_read("requirements.lock"))
    entries = [(pin, hashes[_canonical(pin.name)]) for pin in pins]
    assert lock_hashes.render_lock(entries) == _read("requirements.lock")


# ---- contributor docs and status ----------------------------------------------------------


def test_contributing_states_the_privacy_rule_the_hook_the_tests_and_the_licences():
    text = _flat(_read("CONTRIBUTING.md"))
    assert PRIVACY_WARNING in text
    assert "sh scripts/install-hooks.sh" in text
    assert "python -m pytest" in text
    assert "npm test" in text
    assert "CC BY-SA 4.0" in text
    assert "MIT" in text
    assert "privacy" in text.casefold()


def test_contributing_uses_the_hardened_install_steps_and_names_rules_among_the_data():
    text = _flat(_read("CONTRIBUTING.md"))
    assert "--require-hashes -r requirements.lock" in text
    assert "-r requirements.lock" in text and "-r requirements.txt" not in text
    assert "npm ci --ignore-scripts" in text
    assert "pip freeze" in text and "python scripts/lock_hashes.py" in text
    data = [line for line in _read("CONTRIBUTING.md").splitlines() if line.startswith("- Data")]
    assert len(data) == 1 and "`rules/`" in data[0]


def test_contributing_documents_the_browser_tests_the_preview_and_every_variable_they_read():
    text = _flat(_read("CONTRIBUTING.md"))
    for command in ("npm ci --ignore-scripts", "npx playwright install chromium", "npm run e2e", "npm run preview"):
        assert command in text, command
    scripts = json.loads(_read("package.json"))["scripts"]
    assert "playwright test" in scripts["e2e"] and "scripts/preview.mjs" in scripts["preview"]  # the commands the text names exist
    # every TRIOFORGE_ variable that the e2e configuration or the preview script reads is explained, so a new one cannot go unmentioned
    variables = set()
    for name in ("playwright.config.mjs", "scripts/preview.mjs"):
        variables |= set(re.findall(r"process\.env\.(TRIOFORGE_[A-Z_]+)", _read(name)))
    assert {"TRIOFORGE_RESULTS", "TRIOFORGE_PREVIEW_PORT"} <= variables
    for variable in sorted(variables):
        assert f"`{variable}`" in text, variable


def test_contributing_says_the_privacy_key_stays_on_the_maintainers_computer():
    text = _flat(_read("CONTRIBUTING.md"))
    assert "never given to GitHub" in text
    assert "does not need the key" in text  # what CI checks instead


def test_contributing_describes_the_history_the_push_and_the_identity_checks():
    text = _flat(_read("CONTRIBUTING.md")).casefold()
    for phrase in (
        "whole history",
        "about to send",  # what a push is about to send
        "privacy/identity.txt",
        "utc",
        "--explain",
    ):
        assert phrase in text, phrase


def test_contributing_lists_the_known_limits_of_the_scanner():
    text = _flat(_read("CONTRIBUTING.md"))
    for phrase in (
        "capital letters scattered through a name",
        "plain space",
        "an image",
        "other than a zip file",
        "deeper than six rounds",
    ):
        assert phrase in text, phrase


def test_security_policy_uses_private_advisories_and_says_there_is_no_server():
    text = _flat(_read("SECURITY.md")).casefold()
    assert "private" in text
    assert "security advisory" in text
    assert "no server" in text
    assert "in the browser" in text


def test_readme_installs_the_python_dependencies_from_the_hashed_lock():
    text = _read("README.md")
    assert "--require-hashes -r requirements.lock" in text
    assert "-r requirements.txt" not in text


def test_resume_file_says_phase_0_is_in_progress_and_nothing_is_published():
    text = _flat(_read("docs/RESUME.md"))
    assert "Phase 0 in progress; nothing published" in text
    assert not re.search(r"\b(done|complete|completed|finished)\b", text, re.IGNORECASE)


def test_pull_request_template_has_the_privacy_checkbox():
    text = _flat(_read(".github/pull_request_template.md"))
    assert "- [ ]" in text
    assert "character names" in text


@pytest.mark.parametrize("relative", PUBLIC_TEXT_FILES)
def test_public_files_do_not_mention_private_locations(relative):
    for number, line in enumerate(_read(relative).splitlines(), start=1):
        assert not PRIVATE_LOCATION.search(line), f"{relative}:{number} mentions a private location"


# ---- no citations of the private planning documents ---------------------------------------


def _repository_text_files():
    """(posix path relative to the root, text) of every text file, without tool and cache folders."""
    for folder, subfolders, names in os.walk(ROOT):
        parts = Path(folder).relative_to(ROOT).parts
        subfolders[:] = sorted(
            name
            for name in subfolders
            if name not in SKIPPED_DIRECTORIES and not (parts[:1] == ("sources",) and name == "raw")
        )
        for name in sorted(names):
            path = Path(folder, name)
            data = path.read_bytes()
            if b"\0" in data[:8192]:
                continue  # binary
            yield path.relative_to(ROOT).as_posix(), data.decode("utf-8", errors="replace")


@pytest.mark.parametrize(
    "sample",
    [
        "(see Task" + " 1 report)",
        "the Task" + " 3b list",
        "Appendix" + " B of the plan",
        "spec Appendi" + "x D",
        "plan " + SECTION_SIGN + "5.6",
        "the Phase 0" + " plan",
        "the plan" + "'s table",
        "the fields the plan" + " requires",
    ],
)
def test_private_document_pattern_catches_the_wording_contributors_used(sample):
    assert PRIVATE_DOCUMENT_REFERENCE.search(sample)


@pytest.mark.parametrize(
    "sample",
    [
        "Exact best-in-slot gear plans for every class trio",
        "Next: Phase 1, public-safe data",
        "a plan for the gear",
        "the spec dictionary of a form",
        "a task runner",
        "see the NOTICE file",
    ],
)
def test_private_document_pattern_leaves_ordinary_wording_alone(sample):
    assert not PRIVATE_DOCUMENT_REFERENCE.search(sample)


def test_public_files_do_not_cite_private_documents():
    offenders = []
    for relative, text in _repository_text_files():
        if any(fnmatch.fnmatch(relative, pattern) for pattern in PENDING_CITATION_CLEANUP):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if PRIVATE_DOCUMENT_REFERENCE.search(line):
                offenders.append(f"{relative}:{number}")
    assert not offenders, f"these lines cite private documents: {offenders}"


# ---- the python job of CI runs the Node tests (Part L, L9) ----------------------------------------------------------------------------------------------


def _steps(job: dict) -> list[dict]:
    return [step for step in job["steps"] if isinstance(step, dict)]


def test_the_python_job_has_node_and_the_packages_and_requires_the_node_tests_so_they_run_in_ci_and_do_not_skip():
    workflow = load_yaml((WORKFLOW_DIR / "test.yml").read_text(encoding="utf-8"))
    python_steps, js_steps = _steps(workflow["jobs"]["python"]), _steps(workflow["jobs"]["js"])
    node = [step for step in python_steps if str(step.get("uses", "")).startswith("actions/setup-node@")]
    js_node = [step for step in js_steps if str(step.get("uses", "")).startswith("actions/setup-node@")]
    assert len(node) == 1 and node == js_node, "the python job sets Node up exactly as the js job does (the same pinned action and version)"
    runs = [str(step.get("run", "")) for step in python_steps]
    install = next(at for at, run in enumerate(runs) if NPM_CI.search(run))
    assert "--ignore-scripts" in runs[install]
    pytest_at = next(at for at, run in enumerate(runs) if "pytest" in run)
    assert install < pytest_at, "the packages are installed before the tests run"
    assert python_steps[pytest_at].get("env", {}).get("TRIOFORGE_REQUIRE_NODE") == "1", "a test that needs Node fails instead of skipping"
    assert all("playwright" not in run for job in workflow["jobs"].values() for run in (str(step.get("run", "")) for step in _steps(job))), "no browser test runs in CI"


def test_the_documents_of_the_repository_name_no_private_document_and_quote_no_chat():
    """R6: DECISIONS.md named a private document of the owner's, cited a report that is not in the repository and quoted the owner's chat; it states the decision plainly, and no document of docs/ has those words (the first is written in two pieces here, so that this file does not name it either)."""
    for path in sorted((ROOT / "docs").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for needle in ("answer" + " key", "the report of Part", "i dont care"):
            assert needle not in text, (path.name, needle)
    assert "the owner's decision of 2026-11-22" in (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
