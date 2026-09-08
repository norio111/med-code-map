from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import closing


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import load_disease  # noqa: E402
import load_master  # noqa: E402


def write_cp932_row(path: Path, column_count: int, values: dict[int, str]) -> None:
    row = [""] * column_count
    for one_based_column, value in values.items():
        row[one_based_column - 1] = value
    with path.open("w", encoding="cp932", newline="") as stream:
        csv.writer(stream).writerow(row)


def write_cp932_rows(
    path: Path, column_count: int, rows: list[dict[int, str]]
) -> None:
    with path.open("w", encoding="cp932", newline="") as stream:
        writer = csv.writer(stream)
        for values in rows:
            row = [""] * column_count
            for one_based_column, value in values.items():
                row[one_based_column - 1] = value
            writer.writerow(row)


class LoaderSmokeTest(unittest.TestCase):
    def test_two_loaders_build_one_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            medical = tmp_path / "s_sample.csv"
            disease = tmp_path / "b_sample.txt"
            migration = tmp_path / "ikou_sample.txt"
            database = tmp_path / "sample.db"

            write_cp932_row(
                medical,
                150,
                {
                    2: "S",
                    3: "180000001",
                    5: "架空リハビリテーション料",
                    8: "28",
                    10: "単位",
                    11: "3",
                    12: "245.00",
                    30: "1",
                    31: "1",
                    32: "9",
                    33: "1",
                    34: "245.00",
                    35: "1",
                    68: "1",
                    72: "732",
                    85: "H",
                    87: "20260501",
                    88: "99999999",
                    90: "7",
                    91: "1",
                    92: "001",
                    94: "1",
                    113: "架空リハビリテーション料",
                    117: "H001",
                },
            )
            write_cp932_row(
                disease,
                46,
                {
                    2: "B",
                    3: "1234567",
                    6: "架空傷病名",
                    16: "A000",
                    19: "00",
                    20: "0",
                    22: "20260601",
                    23: "20260602",
                    24: "99999999",
                },
            )
            write_cp932_rows(
                migration,
                7,
                [
                    {
                        2: "7654321",
                        3: "旧架空傷病名",
                        5: "1234567",
                        7: "架空傷病名",
                    },
                    {2: "7654322", 3: "移行先なし架空傷病名"},
                ],
            )

            master_args = argparse.Namespace(
                master=medical,
                output_db=database,
                all=False,
                revision_id="TEST",
                revision_label="架空改定",
                effective_from="2026-01-01",
                effective_to=None,
                expected_total_rows=1,
                expected_selected_rows=1,
            )
            load_master.build_database(master_args)
            load_disease.build_database(
                disease, migration, database, check_known_profile=False
            )

            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM code_item").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM disease").fetchone()[0],
                    1,
                )
                dates = connection.execute(
                    "SELECT listed_on, changed_on, abolished_on FROM disease"
                ).fetchone()
                self.assertEqual(dates, ("20260601", "20260602", "99999999"))
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM disease_migration WHERE new_code='1234567'"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM disease_migration WHERE new_code IS NULL"
                    ).fetchone()[0],
                    1,
                )
                connection.executescript(
                    (ROOT / "sql" / "queries.sql").read_text(encoding="utf-8")
                )


if __name__ == "__main__":
    unittest.main()
