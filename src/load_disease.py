#!/usr/bin/env python3
"""傷病名マスターと移行対応テーブルを検証し、SQLiteへ取り込む。"""

from __future__ import annotations

import argparse
import sqlite3
import tempfile
from pathlib import Path

import pandas as pd


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"

# 2026-06-01取得スナップショットで再現した期待値。
KNOWN_PROFILE = {
    "disease_rows": 27_684,
    "disease_columns": 46,
    "migration_rows": 8_032,
    "migration_columns": 7,
    "icd10_second_code_rows": 1_482,
    "resolved_migration_rows": 6_037,
}


def col(number: int) -> str:
    """1始まりの項番をDataFrame列名へ変換する。"""
    return f"c{number}"


def read_master(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(
        path,
        header=None,
        dtype=str,
        encoding="cp932",
        keep_default_na=False,
    )
    frame.columns = [col(i + 1) for i in range(frame.shape[1])]
    return frame


def assert_equal(actual: int, expected: int, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label}: 実測 {actual} / 期待 {expected}")


def build_database(
    disease_source: Path,
    migration_source: Path,
    destination: Path,
    check_known_profile: bool,
) -> None:
    disease_frame = read_master(disease_source)
    migration_frame = read_master(migration_source)

    if disease_frame.shape[1] < 24:
        raise ValueError(
            f"傷病名マスターの列数が不足しています: {disease_frame.shape[1]}列"
        )
    if migration_frame.shape[1] < 7:
        raise ValueError(
            f"移行対応テーブルの列数が不足しています: {migration_frame.shape[1]}列"
        )

    if check_known_profile:
        assert_equal(
            len(disease_frame), KNOWN_PROFILE["disease_rows"], "傷病名マスター行数"
        )
        assert_equal(
            disease_frame.shape[1],
            KNOWN_PROFILE["disease_columns"],
            "傷病名マスター列数",
        )
        assert_equal(
            len(migration_frame),
            KNOWN_PROFILE["migration_rows"],
            "移行対応テーブル行数",
        )
        assert_equal(
            migration_frame.shape[1],
            KNOWN_PROFILE["migration_columns"],
            "移行対応テーブル列数",
        )

    diseases = [
        (
            row[col(3)],
            row[col(6)],
            row[col(16)] or None,
            row[col(17)] or None,
            1 if row[col(19)] == "01" else 0,
            1 if row[col(20)] == "1" else 0,
            row[col(22)] or None,
            row[col(23)] or None,
            row[col(24)] or None,
        )
        for _, row in disease_frame.iterrows()
    ]
    migrations = [
        (
            row[col(2)],
            row[col(3)],
            row[col(5)] or None,
            row[col(7)] or None,
        )
        for _, row in migration_frame.iterrows()
    ]

    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination_preexisted = destination.exists()

    if destination_preexisted:
        tmp_path = destination
    else:
        tmp_file = tempfile.NamedTemporaryFile(
            prefix=f".{destination.stem}-",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        )
        tmp_path = Path(tmp_file.name)
        tmp_file.close()

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(tmp_path)
        connection.execute("PRAGMA foreign_keys=ON")
        if destination_preexisted:
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            required = {"disease", "disease_migration"}
            if not required.issubset(table_names):
                raise ValueError(
                    "指定DBはmed-code-mapの現行スキーマではありません: "
                    f"不足={sorted(required - table_names)}"
                )
            existing_rows = connection.execute(
                "SELECT COUNT(*) FROM disease"
            ).fetchone()[0]
            if existing_rows:
                raise ValueError(
                    f"傷病名データが既に存在します: {existing_rows}件。重複投入を中止しました。"
                )
        else:
            connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

        with connection:
            connection.executemany(
                """
                INSERT INTO disease (
                    disease_code, name, icd10_code1, icd10_code2,
                    single_use_prohibited, excluded_from_claim,
                    listed_on, changed_on, abolished_on
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                diseases,
            )
            connection.executemany(
                """
                INSERT INTO disease_migration (
                    old_code, old_name, new_code, new_name
                ) VALUES (?,?,?,?)
                """,
                migrations,
            )

            icd2_count = connection.execute(
                "SELECT COUNT(*) FROM disease WHERE icd10_code2 IS NOT NULL"
            ).fetchone()[0]
            resolved_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM disease_migration AS m
                JOIN disease AS d ON d.disease_code = m.new_code
                """
            ).fetchone()[0]

            if check_known_profile:
                assert_equal(
                    icd2_count,
                    KNOWN_PROFILE["icd10_second_code_rows"],
                    "ICD-10コード2あり",
                )
                assert_equal(
                    resolved_count,
                    KNOWN_PROFILE["resolved_migration_rows"],
                    "現行傷病名へ解決できる移行",
                )

        connection.close()
        connection = None
        if not destination_preexisted:
            tmp_path.replace(destination)
    except Exception:
        if connection is not None:
            connection.close()
        if not destination_preexisted:
            tmp_path.unlink(missing_ok=True)
        raise

    print(f"disease:           {len(diseases):>6}")
    print(f"disease_migration: {len(migrations):>6}")
    print(f"ICD-10コード2あり: {icd2_count:>6}")
    print(f"移行先を解決:       {resolved_count:>6}")
    print(f"検証済みDBを作成しました: {destination}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("disease_master", type=Path, help="傷病名マスター（cp932）")
    parser.add_argument("migration_table", type=Path, help="移行対応テーブル（cp932）")
    parser.add_argument("output_db", type=Path, help="新規作成するSQLite DB")
    parser.add_argument(
        "--skip-known-profile-checks",
        action="store_true",
        help="2026-06-01版固有の件数検証を省略する",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    build_database(
        args.disease_master,
        args.migration_table,
        args.output_db,
        check_known_profile=not args.skip_known_profile_checks,
    )
