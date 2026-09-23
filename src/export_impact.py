"""Export explicitly curated policy mappings plus observed SQLite facts for Pages.

Never infer cross-revision identity from names or points. The reviewed JSON is
the only source of policy membership; the database supplies code attributes.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "H": {"old": 190, "new": 234, "removed": 80, "added": 124, "point_changed": 1},
    "unit28": {"old": 172, "new": 210, "removed": 75, "added": 113, "point_changed": 0},
}


def scope_counts(connection: sqlite3.Connection) -> dict:
    result = {}
    for scope, predicate in (("H", "m.kubun_no GLOB 'H[0-9]*'"),
                             ("unit28", "i.unit_code='28'")):
        versions = []
        for revision in ("R06", "R08"):
            versions.append(dict(connection.execute(f"""
                SELECT i.code, i.point FROM code_item i
                LEFT JOIN code_kubun_map m USING(cs_id,code,revision_id)
                WHERE i.cs_id=1 AND i.revision_id=? AND {predicate}
            """, (revision,))))
        old, new = versions
        result[scope] = dict(old=len(old), new=len(new),
                            removed=len(old.keys() - new.keys()),
                            added=len(new.keys() - old.keys()),
                            point_changed=sum(old[k] != new[k] for k in old.keys() & new.keys()))
    return result


def validate_catalog(data: dict) -> None:
    facilities = {f["id"]: f for f in data["facilities"]}
    evidence = data["evidence"]
    if len(facilities) != len(data['facilities']):
        raise ValueError('Duplicate facility ID')
    combinations = set()
    for f in facilities.values():
        identity = (f['rehab_type'], f['grade'])
        expected = {'cerebrovascular':'H001', 'disuse':'H001-2', 'musculoskeletal':'H002'}
        if (identity in combinations or f['grade'] not in ('I','II','III') or
            expected.get(f['rehab_type']) != f['kubun_no'] or not f['review_status'] or
            not f['evidence_ids'] or any(e not in evidence for e in f['evidence_ids'])):
            raise ValueError('Invalid facility identity / evidence')
        combinations.add(identity)
    ids = set()
    for e in evidence.values():
        if not e["url"].startswith("https://") or not e["locator"] or not e["review_status"]:
            raise ValueError("Evidence needs URL, locator and review status")
        if e.get("pdf_page") is not None and e["pdf_page"] < 1:
            raise ValueError("PDF page must be one-based")
    for item in data["policy_items"]:
        if item["id"] in ids:
            raise ValueError("Duplicate policy ID")
        ids.add(item["id"])
        for claim in item["changes"]:
            if claim["epistemic"] not in ("Fact", "Interpretation", "Hypothesis"):
                raise ValueError("Unknown epistemic status")
            if not claim["evidence_ids"] or any(e not in evidence for e in claim["evidence_ids"]):
                raise ValueError("Claim without evidence")
        variants = set()
        for variant in item["variants"]:
            if variant["facility_id"] in variants or variant["facility_id"] not in facilities:
                raise ValueError("Invalid variant")
            variants.add(variant["facility_id"])
            if variant["relation"] not in ("direct", "conditional", "unknown", "excluded"):
                raise ValueError("Invalid relation")
            if variant['relation'] in ('unknown', 'excluded') and variant['code_map']:
                raise ValueError('Unconfirmed/excluded relation cannot assert code membership')
            if variant["relation"] == "direct" and item["checks"]:
                raise ValueError("Remaining conditions cannot be direct")
            if not variant["evidence_ids"] or any(e not in evidence for e in variant["evidence_ids"]):
                raise ValueError("Relation without evidence")
            for mapping in variant["code_map"]:
                if (mapping["revision_id"] not in ("R06", "R08") or
                    len(mapping["code"]) != 9 or not mapping["code"].isdigit() or
                    not mapping["evidence_ids"] or
                    any(e not in evidence for e in mapping["evidence_ids"])):
                    raise ValueError("Invalid explicit code map")


def export(connection: sqlite3.Connection, catalog: dict) -> dict:
    validate_catalog(catalog)
    data = copy.deepcopy(catalog)
    counts = scope_counts(connection)
    if counts != EXPECTED:
        raise ValueError(f"Full R06/R08 snapshot required; scope mismatch: {counts}")
    data["machine"] = {"origin": "machine", "epistemic": "Fact", "scope_counts": counts}
    connection.row_factory = sqlite3.Row
    for item in data["policy_items"]:
        for variant in item["variants"]:
            for mapping in variant["code_map"]:
                row = connection.execute("""
                    SELECT i.display_short, i.point, i.point_kind, i.unit_code,
                           m.kubun_no, q.upper_value
                    FROM code_item i JOIN code_kubun_map m USING(cs_id,code,revision_id)
                    LEFT JOIN code_quantity_rule q USING(cs_id,code,revision_id)
                    WHERE i.cs_id=? AND i.code=? AND i.revision_id=?
                """, (mapping["cs_id"], mapping["code"], mapping["revision_id"])).fetchone()
                if row is None or row["kubun_no"] != mapping["expected_kubun"]:
                    raise ValueError(f"Code / kubun mismatch: {mapping}")
                if mapping.get('expected_grade'):
                    grade = next(f['grade'] for f in data['facilities'] if f['id'] == variant['facility_id'])
                    digit = {'I':'１','II':'２','III':'３'}[grade]
                    if mapping['expected_grade'] != grade or not row['display_short'].split('（', 1)[-1].startswith(digit+'）'):
                        raise ValueError('Code / grade mismatch')
                other_revision = "R08" if mapping["revision_id"] == "R06" else "R06"
                other = connection.execute("""SELECT point FROM code_item
                    WHERE cs_id=? AND code=? AND revision_id=?""",
                    (mapping["cs_id"], mapping["code"], other_revision)).fetchone()
                observation = dict(row)
                observation.update(origin="machine", epistemic="Fact",
                    presence="both" if other else ("old_only" if other_revision == "R08" else "new_only"),
                    same_code_point_changed=bool(other and other["point"] != row["point"]),
                    evidence_id="master_" + mapping["revision_id"])
                observation["facility_requirements"] = [dict(r) for r in connection.execute("""
                    SELECT group_no, slot_no, kijun_code FROM code_facility_req
                    WHERE cs_id=? AND code=? AND revision_id=? ORDER BY slot_no
                """, (mapping["cs_id"], mapping["code"], mapping["revision_id"]))]
                mapping["observation"] = observation
    return data


def browser_script(data: dict) -> str:
    """Serialize the same export as data, without evaluating strings as code."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # A quoted JSON string preserves keys such as __proto__ and safely escapes
    # quotes, backslashes and Unicode line separators in source material.
    return ("// Generated by src/export_impact.py; DO NOT EDIT.\n"
            "// Editorial source: data/impact-catalog.json; attributes: audited SQLite.\n"
            "globalThis.MED_CODE_MAP_IMPACT_DATA = JSON.parse("
            + json.dumps(payload, ensure_ascii=True) + ");\n")


def write_outputs(data: dict, output: Path) -> None:
    if output.suffix != ".json":
        raise ValueError("--output must end in .json (a sibling .js is also generated)")
    json_text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    script_text = browser_script(data)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json_text, encoding="utf-8")
    output.with_suffix(".js").write_text(script_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/impact-catalog.json")
    parser.add_argument("--output", type=Path, default=ROOT / "assets/impact-data.json")
    args = parser.parse_args()
    raw = args.catalog.read_bytes()
    connection = sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        result = export(connection, json.loads(raw))
    finally:
        connection.close()
    result["machine"]["catalog_sha256"] = hashlib.sha256(raw).hexdigest()
    write_outputs(result, args.output)
    print(f"Exported {len(result['policy_items'])} policy items: {args.output} + {args.output.with_suffix('.js')}")


if __name__ == "__main__":
    main()
