"""Apply recorded visual decisions only to matching pinned crop hashes."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    decisions = {r["id"]: r for r in json.loads(args.review.read_text(encoding="utf-8"))["decisions"]}
    rows = [json.loads(line) for line in args.manifest.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        decision = decisions[row["id"]]
        for key in ["crop_sha256", "document_sha256", "source_member", "bbox"]:
            if row[key] != decision[key]:
                raise ValueError("Review belongs to a different crop")
        row["approved"], row["review"] = decision["approved"], decision["review"]
    args.manifest.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    print({s: sum(r["approved"] and r["split"] == s for r in rows) for s in ["train", "validation", "test"]})


if __name__ == "__main__":
    main()
