# Runbook: community reports and moderation

For the maintainers. It covers the reports that players make with the issue form "Seen in game": how to check one, how to add it to `rules/community-seen.json` or retract it, what to do when an attachment shows a name or a line of chat, and the repository settings and labels that go with it.

**The rule.** A report counts only when a maintainer has checked a screenshot of the item window. The file holds no free text and no link: for each report, the item key, the kind, the issue number, the day and the check, and nothing else. The wiki's own word and the state of the zones outweigh a report: an item that the wiki marks as deleted, as not existing or as removed, or whose every zone is unreleased or not part of EQL, stays hidden whatever players report (the report is noted in its reasons as outweighed). A screenshot shows that the item is in the game's data, not that anyone can get it. A report that was outweighed counts from the release in which the mark is taken off or the zone is opened, and the results diff report of that release lists the item as strict now because of a report. The address of an issue is built from the owner of the build and is never stored.

## Labels

GitHub applies the labels a form lists only if they exist in the repository, so create them once, before the repository is public:

| Label | Set by | Meaning |
|---|---|---|
| `seen-report` | the form "Seen in game" | a report of an item or a tier seen in game |
| `needs-check` | the form "Seen in game" | waits for a maintainer to check the screenshot |
| `screenshot-checked` | a maintainer | the screenshot was checked; set it in place of `needs-check`, and only then add the report |
| `retracted` | a maintainer | the report was taken back (set it with the retraction; in a privacy incident, not before the attachment is gone: see below) |
| `data` | the form "Wrong item data" | an item page shows a wrong stat, tier, source or class restriction |
| `site` | the form "Problem with a page" | a page says something wrong or unclear, or does not work |
| `rules` | the form "Rule correction" | a rule is wrong, or its evidence is out of date |

```
gh label create seen-report --repo <owner>/trioforge --color 0e8a16 --description "Report from the form Seen in game"
gh label create needs-check --repo <owner>/trioforge --color fbca04 --description "Waits for a maintainer to check the screenshot"
gh label create screenshot-checked --repo <owner>/trioforge --color 1d76db --description "A maintainer has checked the screenshot"
gh label create retracted --repo <owner>/trioforge --color b60205 --description "The report was taken back"
gh label create data --repo <owner>/trioforge --color 5319e7 --description "Wrong item data"
gh label create site --repo <owner>/trioforge --color c5def5 --description "Problem with a page"
gh label create rules --repo <owner>/trioforge --color d4c5f9 --description "Rule correction"
```

## Checking a report

1. Open the issue and look at the attachment first. If it shows a character name, a player name or any chat, stop and follow "A name or chat in an attachment" below before anything else.
2. The picture must be a crop of the item window and nothing else. The reporter ticked "My image shows only the item window: no names, no chat"; the tick is a promise, not a check.
3. The item name in the window is the item in the form. Names are not unique, so find the item in `derived/catalog.json` (one line for each item, which starts with its `key`, such as `w123`) and compare its slot and stats with the window. The key must be a wearable, an item that lists a slot of a place of a kit; `add` refuses any other.
4. The tier in the window is the "Tier seen" of the form. The kind is `seen` when the report is that the item exists in game, and `tier` when it is that a tier of it does.
5. The zone and how it was obtained are for the reader of the issue; nothing of them is stored.
6. If everything matches, replace the label `needs-check` with `screenshot-checked`. If not, ask the reporter in a comment for a better crop, without repeating anything the picture shows, and leave `needs-check`. Close an issue that stays without an answer for a week.

## Adding a report

On the PC, where the hooks that scan a commit run, in the repository:

```
PYTHONPATH=pipeline python -m trioforge.community add --key w123 --issue 5 --kind seen --screenshot-checked
```

From the root of the repository, like every command of the pipeline. On Windows PowerShell, set the path first with `$env:PYTHONPATH = "pipeline"` and start the command at `python`.

`--screenshot-checked` is required: it says that you have checked a screenshot of the item window, and the command refuses without it. It also refuses a key that is not a wearable of `derived/catalog.json`, and an item and an issue that the file has already. It prints the entry and the counts and nothing else, and a refusal is one line and writes nothing.

`git diff rules/community-seen.json` shows one added line. Commit the file by itself, with the issue number in the message and nothing from the picture, and close the issue with a short comment that says the report was accepted.

The report reaches the kits with the next release: the catalog is built again with the file, and the results diff report of the release lists under "Community evidence" every entry added, retracted or changed since the last release, each with its issue, and the items that a report makes strict or stops making strict. An item that stopped being strict is listed with why: "no longer strict, the report retracted", or "no longer strict, the report outweighed", with the marks of the wiki, the closed zones or the removal that outweigh it. The entries come from the list that `release.json` records, not from the reasons of the items, so a retraction that changes no item is listed too. The first release that records the list has nothing to compare it with: it lists the entries as "recorded in this release for the first time", and none of them is an addition or a retraction. Read that report before the release is tagged; an entry you did not expect is a reason to retract it first.

## Retracting a report

```
PYTHONPATH=pipeline python -m trioforge.community retract --issue 5 --reason withdrawn
```

moves every entry of the issue from `reports` to `retracted`, with the reason and the day. The reasons:

- `withdrawn`: the reporter took the report back.
- `wrong-item`: the picture, or the key, was another item or another tier.
- `rejected`: the report cannot stand (it was false, or the picture does not show what it should). The reason says nothing about the person who made it, and it stays in a public file for good, so choose it whenever the others do not fit.
- `duplicate`: another issue reports the same item; keep one of them.

A retraction is final for the issue: the command takes no report for an issue that has been retracted, of the same item or of another, so if the report was right after all, ask for a new issue. Commit the file and set the label `retracted`. The retraction appears in the results diff report of the next release, under "Community evidence", as retracted, and the items that rested on it fall back to the level the wiki gives them.

## A name or chat in an attachment

A picture that shows a character name, a player name or a line of chat is a privacy incident, whatever the report is worth. Make the content unreachable first, and add nothing public until it is gone. In this order:

1. Hide or delete the content at once. First copy the address of the issue and the address of the attachment to a note outside the repository (the addresses only: you need them for step 3). Then delete the comment, or edit the issue and remove the picture from its text, or delete the issue (the "Delete issue" link at the foot of its sidebar; only owners and admins have it, and it cannot be undone). If you hide a comment instead, the reason you choose is shown to everyone: choose "Off-topic", never "Abuse" or "Spam", which would label the reporter. Do not download, copy, quote or send the picture anywhere, and keep no note of what it showed.
2. Delete the old revisions, if you edited and did not delete. After an edit the old text, with the picture in it, stays in the edit history: click "edited" at the top of the issue or the comment, open each revision that has the picture and choose "Delete revision from history".
3. The attachment itself stays at its address even after the text is edited or the issue is deleted. Ask GitHub Support to purge it: write through the contact form of GitHub Support (support.github.com/contact), give the address of the issue and the address of the attachment, and ask for the attachment and its cached copies to be removed because it shows a person's name or chat. Keep the answer.
4. Until the attachment is gone, add nothing public about it: no label, no comment, no retraction, and no commit or message that names the issue or the reporter. A public mark beside a picture that can still be opened points at it. The attachment is gone when GitHub Support says so and its address shows nothing.
5. Then, if the report was added already, retract it: with `rejected`, or with `withdrawn` when the reporter will post a new crop, and set the label `retracted`.
6. Tell the reporter, without repeating what the picture showed, to post a new issue with a clean crop.

## Interaction limits

When a wave of false or spam reports, or of pictures with names, arrives, limit who can open issues. In the repository: Settings, "Moderation options", "Interaction limits". The choices:

- limit to existing users: accounts that have existed for more than a day;
- limit to prior contributors;
- limit to repository collaborators.

A limit lasts 24 hours, 3 days, 1 week, 1 month or 6 months and then lifts by itself; choose the narrowest that stops the wave, and lift it earlier with "Remove limits". Besides a limit: block the account, report it to GitHub, and lock an issue that turns into an argument. Do not turn issues off: the site's report links point at them.
