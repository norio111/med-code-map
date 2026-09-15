"""疑義解釈（gigi_kaishaku）取込のsmokeテスト。

既存の tests/test_smoke.py と同じ方針:
  ・架空の最小データでロジックを検証するテストは常に実行する
  ・data/private/ に実データ(xlsm)がある場合だけ、全件取込の回帰を実行する
  ・実データが無い環境（CI等）ではそのテストだけ skip する

実行:
    py -m unittest discover -s tests -v
    py -m unittest tests.test_gigi_smoke -v
"""

import glob
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import load_gigi  # noqa: E402

SCHEMA_PATH = ROOT / "sql" / "schema_gigi.sql"
PRIVATE_DIR = ROOT / "data" / "private"

# 既知版(2026-09-15時点Ver.1.1.4)がある前提の回帰テスト用。
# 環境によってVerが進んでいることもあるので、ファイル名ではなく
# glob でその時点にある Ver*.xlsm を拾う。
_REAL_XLSM = sorted(glob.glob(str(PRIVATE_DIR / "Ver.*.xlsm")))
_HAVE_REAL_DATA = bool(_REAL_XLSM) and SCHEMA_PATH.exists()


def _make_fixture_xlsm(path):
    """最小の架空データで管理用シートを再現する。

    列構成は load_gigi.COL_* の定義と一致させること。
    2行だけ: 通常の医科1件、療養費系(改定紐付なしになるはず)1件。
    """
    import openpyxl
    from datetime import datetime

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "管理用"
    header = ["No.", "改定年度", "発出年月日", "件名", "分類",
              "問番号", "質問", "回答", "廃止済み疑義解釈"]
    ws.append(header)
    ws.append([
        1, "令和8年度診療報酬改定", datetime(2026, 4, 1),
        "疑義解釈資料の送付について（その２)", "訪看",
        1, "テスト用の質問です。", "テスト用の回答です。", None,
    ])
    ws.append([
        2, None, datetime(2026, 4, 2),
        "柔道整復施術療養費に関する疑義解釈の送付について", "柔整",
        "１．テスト", "柔整のテスト質問。", "柔整のテスト回答。", "廃止済み",
    ])

    cover = wb.create_sheet("表紙")
    cover["A1"] = "Ver0.0.1. テスト用ダミーデータを追加"

    wb.save(path)


class GigiFixtureSmokeTest(unittest.TestCase):
    """架空の最小データで、パース・投入・検証ロジックを確認する。
    実データの有無に関わらず常に実行する。
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.xlsm = os.path.join(self.tmpdir.name, "Ver.0.0.1.xlsm")
        self.db = os.path.join(self.tmpdir.name, "fixture.db")
        _make_fixture_xlsm(self.xlsm)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_two_fixture_rows_load_and_normalize(self):
        conn, rows, skipped, latest = load_gigi.load(
            self.db, str(SCHEMA_PATH), self.xlsm, "Ver.0.0.1")
        try:
            self.assertEqual(len(rows), 2)
            self.assertEqual(len(skipped), 0)

            cur = conn.cursor()
            cur.execute(
                "SELECT revision_code, bunrui, sono_no, toi_no_raw, "
                "toi_no_num, is_haishi FROM gigi_kaishaku "
                "WHERE source_ver=? ORDER BY src_no", ("Ver.0.0.1",))
            got = cur.fetchall()

            # 1件目: 通常の改定紐付き。全角「２」が半角2に正規化されること
            self.assertEqual(got[0], ("R08", "訪看", 2, "1", 1, 0))
            # 2件目: 療養費系は revision_code が NULL になること（仕様）
            #        問番号は数値化できない文字列のまま保持されること
            #        廃止済みフラグが 0/1 に正規化されること
            self.assertIsNone(got[1][0])
            self.assertEqual(got[1][1], "柔整")
            self.assertEqual(got[1][3], "１．テスト")
            self.assertIsNone(got[1][4])
            self.assertEqual(got[1][5], 1)
        finally:
            conn.close()

    def test_expected_total_rows_mismatch_is_reported(self):
        conn, rows, skipped, latest = load_gigi.load(
            self.db, str(SCHEMA_PATH), self.xlsm, "Ver.0.0.1")
        conn.close()

        class Args:
            expected_total_rows = 99
            skip_known_profile_checks = True

        failures = load_gigi.validate(rows, Args())
        self.assertEqual(len(failures), 1)
        self.assertIn("総件数", failures[0])

    def test_expected_total_rows_match_is_clean(self):
        conn, rows, skipped, latest = load_gigi.load(
            self.db, str(SCHEMA_PATH), self.xlsm, "Ver.0.0.1")
        conn.close()

        class Args:
            expected_total_rows = 2
            skip_known_profile_checks = True

        failures = load_gigi.validate(rows, Args())
        self.assertEqual(failures, [])

    def test_reimport_same_ver_is_idempotent(self):
        """同一 source_ver の再取込は、行を重複させず差し替えること。"""
        conn1, rows1, _, _ = load_gigi.load(
            self.db, str(SCHEMA_PATH), self.xlsm, "Ver.0.0.1")
        conn1.close()
        conn2, rows2, _, _ = load_gigi.load(
            self.db, str(SCHEMA_PATH), self.xlsm, "Ver.0.0.1")
        try:
            n = conn2.execute(
                "SELECT COUNT(*) FROM gigi_kaishaku WHERE source_ver=?",
                ("Ver.0.0.1",)).fetchone()[0]
            self.assertEqual(n, 2)  # 4件になっていない = 重複していない
        finally:
            conn2.close()


@unittest.skipUnless(
    _HAVE_REAL_DATA,
    "data/private/ に Ver.*.xlsm が無いため実データ回帰はskip")
class GigiRealDataRegressionTest(unittest.TestCase):
    """既知版の実データで、期待件数どおりに投入できることを確認する。

    Ver番号が進んでいる場合、既知プロファイル(load_gigi.KNOWN_PROFILE)と
    一致しなくなる可能性がある。そのときはこのテストが失敗で教えてくれる
    ので、KNOWN_PROFILE を新しい版の値へ更新すること。
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmpdir.name, "real.db")
        self.xlsm = _REAL_XLSM[-1]  # 最新のVerを使う

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_full_import_matches_known_profile(self):
        conn, rows, skipped, latest = load_gigi.load(
            self.db, str(SCHEMA_PATH), self.xlsm,
            os.path.splitext(os.path.basename(self.xlsm))[0])
        try:
            class Args:
                expected_total_rows = None
                skip_known_profile_checks = False

            failures = load_gigi.validate(rows, Args())
            self.assertEqual(
                failures, [],
                "既知プロファイルと不一致。Verが進んで内容が変わった場合は "
                "load_gigi.KNOWN_PROFILE を更新すること: " + str(failures))

            cur = conn.cursor()
            n = cur.execute(
                "SELECT COUNT(*) FROM gigi_kaishaku").fetchone()[0]
            self.assertGreater(n, 0)

            # FTSが引けることも確認しておく
            hit = cur.execute(
                "SELECT COUNT(*) FROM gigi_fts WHERE gigi_fts MATCH ?",
                ("訪問看護",)).fetchone()[0]
            self.assertGreater(hit, 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
