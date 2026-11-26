"""Content rules: text that looks like a line from a game log, and text that a public repository
must not carry for another reason.

Each rule is a compiled pattern with bounded repetitions and no nested quantifiers, so a hostile
line cannot make the scanner slow. A name is a capital letter followed by at least two letters
(interior capitals are allowed).

* The ``log-*`` rules describe the lines the game client writes to its log: a time stamp in
  brackets, chat, loot, a ``/who`` row, a group change, and the player's own chat.
* ``local-path`` finds a path into a user's profile folder (on Windows, in Git Bash or WSL, on
  Linux or on macOS, and the share that Windows gives a WSL distribution's home folder); the
  placeholders ``<user>`` and ``<name>`` are not a user.
* ``provenance`` finds words that point at the game client's own program file: its name, a dump
  of its code, an address inside it, a section name. Nothing public may cite those.

The patterns describe such text in words, so this file must not contain any of it itself; its own
text is checked by the same rules in the repository scan. Where a pattern needs one of those
words or paths, it is written in pieces.
"""

from __future__ import annotations

import re

_NAME = r"[A-Z][A-Za-z]{2,}"

# A folder name that starts with one of these placeholders is not a private user name.
_NOT_A_PLACEHOLDER = r"(?!<(?:user|name)>)"
_HOME = "/" + "home" + "/"
_USERS = "/" + "Users" + "/"
_DATA_VOLUME = "/System/Volumes/Data"  # (the volume that holds the users' folders on a current macOS: a path that a tool prints in full has it before the folder for users)
_NOT_SHARED = r"(?!Shared(?![\w.-]))"  # (the folder that every user of the machine shares: a name that is "Shared" and then anything that is not part of a name, a slash, a quote, a comma, a bracket, a colon, white space or the end; "SharedBy", "Shared.name" and "Shared-x" are user names)

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "log-timestamp",
        re.compile(
            r"\[(Mon|Tue|Wed|Thu|Fri|Sat|Sun) "
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
            r"[ 0-9]\d \d\d:\d\d:\d\d \d{4}\]"
        ),
    ),
    (
        "log-tell",
        re.compile(
            r"\b" + _NAME + r" tells (you|the group|the guild|the raid|[A-Za-z]+:\d+), '"
        ),
    ),
    ("log-say", re.compile(r"\b" + _NAME + r" (says|shouts|auctions), '")),
    ("log-loot", re.compile(r"(You have looted|has looted) (a|an|the|\d+) ")),
    ("log-who", re.compile(r"\[\d{1,3} [A-Z][A-Za-z ]{2,30}\] " + _NAME + r" \(")),
    ("log-group", re.compile(r"\b" + _NAME + r" has (joined|left) the group")),
    ("log-ooc", re.compile(r"\b" + _NAME + r" says out of character, ")),
    ("log-told", re.compile(r"\bYou told " + _NAME + r", ")),
    (
        "log-self",
        re.compile(
            r"\bYou (?:say|shout|auction)(?: out of character| to your (?:party|guild|raid))?, '"
            r"|\bYou tell (?:your (?:party|guild|raid)|the (?:group|guild|raid)|[A-Za-z]+:\d+), '"
        ),
    ),
    # Windows: a drive letter, the folder for users, then a name.
    (
        "local-path",
        re.compile(r"[A-Za-z]:[\\/](?i:users)[\\/]" + _NOT_A_PLACEHOLDER + r"[^\\/\s]+"),
    ),
    # Git Bash, WSL and Cygwin write the drive as a folder, then the same folder for users.
    ("local-path", re.compile(r"/[A-Za-z]/(?i:users)/" + _NOT_A_PLACEHOLDER + r"[^/\s]+")),
    # Linux. Not after a word character, so the path part of a web address does not count.
    ("local-path", re.compile(r"(?<![\w.~-])" + _HOME + _NOT_A_PLACEHOLDER + r"[^/\s]+")),
    # macOS: the folder for users, in the case the system writes it (a route of an interface is
    # in lower case), not after a word character either, and not after a drive letter (that is the
    # Windows rule's); it is also where the system's data volume has it. The folder every user
    # shares is no one's.
    (
        "local-path",
        re.compile(r"(?:(?<![\w.~-])(?<![A-Za-z]:)|(?<=" + _DATA_VOLUME + r"))" + _USERS + _NOT_A_PLACEHOLDER + _NOT_SHARED + r"[^/\s]+"),
    ),
    # The home folder of a WSL distribution, as Windows shows it: a share of the host ``wsl$`` or
    # ``wsl.localhost``, the distribution, then the Linux folder for homes and a name.
    (
        "local-path",
        re.compile(
            r"[\\/]{2}(?i:wsl)(?:\$|\.(?i:localhost))[\\/][^\\/\s]+[\\/](?i:home)[\\/]"
            + _NOT_A_PLACEHOLDER
            + r"[^\\/\s]+"
        ),
    ),
    (
        "provenance",
        re.compile(
            "(?i:" + "eq" + "game" + "|disas" + "sembl" + r"|\." + "rdata" + r"\b)"
            r"|\bR" + "VA" + r"\b"
        ),
    ),
)

RULE_NAMES = tuple(dict.fromkeys(name for name, _pattern in RULES))

# Every rule needs at least one of these fragments, so a line with none of them (nearly every
# line) is cleared by a few plain substring tests, without running the patterns. The first group
# is tested on the line as it is, the second on its lower-case form.
_ADDRESS = "R" + "VA"
_LOWER_FRAGMENTS = ("users", "wsl", "eq" + "game", "disas" + "sembl", "." + "rdata")


def find(text: str) -> list[tuple[str, int, int]]:
    """Return ``(rule, start, end)`` for every match of a content rule in ``text``."""
    if (
        "[" not in text
        and ", '" not in text
        and "looted " not in text
        and "the group" not in text
        and "You told " not in text
        and "says out of" not in text
        and _HOME not in text
        and _ADDRESS not in text
    ):
        lowered = text.lower()
        for fragment in _LOWER_FRAGMENTS:
            if fragment in lowered:
                break
        else:
            return []
    found = []
    for rule, pattern in RULES:
        for match in pattern.finditer(text):
            found.append((rule, match.start(), match.end()))
    return found
