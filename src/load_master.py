#!/usr/bin/env python3
"""医科診療行為マスターを検証し、対応表SQLiteへ取り込む。"""

from __future__ import annotations

import argparse
import sqlite3
import tempfile
from pathlib import Path

import pandas as pd


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
UNIT_FILTER = "28"
CODE_SYSTEM = (
    1,
    "S",
    "医科診療行為マスター",
    "http://jpfhir.jp/fhir/core/CodeSystem/JP_ProcedureCodesMedical_CS",
    "社会保険診療報酬支払基金",
    "数字9桁",
)

# 名称は基本マスターに存在しないため、点数表との照合状態を verified=0 で保持する。
KUBUN_NAME = {
    "H000": "心大血管疾患リハビリテーション料",
    "H001": "脳血管疾患等リハビリテーション料",
    "H002": "運動器リハビリテーション料",
    "H003": "呼吸器リハビリテーション料",
    "H007": "障害児（者）リハビリテーション料",
    "H008": "摂食機能療法",
    "C006": "在宅患者訪問リハビリテーション指導管理料",
}

# 別紙7-8から転記した候補。公開版では未検証値として扱う。
KIJUN_NAME = {
    "730": "心大血管疾患リハビリテーション料（１）",
    "731": "心大血管疾患リハビリテーション料（２）",
    "732": "脳血管疾患等リハビリテーション料（１）",
    "733": "脳血管疾患等リハビリテーション料（２）",
    "734": "脳血管疾患等リハビリテーション料（３）",
    "737": "呼吸器リハビリテーション料（１）",
    "738": "呼吸器リハビリテーション料（２）",
    "828": "運動器リハビリテーション料（１）",
    "829": "運動器リハビリテーション料（２）",
    "830": "運動器リハビリテーション料（３）",
    "831": "がん患者リハビリテーション料",
    "849": "リハビリテーション総合計画評価料１",
    "628": "障害児（者）リハビリテーション料",
    "3358": "認知症患者リハビリテーション料",
    "3067": "初期加算及び急性期リハビリテーション加算",
    "3780": "リハビリテーションデータ提出加算",
    "3843": "算定上限日数に関する基準",
    "124": "難病患者リハビリテーション料",
    "704": "集団コミュニケーション療法料",
}


def col(number: int) -> str:
    return f"c{number}"


def blank(value: object) -> bool:
    return value is None or str(value).strip() in ("", "0", "00", "000", "0000")


def number_or_none(value: object) -> float | None:
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"数値として解釈できません: {value!r}") from exc


def assert_equal(actual: int, expected: int | None, label: str) -> None:
    if expected is not None and actual != expected:
        raise ValueError(f"{label}: 実測 {actual} / 期待 {expected}")


def build_database(args: argparse.Namespace) -> None:
    frame = pd.read_csv(
        args.master,
        header=None,
        dtype=str,
        encoding="cp932",
        keep_default_na=False,
    )
    frame.columns = [col(i + 1) for i in range(frame.shape[1])]
    if frame.shape[1] < 117:
        raise ValueError(f"医科診療行為マスターの列数が不足しています: {frame.shape[1]}列")
    assert_equal(len(frame), args.expected_total_rows, "入力マスター行数")

    selected = frame if args.all else frame[frame[col(8)] == UNIT_FILTER]
    assert_equal(len(selected), args.expected_selected_rows, "取込対象行数")

    revision = (
        args.revision_id,
        args.revision_label,
        args.effective_from,
        args.effective_to,
    )

    destination = args.output_db.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(
            f"出力先が既に存在します: {destination}\n"
            "既存DBを保護するため上書きしません。別名を指定してください。"
        )

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
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

        kubun_rows: dict[str, tuple] = {}
        kijun_rows: dict[str, tuple] = {}
        unknown_kijun: set[str] = set()
        items: list[tuple] = []
        quantity_rules: list[tuple] = []
        maps: list[tuple] = []
        requirements: list[tuple] = []

        for _, row in selected.iterrows():
            code = row[col(3)]
            items.append(
                (
                    1,
                    code,
                    row[col(5)],
                    row[col(113)] or None,
                    row[col(8)] or None,
                    row[col(10)] or None,
                    row[col(11)] or None,
                    number_or_none(row[col(12)]),
                    row[col(68)] or None,
                    row[col(87)] or None,
                    row[col(88)] or None,
                )
            )

            if row[col(30)] == "1":
                quantity_rules.append(
                    (
                        1,
                        code,
                        int(row[col(31)] or 0),
                        int(row[col(32)] or 0),
                        int(row[col(33)] or 0),
                        number_or_none(row[col(34)]),
                        row[col(35)],
                    )
                )

            alpha = row[col(85)].strip()
            digits = row[col(92)].strip()
            if alpha not in ("", "*", "-") and digits:
                kubun_number = alpha + digits
                kubun_rows.setdefault(
                    kubun_number,
                    (
                        kubun_number,
                        args.revision_id,
                        KUBUN_NAME.get(kubun_number),
                        row[col(90)],
                        row[col(91)],
                        0,
                    ),
                )
                maps.append(
                    (
                        1,
                        code,
                        args.revision_id,
                        kubun_number,
                        row[col(94)] or None,
                        row[col(117)] or None,
                    )
                )

            for slot in range(1, 11):
                value = row[col(71 + slot)].strip()
                if blank(value):
                    continue
                group = 1 if slot <= 6 else (2 if slot <= 9 else 3)
                kijun_rows.setdefault(
                    value,
                    (
                        value,
                        KIJUN_NAME.get(value),
                        1 if value.startswith("8") and len(value) == 4 else 0,
                    ),
                )
                if value not in KIJUN_NAME:
                    unknown_kijun.add(value)
                requirements.append(
                    (1, code, args.revision_id, group, slot, value)
                )

        with connection:
            connection.execute(
                """
                INSERT INTO revision (
                    revision_id, label, effective_from, effective_to
                ) VALUES (?,?,?,?)
                """,
                revision,
            )
            connection.execute(
                """
                INSERT INTO codesystem (
                    cs_id, master_type, name, fhir_uri, authority, code_format
                ) VALUES (?,?,?,?,?,?)
                """,
                CODE_SYSTEM,
            )
            connection.executemany(
                """
                INSERT INTO code_item (
                    cs_id, code, display_short, display_full, unit_code,
                    unit_name, point_kind, point, kokuji_kind,
                    changed_on, abolished_on
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                items,
            )
            connection.executemany(
                """
                INSERT INTO code_quantity_rule (
                    cs_id, code, lower_value, upper_value,
                    step_value, step_point, error_handling
                ) VALUES (?,?,?,?,?,?,?)
                """,
                quantity_rules,
            )
            connection.executemany(
                """
                INSERT INTO kubun (
                    kubun_no, revision_id, name, chapter, part, verified
                ) VALUES (?,?,?,?,?,?)
                """,
                kubun_rows.values(),
            )
            connection.executemany(
                """
                INSERT INTO facility_kijun (
                    kijun_code, name, is_meyose
                ) VALUES (?,?,?)
                """,
                kijun_rows.values(),
            )
            connection.executemany(
                """
                INSERT INTO code_kubun_map (
                    cs_id, code, revision_id, kubun_no, item_no, kubun_text
                ) VALUES (?,?,?,?,?,?)
                """,
                maps,
            )
            connection.executemany(
                """
                INSERT INTO code_facility_req (
                    cs_id, code, revision_id, group_no, slot_no, kijun_code
                ) VALUES (?,?,?,?,?,?)
                """,
                requirements,
            )

        connection.close()
        connection = None
        tmp_path.replace(destination)
    except Exception:
        if connection is not None:
            connection.close()
        tmp_path.unlink(missing_ok=True)
        raise

    print(f"code_item:          {len(items):>5}")
    print(f"code_quantity_rule: {len(quantity_rules):>5}")
    print(f"code_kubun_map:     {len(maps):>5}")
    print(f"code_facility_req:  {len(requirements):>5}")
    print(f"kubun: {len(kubun_rows)} / facility_kijun: {len(kijun_rows)}")
    if unknown_kijun:
        print("名称未登録の施設基準コード:", sorted(unknown_kijun))
    print(f"検証済みDBを作成しました: {destination}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path, help="医科診療行為マスター（cp932）")
    parser.add_argument("output_db", type=Path, help="新規作成するSQLite DB")
    parser.add_argument("--all", action="store_true", help="全件を取り込む")
    parser.add_argument("--revision-id", required=True, help="例: R06")
    parser.add_argument("--revision-label", required=True, help="改定の表示名")
    parser.add_argument("--effective-from", required=True, help="YYYY-MM-DD")
    parser.add_argument("--effective-to", help="YYYY-MM-DD。現行なら省略")
    parser.add_argument("--expected-total-rows", type=int)
    parser.add_argument("--expected-selected-rows", type=int)
    return parser.parse_args()


if __name__ == "__main__":
    build_database(parse_args())
