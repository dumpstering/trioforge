"""The result files are the same bytes whatever the hash seed of the process that writes them.

Python hashes its strings with a seed it picks anew for every process, and a set of strings hands out its members in an order that
depends on it. Anything a set feeds into a result file (the creation-legal races, say) must be put in order first, or the same inputs
would write another file on another run. A test in one process cannot see that, since its seed is fixed: these run the flip notes and the
defaults file in fresh processes, each with a seed of its own, and compare what they write. Every name and number here is invented.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from trioforge import precompute as pc

PIPELINE = Path(pc.__file__).resolve().parents[2]  # what a fresh process needs on its path
SEEDS = ("0", "1", "2", "17", "4242")

#: The part of a run that writes the flip notes: the races of a layout (the last two cannot be created), the value of each race in the
#: default view (three values among fifteen races: ties everywhere), and eight rule variants that each put a few races on top with the
#: same value, so that the winner of a variant is decided among tied races by the order of the display and nothing else. It prints the
#: bytes of ``defaults.json`` those make, and, as a control, a set of the same races joined in the order the process hands it out.
SCRIPT = r'''
import sys

from trioforge.data.races import RACE_NAMES
from trioforge.precompute import seals, shards


def render_defaults() -> str:
    codes = list(RACE_NAMES)
    races = [(code, n < len(codes) - 2) for n, code in enumerate(codes)]
    layout = shards.Layout(
        trio="pal-mnk-ber", classes=("PAL", "MNK", "BER"), level=50, data_release="data-2030-01-02", game_patch="2026-10-13",
        rules_version="2026-10-13", solver={}, build_options={}, assumptions={}, races=races, roles=["tank"],
        setups={"tank": ["dw"]}, tiers=[4], caps={}, pools={}, default_evidence="strict", expected={}, item_rows={},
    )
    order = [code for code, _ in races]
    base = {code: 100.0 + (n % 3) for n, code in enumerate(order)}
    default = shards.default_race(base, layout.legal_races(), order, 1)["race"]
    rules = ["race.iksar_ac_placement", "monk.bonus_placement", "mana.wis_bands", "tier.weapon_damage_pct", "monk.weight_curve", "some.rule"]
    variants = [
        seals.Variant(f"Variant {k}", rules[k % len(rules)], f"B{k}" if k % 3 else None, {code: 150.0 for n, code in enumerate(order) if (n + k) % 4 == 0})
        for k in range(8)
    ]
    notes = seals.flip_notes(variants, base, default, layout.legal_races(), order, 1)
    per_race = {code: (base[code], "dw") for code in order}
    doc = shards.defaults_doc(
        layout, view={"role": "tank", "tier": 4, "evidence": "strict", "buffs": "own"}, per_race=per_race, strict_empty=False,
        robustness="done", flip_notes=notes, close_pct=1,
    )
    return shards.render(doc)


def control() -> str:
    return " ".join(set(RACE_NAMES))


if __name__ == "__main__":
    sys.stdout.write(render_defaults() + "\n--control--\n" + control() + "\n")
'''


def in_a_fresh_process(seed: str) -> tuple[str, str]:
    """What a process started with this hash seed writes: the defaults file, and the control."""
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(PIPELINE), "PYTHONUTF8": "1"}
    done = subprocess.run([sys.executable, "-c", SCRIPT], env=env, capture_output=True, text=True, encoding="utf-8", check=False, timeout=300)
    assert done.returncode == 0, done.stderr
    written, _, control = done.stdout.partition("\n--control--\n")
    return written, control.strip()


def test_the_flip_notes_and_the_defaults_file_are_the_same_bytes_in_processes_with_other_hash_seeds():
    with ThreadPoolExecutor(max_workers=len(SEEDS)) as pool:
        outputs = dict(zip(SEEDS, pool.map(in_a_fresh_process, SEEDS)))
    written = {seed: output[0] for seed, output in outputs.items()}
    assert len(set(written.values())) == 1, {seed: text[-300:] for seed, text in written.items()}
    doc = json.loads(written[SEEDS[0]])
    assert len(doc["flip_notes"]) >= 3 and len(doc["races"]) == 16  # there is something to compare
    # the control: the seeds do change the order a set of the same races is handed out in, so a set that fed the file would have shown
    assert len({control for _, control in outputs.values()}) > 1, "the seeds did not change the order of a set of strings"


def test_the_process_that_runs_the_tests_writes_the_same_bytes_as_a_fresh_one_with_a_seed_of_its_own():
    namespace: dict[str, object] = {"__name__": "script"}
    exec(compile(SCRIPT, "<the flip notes script>", "exec"), namespace)  # (the script is this file's own, not input)
    here = namespace["render_defaults"]()  # type: ignore[operator]
    assert here == in_a_fresh_process("12345")[0]
