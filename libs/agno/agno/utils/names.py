"""Human-readable ID generation, inspired by Docker container names.

Generates IDs in the format ``adjective-name-hexsuffix``, where the
adjective and name are chosen deterministically from a UUID4, and the
hex suffix is derived from the same UUID to guarantee uniqueness.
"""

from uuid import uuid4

# 64 positive, professional adjectives.
# All entries must be single lowercase alphabetic words (no hyphens).
_ADJECTIVES: list[str] = [
    "agile",
    "bold",
    "brave",
    "bright",
    "calm",
    "civic",
    "clean",
    "clear",
    "cool",
    "crisp",
    "deft",
    "eager",
    "epic",
    "fair",
    "fast",
    "firm",
    "fleet",
    "focal",
    "frank",
    "fresh",
    "grand",
    "great",
    "hardy",
    "keen",
    "kind",
    "lively",
    "lucid",
    "major",
    "merry",
    "mild",
    "modest",
    "neat",
    "noble",
    "novel",
    "open",
    "plain",
    "plucky",
    "prime",
    "proud",
    "pure",
    "quick",
    "quiet",
    "rapid",
    "ready",
    "rich",
    "robust",
    "sharp",
    "sleek",
    "smart",
    "solid",
    "sound",
    "steady",
    "stoic",
    "swift",
    "tidy",
    "tough",
    "true",
    "unique",
    "vivid",
    "warm",
    "wise",
    "witty",
    "zesty",
    "zippy",
]

# 64 notable scientists and engineers.
# All entries must be single lowercase alphabetic words (no hyphens).
_NAMES: list[str] = [
    "archimedes",
    "babbage",
    "bell",
    "bohr",
    "boltzmann",
    "boole",
    "brahe",
    "carson",
    "celsius",
    "curie",
    "darwin",
    "dijkstra",
    "dirac",
    "einstein",
    "euler",
    "faraday",
    "fermi",
    "feynman",
    "franklin",
    "galileo",
    "gauss",
    "goodall",
    "hawking",
    "heisenberg",
    "hopper",
    "hubble",
    "hypatia",
    "johnson",
    "kepler",
    "knuth",
    "lamarr",
    "leibniz",
    "lovelace",
    "maxwell",
    "mendel",
    "meitner",
    "morse",
    "nash",
    "newton",
    "noether",
    "ohm",
    "pascal",
    "pasteur",
    "pauling",
    "planck",
    "ptolemy",
    "ramanujan",
    "ride",
    "ritchie",
    "rosalind",
    "rutherford",
    "sagan",
    "schrodinger",
    "shannon",
    "tesla",
    "thompson",
    "turing",
    "volta",
    "watt",
    "wozniak",
    "wright",
    "wu",
    "yang",
    "zuse",
]


def generate_human_readable_id() -> str:
    """Generate a human-readable ID backed by UUID4 uniqueness.

    Format: ``adjective-name-hexsuffix``  (e.g. ``elegant-euler-3f2a1b4c``)

    The adjective and name are selected deterministically from the UUID's
    integer value, and an 8-character hex suffix derived from the same UUID
    ensures collision resistance equivalent to UUID4.

    Returns:
        str: A human-readable, unique identifier.
    """
    uid = uuid4()
    uid_int = uid.int

    adjective = _ADJECTIVES[uid_int % len(_ADJECTIVES)]
    name = _NAMES[(uid_int // len(_ADJECTIVES)) % len(_NAMES)]
    hex_suffix = uid.hex[:8]

    return f"{adjective}-{name}-{hex_suffix}"
