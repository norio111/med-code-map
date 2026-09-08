#!/usr/bin/env python3
"""ローカル入力ファイルのサイズとSHA-256をCSVへ記録する。"""

from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(source_dir: Path, output: Path) -> None:
    files = sorted(path for path in source_dir.rglob("*") if path.is_file())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["relative_path", "bytes", "sha256", "recorded_at_utc"],
        )
        writer.writeheader()
        recorded_at = datetime.now(timezone.utc).isoformat()
        for path in files:
            writer.writerow(
                {
                    "relative_path": path.relative_to(source_dir).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                    "recorded_at_utc": recorded_at,
                }
            )
    print(f"{len(files)}ファイルを記録しました: {output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path("source-manifest.csv"))
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(args.source_dir, args.output)

