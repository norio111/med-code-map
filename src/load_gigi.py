#!/usr/bin/env python3
"""
疑義解釈検索ツール（厚労省 xlsm）→ SQLite 取込

med-code-map の既存ローダ（load_master.py / load_disease.py）と同じ方針で、
期待件数を渡してDBの整合性を検証する。不一致なら投入を確定させず中止する。

使い方:
    py src/load_gigi.py data/private/Ver.1.1.4.xlsm work/med-code-map.db `
      --expected-total-rows 7629 `
      --expected-bunrui 訪看=198 `
      --expected-no-revision-rows 694

既知版（2026-09-15 時点、その12まで反映のVer.1.1.4）の期待値は上記。
未知版で試す場合は --skip-known-profile-checks を付ける。
このオプションは列の意味を保証するものではない。

設計メモ:
  ・読むのは「管理用」シートのみ。「検索」シートはマクロ実行後の表示用で空。
  ・同一 source_ver の再取込は冪等（既存行を削除してから入れ直す）。
  ・版が変わったら別 source_ver として追加投入する。過去版は消さない
    （どの版の時点で何が載っていたかを後から追えるようにするため）。
  ・load_master.py の --append は「同一改定IDが既にあれば中止」だが、
    gigiは同一ファイルの再取込（Ver据え置きでの再実行）を許す必要が
    あるため、削除→再投入の冪等方式にしている。版を跨いだ二重投入は
    source_ver が異なる限り両方残る。
"""

import argparse
import hashlib
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import openpyxl

SHEET = "管理用"
COVER = "表紙"

# 管理用シートの列位置（1始まり）
COL_NO, COL_KAITEI, COL_DATE, COL_TITLE = 1, 2, 3, 4
COL_BUNRUI, COL_TOI, COL_Q, COL_A, COL_HAISHI = 5, 6, 7, 8, 9

JST = timezone(timedelta(hours=9))

SERIES_PATTERNS = [
    ("jusei", "柔道整復"),
    ("ahaki", "はり"),
    ("soug", "治療用装具"),
    ("beia", "ベースアップ評価料"),
]

# 2026-09-15 時点、Ver.1.1.4（その12まで反映）での既知プロファイル。
# --skip-known-profile-checks を付けない限り、ここと突き合わせる。
KNOWN_PROFILE = {
    "total_rows": 7629,
    "bunrui": {"訪看": 198},
    "no_revision_rows": 694,
}


def now_iso():
    return datetime.now(JST).isoformat(timespec="seconds")


def to_date(v):
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, (int, float)):
        return (datetime(1899, 12, 30) + timedelta(days=int(v))).date().isoformat()
    return None


def to_revision_code(label):
    """'令和8年度診療報酬改定' -> 'R08' / 療養費系(柔整等)は None。"""
    if not label:
        return None
    s = unicodedata.normalize("NFKC", str(label))
    m = re.search(r"(平成|令和)\s*(元|\d+)\s*年度", s)
    if not m:
        return None
    era = "H" if m.group(1) == "平成" else "R"
    num = 1 if m.group(2) == "元" else int(m.group(2))
    return f"{era}{num:02d}"


def parse_title(title):
    if not title:
        return None, None
    s = unicodedata.normalize("NFKC", str(title))
    series = "other"
    for name, kw in SERIES_PATTERNS:
        if kw in s:
            series = name
            break
    else:
        if "疑義解釈資料の送付について" in s:
            series = "main"
    m = re.search(r"その\s*(\d+)", s)
    return series, (int(m.group(1)) if m else None)


def parse_toi(v):
    if v is None:
        return None, None
    raw = str(v).strip()
    if isinstance(v, int):
        return raw, v
    s = unicodedata.normalize("NFKC", raw)
    return raw, int(s) if re.fullmatch(r"\d+", s) else None


def read_cover_note(wb):
    if COVER not in wb.sheetnames:
        return None
    ws = wb[COVER]
    notes = []
    for r in range(1, ws.max_row + 1):
        for c in range(1, 5):
            v = ws.cell(row=r, column=c).value
            if isinstance(v, str) and re.match(r"\s*Ver\s*[\d.]+", v):
                notes.append(v.strip())
    return " / ".join(notes) if notes else None


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_rows(xlsm_path):
    wb = openpyxl.load_workbook(xlsm_path, data_only=True, keep_vba=False)
    if SHEET not in wb.sheetnames:
        raise SystemExit(f"'{SHEET}' シートが見つからへん: {wb.sheetnames}")
    ws = wb[SHEET]

    rows, skipped = [], []
    for r in range(2, ws.max_row + 1):
        src_no = ws.cell(row=r, column=COL_NO).value
        if src_no is None:
            continue

        q = ws.cell(row=r, column=COL_Q).value
        if not q:
            skipped.append((r, "質問が空"))
            continue

        title = ws.cell(row=r, column=COL_TITLE).value
        series, sono = parse_title(title)
        toi_raw, toi_num = parse_toi(ws.cell(row=r, column=COL_TOI).value)
        kaitei = ws.cell(row=r, column=COL_KAITEI).value
        haishi = ws.cell(row=r, column=COL_HAISHI).value

        rows.append({
            "src_no": int(src_no),
            "revision_code": to_revision_code(kaitei),
            "kaitei_label": kaitei,
            "issued_date": to_date(ws.cell(row=r, column=COL_DATE).value),
            "doc_title": title,
            "doc_series": series,
            "sono_no": sono,
            "bunrui": ws.cell(row=r, column=COL_BUNRUI).value or "未分類",
            "toi_no_raw": toi_raw or "",
            "toi_no_num": toi_num,
            "question": q,
            "answer": ws.cell(row=r, column=COL_A).value,
            "is_haishi": 1 if haishi else 0,
        })

    return rows, skipped, read_cover_note(wb)


def validate(rows, args):
    """期待値と突き合わせる。med-code-map の他ローダと同じ思想:
    不一致があれば投入を確定させず、呼び出し側で中止させる。
    戻り値: 失敗メッセージのリスト（空なら検証OK）。
    """
    failures = []

    checks = []
    if args.expected_total_rows is not None:
        checks.append(("総件数", args.expected_total_rows, len(rows)))
    elif not args.skip_known_profile_checks:
        checks.append(("総件数(既知プロファイル)", KNOWN_PROFILE["total_rows"], len(rows)))

    if not args.skip_known_profile_checks and args.expected_total_rows is None:
        actual_bunrui = {}
        actual_no_rev = 0
        for r in rows:
            actual_bunrui[r["bunrui"]] = actual_bunrui.get(r["bunrui"], 0) + 1
            if r["revision_code"] is None:
                actual_no_rev += 1
        for name, expected in KNOWN_PROFILE["bunrui"].items():
            checks.append((f"分類「{name}」件数", expected, actual_bunrui.get(name, 0)))
        checks.append(("改定紐付なし件数", KNOWN_PROFILE["no_revision_rows"], actual_no_rev))

    for name, expected, actual in checks:
        if expected != actual:
            failures.append(f"{name}: 期待={expected} 実測={actual}")

    return failures


def load(db_path, schema_path, xlsm_path, ver):
    rows, skipped, cover_note = extract_rows(xlsm_path)
    if not rows:
        raise SystemExit("取り込む行が無い")

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    with open(schema_path, encoding="utf-8") as f:
        conn.executescript(f.read())

    stamp = now_iso()
    conn.execute("DELETE FROM gigi_kaishaku WHERE source_ver = ?", (ver,))
    conn.execute("DELETE FROM gigi_source   WHERE ver        = ?", (ver,))

    conn.executemany(
        """INSERT INTO gigi_kaishaku
           (source_ver, src_no, revision_code, kaitei_label, issued_date,
            doc_title, doc_series, sono_no, bunrui, toi_no_raw, toi_no_num,
            question, answer, is_haishi, imported_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(ver, r["src_no"], r["revision_code"], r["kaitei_label"],
          r["issued_date"], r["doc_title"], r["doc_series"], r["sono_no"],
          r["bunrui"], r["toi_no_raw"], r["toi_no_num"], r["question"],
          r["answer"], r["is_haishi"], stamp) for r in rows],
    )

    latest = max(rows, key=lambda r: (r["issued_date"] or "", r["src_no"]))
    conn.execute(
        """INSERT INTO gigi_source
           (ver, sha256, fetched_at, imported_at, row_count,
            latest_issued_date, latest_doc_title, update_note)
           VALUES (?,?,?,?,?,?,?,?)""",
        (ver, sha256_of(xlsm_path), stamp, stamp, len(rows),
         latest["issued_date"], latest["doc_title"], cover_note),
    )

    conn.execute("INSERT INTO gigi_fts(gigi_fts) VALUES('rebuild')")
    conn.commit()

    return conn, rows, skipped, latest


def report(conn, rows, skipped, latest, ver, failures):
    cur = conn.cursor()
    status = "OK" if not failures else "NG（DBは投入済みだが要確認）"
    print(f"■ 取込 {status}  source_ver = {ver}")
    print(f"  投入件数: {len(rows)}")
    if skipped:
        print(f"  スキップ: {len(skipped)} 行 -> {skipped[:5]}")
    print(f"  最新収録: {latest['issued_date']}  {latest['doc_title']}")

    print("\n■ 改定年度別")
    for code, label, n in cur.execute(
        """SELECT revision_code, MIN(kaitei_label), COUNT(*)
           FROM gigi_kaishaku WHERE source_ver=?
           GROUP BY revision_code ORDER BY revision_code IS NULL, revision_code""",
        (ver,)):
        print(f"  {code or '(改定紐付なし)':<14} {n:>5}  {label or '療養費系'}")

    print("\n■ 分類別")
    for bunrui, n in cur.execute(
        """SELECT bunrui, COUNT(*) FROM gigi_kaishaku WHERE source_ver=?
           GROUP BY bunrui ORDER BY COUNT(*) DESC""", (ver,)):
        print(f"  {bunrui:<20} {n:>5}")

    if failures:
        print("\n■ 期待値との不一致（要確認。DBは中止していない＝行は入っている）")
        for f in failures:
            print(f"  [NG] {f}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("xlsm", help="疑義解釈検索ツール(.xlsm)のパス")
    p.add_argument("db", nargs="?", default="work/med-code-map.db")
    p.add_argument("--schema", default="sql/schema_gigi.sql")
    p.add_argument("--ver", help="省略時はファイル名から推定")
    p.add_argument("--expected-total-rows", type=int, default=None,
                   help="投入後の総件数がこれと一致しなければ exit 1")
    p.add_argument("--skip-known-profile-checks", action="store_true",
                   help="既知版(2026-09-15時点Ver.1.1.4)の期待値検証を飛ばす。"
                        "未知版を試すとき用。列の意味を保証するものではない")
    a = p.parse_args()

    ver = a.ver
    if not ver:
        m = re.search(r"(Ver[.\d]*\d)", a.xlsm)
        ver = m.group(1) if m else "unknown"

    conn, rows, skipped, latest = load(a.db, a.schema, a.xlsm, ver)
    failures = validate(rows, a)
    report(conn, rows, skipped, latest, ver, failures)
    conn.close()

    if failures:
        print("\n投入は完了したが期待値と不一致。原因を確認するまでこのDBを"
              "完成扱いにしないこと。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
