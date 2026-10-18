"""The sixteen class codes, in class-id order 1 to 16: the one list every module shares.

``WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM NEC WIZ MAG ENC BST BER`` is also the order of the class
columns in the client's spell file and the order of the class ids in its tables, so a module that
needs the id of a class takes ``CLASS_CODES.index(code) + 1``, and one that needs the code of an id
takes ``CLASS_CODES[id - 1]``. Import the constants from here; do not type the list again.
"""

__all__ = ["CLASS_CODES", "CLASS_NAMES"]

CLASS_NAMES = {
    "WAR": "Warrior",
    "CLR": "Cleric",
    "PAL": "Paladin",
    "RNG": "Ranger",
    "SHD": "Shadow Knight",
    "DRU": "Druid",
    "MNK": "Monk",
    "BRD": "Bard",
    "ROG": "Rogue",
    "SHM": "Shaman",
    "NEC": "Necromancer",
    "WIZ": "Wizard",
    "MAG": "Magician",
    "ENC": "Enchanter",
    "BST": "Beastlord",
    "BER": "Berserker",
}
CLASS_CODES = tuple(CLASS_NAMES)
