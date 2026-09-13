"""
Dataset Curation - MinHash Near-Duplicate Detection
===================================================

Find near-duplicate rows in a dataset without any LLM calls. Each row is
reduced to a set of word 3-gram shingles, each shingle set is compressed to a
64-slot MinHash signature, and rows whose estimated Jaccard similarity is
>= 0.7 are clustered with union-find. The first row of each cluster is kept.

Why MinHash works: a keyed hash function imposes a pseudo-random ordering on
the universe of shingles. For two shingle sets A and B, the shingle with the
minimum hash over A union B is uniformly random over that union, so A and B
share the same minimum exactly when that shingle lies in A intersect B -
which happens with probability |A n B| / |A u B|, the Jaccard similarity.
Averaging over 64 independent orderings estimates that probability with
standard error sqrt(J * (1 - J) / 64), about +/- 0.06 near J = 0.7.

Everything here is deterministic: blake2b with fixed keys, no randomness.

Honest limitation: word 3-gram shingles catch verbatim copies, light edits,
and close paraphrases. Heavier rewording that preserves meaning but shares
few 3-grams falls below the threshold - that regime needs embedding-based
dedup, not MinHash.
"""

import hashlib
from itertools import combinations

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
NUM_HASHES = 64
SHINGLE_SIZE = 3
SIMILARITY_THRESHOLD = 0.7


# ---------------------------------------------------------------------------
# Fixture: 10 rows, 2 planted near-duplicate clusters
# ---------------------------------------------------------------------------
# Cluster A (light-edit-level): rows 0, 3, 7 - one-word substitutions.
# Cluster B (paraphrase-level): rows 2, 6 - word-choice changes in a longer
# instruction. All other rows are unique.
ROWS = [
    {
        "id": "row-00",
        "text": (
            "Write a Python function that checks whether a given string is a "
            "palindrome, ignoring case and punctuation, and include a short "
            "docstring plus two example calls demonstrating typical usage."
        ),
    },
    {
        "id": "row-01",
        "text": (
            "Explain how a hash table achieves average constant time lookups "
            "and what happens when too many keys collide."
        ),
    },
    {
        "id": "row-02",
        "text": (
            "Draft a professional email to a customer explaining that their "
            "order has been delayed by two weeks due to a supplier issue, "
            "apologize for the inconvenience, offer a ten percent discount on "
            "their next purchase, and reassure them that the revised delivery "
            "date is now confirmed."
        ),
    },
    {
        "id": "row-03",
        "text": (
            "Write a Python function that checks whether a given string is a "
            "palindrome, ignoring case and punctuation, and include a short "
            "docstring plus three example calls demonstrating typical usage."
        ),
    },
    {
        "id": "row-04",
        "text": (
            "Translate the sentence 'the weather is beautiful today' into "
            "French and German."
        ),
    },
    {
        "id": "row-05",
        "text": (
            "Write a SQL query that returns the top five customers by total "
            "order value in the last ninety days."
        ),
    },
    {
        "id": "row-06",
        "text": (
            "Draft a professional email to a customer explaining that their "
            "order has been postponed by two weeks due to a supplier issue, "
            "apologize for the trouble, offer a ten percent discount on "
            "their next purchase, and reassure them that the revised delivery "
            "date is now confirmed."
        ),
    },
    {
        "id": "row-07",
        "text": (
            "Write a Python function that checks whether a given string is a "
            "palindrome, ignoring case and punctuation, and include a concise "
            "docstring plus two example calls demonstrating typical usage."
        ),
    },
    {
        "id": "row-08",
        "text": (
            "Describe the main differences between TCP and UDP and when you "
            "would choose each protocol."
        ),
    },
    {
        "id": "row-09",
        "text": (
            "Give a step-by-step derivation of the quadratic formula starting "
            "from a general quadratic equation."
        ),
    },
]


# ---------------------------------------------------------------------------
# Create MinHash Signatures
# ---------------------------------------------------------------------------
def shingles(text: str) -> set:
    tokens = text.lower().split()
    if len(tokens) < SHINGLE_SIZE:
        # Texts shorter than one shingle fall back to a single whole-text
        # shingle so minhash_signature never sees an empty set.
        return {" ".join(tokens)}
    return {
        " ".join(tokens[i : i + SHINGLE_SIZE])
        for i in range(len(tokens) - SHINGLE_SIZE + 1)
    }


def hash_shingle(shingle: str, key: bytes) -> int:
    digest = hashlib.blake2b(shingle.encode(), key=key, digest_size=8).digest()
    return int.from_bytes(digest, "big")


def minhash_signature(shingle_set: set) -> list:
    # Slot i takes the minimum of hash function i (blake2b keyed with a
    # distinct key) over all shingles: one sample of "does the union's
    # minimum land in the intersection" per slot.
    return [
        min(hash_shingle(s, f"perm-{i:02d}".encode()) for s in shingle_set)
        for i in range(NUM_HASHES)
    ]


def estimated_jaccard(sig_a: list, sig_b: list) -> float:
    return sum(a == b for a, b in zip(sig_a, sig_b)) / NUM_HASHES


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------
def find(parent: dict, x: int) -> int:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def union(parent: dict, a: int, b: int) -> None:
    root_a, root_b = find(parent, a), find(parent, b)
    if root_a != root_b:
        parent[max(root_a, root_b)] = min(root_a, root_b)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    signatures = [minhash_signature(shingles(row["text"])) for row in ROWS]

    parent = {i: i for i in range(len(ROWS))}
    pair_sims = {}
    for i, j in combinations(range(len(ROWS)), 2):
        sim = estimated_jaccard(signatures[i], signatures[j])
        pair_sims[(i, j)] = sim
        if sim >= SIMILARITY_THRESHOLD:
            union(parent, i, j)

    clusters = {}
    for i in range(len(ROWS)):
        clusters.setdefault(find(parent, i), []).append(i)
    dup_clusters = [members for members in clusters.values() if len(members) > 1]

    print(f"pairs at threshold >= {SIMILARITY_THRESHOLD}:")
    for (i, j), sim in sorted(pair_sims.items()):
        if sim >= SIMILARITY_THRESHOLD:
            print(f"  {ROWS[i]['id']} ~ {ROWS[j]['id']}  est_jaccard={sim:.3f}")
    print()

    dropped_ids = []
    for n, members in enumerate(dup_clusters, start=1):
        ids = [ROWS[i]["id"] for i in members]
        print(f"cluster {n}: {ids}")
        for i, j in combinations(members, 2):
            sim = pair_sims[(i, j)]
            print(f"  est_jaccard({ROWS[i]['id']}, {ROWS[j]['id']}) = {sim:.3f}")
        keep_id, drop_ids = ids[0], ids[1:]
        dropped_ids.extend(drop_ids)
        print(f"  keep {keep_id}, drop {', '.join(drop_ids)}")
        print(f"  text: {ROWS[members[0]]['text'][:70]}...")
        print()

    kept = len(ROWS) - len(dropped_ids)
    print(
        f"kept {kept} of {len(ROWS)} rows: dropped {len(dropped_ids)} "
        f"near-duplicates across {len(dup_clusters)} clusters"
    )
