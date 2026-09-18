import hashlib
import json
import sys


def sha256_of_entry_without_hash(entry):
    temp = dict(entry)
    temp.pop("hash", None)
    raw = json.dumps(temp, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


def verify_export(path):
    with open(path, "r") as f:
        data = json.load(f)

    required_top = ["spec", "version", "exported_at", "hash_alg", "chain"]
    for key in required_top:
        if key not in data:
            print(f"EXPORT_VERIFY: FAIL (missing top-level key: {key})")
            return 2

    if data["hash_alg"] != "sha256":
        print("EXPORT_VERIFY: FAIL (unsupported hash_alg)")
        return 2

    prev = "GENESIS"
    for idx, entry in enumerate(data["chain"], start=1):
        expected = entry.get("hash")
        if not expected:
            print(f"EXPORT_VERIFY: FAIL (entry {idx} missing hash)")
            return 2

        recalculated = sha256_of_entry_without_hash(entry)
        if recalculated != expected:
            print(f"EXPORT_VERIFY: FAIL (entry {idx} hash mismatch)")
            return 2

        if entry.get("previous_hash") != prev:
            print(f"EXPORT_VERIFY: FAIL (entry {idx} previous_hash mismatch)")
            return 2

        prev = expected

    print("EXPORT_VERIFY: PASS")
    return 0


if __name__ == "__main__":
    path = "execution_log.json"
    if len(sys.argv) >= 2:
        path = sys.argv[1]
    raise SystemExit(verify_export(path))
