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
                append=False,
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


class RevisionDiffTest(unittest.TestCase):
    """同じコードの2改定を1DBへ入れ、差分クエリが変化を拾えることを確かめる。"""

    def _row(self, code: str, point: str, name: str) -> dict[int, str]:
        return {
            2: "S",
            3: code,
            5: name,
            8: "28",
            10: "単位",
            11: "3",
            12: point,
            30: "1",
            31: "1",
            32: "9",
            33: "1",
            34: point,
            35: "1",
            68: "1",
            72: "732",
            85: "H",
            87: "20260601",
            88: "99999999",
            90: "7",
            91: "1",
            92: "001",
            94: "1",
            113: name,
            117: "H001",
        }

    def _args(self, master, database, revision_id, label, frm, to, append, rows):
        return argparse.Namespace(
            master=master,
            output_db=database,
            all=False,
            revision_id=revision_id,
            revision_label=label,
            effective_from=frm,
            effective_to=to,
            expected_total_rows=rows,
            expected_selected_rows=rows,
            append=append,
        )

    def test_two_revisions_coexist_and_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            old_master = tmp_path / "s_old.csv"
            new_master = tmp_path / "s_new.csv"
            database = tmp_path / "two.db"

            # 旧版: 据え置きコードと、新版で消えるコード
            write_cp932_rows(old_master, 150, [
                self._row("180000001", "245.00", "架空リハ料"),
                self._row("180000002", "100.00", "架空廃止予定リハ料"),
            ])
            # 新版: 点数が変わったコードと、新設コード
            write_cp932_rows(new_master, 150, [
                self._row("180000001", "255.00", "架空リハ料"),
                self._row("180000003", "300.00", "架空新設リハ料"),
            ])

            load_master.build_database(self._args(
                old_master, database, "OLD", "架空旧改定",
                "2024-06-01", "2026-05-31", False, 2))
            load_master.build_database(self._args(
                new_master, database, "NEW", "架空新改定",
                "2026-06-01", None, True, 2))

            with closing(sqlite3.connect(database)) as connection:
                connection.execute("PRAGMA foreign_keys=ON")
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM revision").fetchone()[0],
                    2,
                )
                # 同じコードが2改定ぶん、別の点数で共存している
                points = connection.execute(
                    "SELECT revision_id, point FROM code_item"
                    " WHERE code='180000001' ORDER BY revision_id"
                ).fetchall()
                self.assertEqual(points, [("NEW", 255.0), ("OLD", 245.0)])

                diff = (ROOT / "sql" / "revision-diff.sql").read_text(encoding="utf-8")
                params = {"old": "OLD", "new": "NEW"}
                results = []
                for statement in diff.split(";"):
                    body = "\n".join(
                        line for line in statement.splitlines()
                        if line.strip() and not line.strip().startswith("--")
                    )
                    if not body.strip():
                        continue
                    results.append(
                        connection.execute(statement, params).fetchall()
                    )

                added, removed, repriced = results[1], results[2], results[3]
                self.assertEqual([r[0] for r in added], ["180000003"])
                self.assertEqual([r[0] for r in removed], ["180000002"])
                self.assertEqual(repriced[0][0], "180000001")
                self.assertEqual(repriced[0][4], 10.0)

    def test_same_revision_twice_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            master = tmp_path / "s.csv"
            database = tmp_path / "one.db"
            write_cp932_rows(master, 150, [self._row("180000001", "245.00", "架空リハ料")])

            load_master.build_database(self._args(
                master, database, "SAME", "架空改定", "2026-06-01", None, False, 1))
            before = database.read_bytes()
            with self.assertRaises(ValueError):
                load_master.build_database(self._args(
                    master, database, "SAME", "架空改定", "2026-06-01", None, True, 1))
            # 失敗しても既存DBは元のまま
            self.assertEqual(database.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
