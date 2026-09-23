from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import export_impact
import load_master
from test_smoke import write_cp932_rows


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT / 'data/impact-catalog.json').read_text(encoding='utf-8'))
        self.public = json.loads((ROOT / 'assets/impact-data.json').read_text(encoding='utf-8'))

    def test_catalog_and_generated_provenance(self):
        export_impact.validate_catalog(self.catalog)
        expected_hash = hashlib.sha256((ROOT / 'data/impact-catalog.json').read_bytes()).hexdigest()
        self.assertEqual(self.public['machine']['catalog_sha256'], expected_hash)
        for item in self.public['policy_items']:
            for variant in item['variants']:
                self.assertIn(variant['relation'], ('conditional', 'unknown', 'excluded'))
                for mapping in variant['code_map']:
                    self.assertEqual(mapping['origin'], 'manual')
                    self.assertEqual(mapping['observation']['origin'], 'machine')
                    self.assertEqual(mapping['observation']['kubun_no'], mapping['expected_kubun'])

    def test_browser_script_is_generated_from_the_identical_export(self):
        self.assertEqual((ROOT/'assets/impact-data.js').read_text(encoding='utf-8'),
                         export_impact.browser_script(self.public))
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'custom.json'
            export_impact.write_outputs(self.public, output)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8')), self.public)
            self.assertEqual(output.with_suffix('.js').read_text(encoding='utf-8'),
                             export_impact.browser_script(self.public))
            with self.assertRaises(ValueError):
                export_impact.write_outputs(self.public, Path(tmp)/'invalid.js')

    def test_missing_evidence_and_unsafe_direct_relation_rejected(self):
        broken = copy.deepcopy(self.catalog)
        broken['policy_items'][0]['changes'][0]['evidence_ids'] = []
        with self.assertRaises(ValueError):
            export_impact.validate_catalog(broken)
        broken = copy.deepcopy(self.catalog)
        broken['policy_items'][0]['variants'][0]['relation'] = 'direct'
        with self.assertRaises(ValueError):
            export_impact.validate_catalog(broken)

    def test_new_patient_item_never_links_to_old_reduction(self):
        items = {i['id']: i for i in self.public['policy_items']}
        for variant in items['specific']['variants']:
            self.assertTrue(variant['code_map'])
            for mapping in variant['code_map']:
                self.assertEqual(mapping['revision_id'], 'R08')
                self.assertEqual(mapping['observation']['upper_value'], 2)
                grade = next(f['grade'] for f in self.public['facilities'] if f['id'] == variant['facility_id'])
                self.assertTrue(mapping['observation']['display_short'].split('（',1)[1].startswith({'I':'１','II':'２','III':'３'}[grade]+'）'))
        for variant in items['reduction']['variants']:
            self.assertTrue(all(m['revision_id'] == 'R06' for m in variant['code_map']))

    def test_disease_code_sets_are_separate(self):
        early = self.public['policy_items'][0]
        expected = {'H001': {'180763870', '180763970'},
                    'H001-2': {'180767070', '180767170'},
                    'H002': {'180770270', '180770370'}}
        for v in early['variants']:
            actual = {m['code'] for m in v['code_map'] if m['revision_id'] == 'R08'}
            facility = next(f for f in self.public['facilities'] if f['id'] == v['facility_id'])
            self.assertEqual(actual, expected[facility['kubun_no']])
            self.assertEqual([e for e in v['evidence_ids'] if e.startswith('notice_')],
                             ['notice_'+facility['kubun_no']])

    def test_nine_facilities_and_complete_explicit_relations(self):
        facilities = self.catalog['facilities']
        self.assertEqual(len(facilities), 9)
        identities = {(f['rehab_type'], f['grade']) for f in facilities}
        self.assertEqual(len(identities), 9)
        for item in self.catalog['policy_items']:
            if item['id'] != 'lymph':
                self.assertEqual({v['facility_id'] for v in item['variants']}, {f['id'] for f in facilities})
                self.assertEqual(len(item['variants']), 9)
        broken = copy.deepcopy(self.catalog)
        broken['facilities'][0]['kubun_no'] = 'H001-2'
        with self.assertRaises(ValueError):
            export_impact.validate_catalog(broken)
        broken = copy.deepcopy(self.catalog)
        broken['policy_items'][0]['variants'].append(broken['policy_items'][0]['variants'][0])
        with self.assertRaises(ValueError):
            export_impact.validate_catalog(broken)


class KubunRegression(unittest.TestCase):
    def test_branch_and_non_h_scope_through_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            csv_path, db = path / 'sample.csv', path / 'sample.db'
            rows = []
            for i, (alpha, digits, branch) in enumerate([
                ('H', '001', '00'), ('H', '001', '02'), ('H', '008', '00'),
                ('H', '004', '00'), ('C', '006', '00')]):
                rows.append({2:'S',3:str(180000001+i),5:'架空データ',8:'28',11:'3',12:'100',
                             85:alpha,92:digits,93:branch,72:'732'})
            write_cp932_rows(csv_path,150,rows)
            with contextlib.redirect_stdout(io.StringIO()):
                load_master.build_database(argparse.Namespace(master=csv_path,output_db=db,all=True,
                    revision_id='R06',revision_label='架空',effective_from='2024-06-01',effective_to=None,
                    expected_total_rows=5,expected_selected_rows=5,append=False))
            with contextlib.closing(sqlite3.connect(db)) as c:
                kubuns = {r[0] for r in c.execute('SELECT kubun_no FROM code_kubun_map')}
                self.assertEqual(kubuns, {'H001','H001-2','H008','H004','C006'})
                self.assertEqual(c.execute("SELECT name FROM kubun WHERE kubun_no='H008'").fetchone()[0], '集団コミュニケーション療法料')
                self.assertEqual(export_impact.scope_counts(c)['H']['old'],4)
                self.assertEqual(export_impact.scope_counts(c)['unit28']['old'],5)
                with self.assertRaises(ValueError):
                    export_impact.export(c, json.loads((ROOT/'data/impact-catalog.json').read_text(encoding='utf-8')))


@unittest.skipUnless(all((ROOT/'data/private'/f).exists() for f in
    ('s_20260501.csv','s_20260911.csv')), 'Private R06/R08 snapshots not installed')
class RealSnapshotRegression(unittest.TestCase):
    def test_full_snapshots_and_public_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp)/'full.db'
            for rev, filename, total in [('R06','s_20260501.csv',10192),('R08','s_20260911.csv',11833)]:
                with contextlib.redirect_stdout(io.StringIO()):
                    load_master.build_database(argparse.Namespace(master=ROOT/'data/private'/filename,
                        output_db=database,all=True,revision_id=rev,revision_label=rev,
                        effective_from='2024-06-01' if rev=='R06' else '2026-06-01',effective_to=None,
                        expected_total_rows=total,expected_selected_rows=total,append=rev=='R08'))
            with contextlib.closing(sqlite3.connect(database)) as c:
                self.assertEqual(export_impact.scope_counts(c), export_impact.EXPECTED)
                catalog=json.loads((ROOT/'data/impact-catalog.json').read_text(encoding='utf-8'))
                generated=export_impact.export(c,catalog)
                public=json.loads((ROOT/'assets/impact-data.json').read_text(encoding='utf-8'))
                self.assertEqual(generated['policy_items'],public['policy_items'])
                broken=copy.deepcopy(catalog)
                broken['policy_items'][0]['variants'][1]['code_map'][-1]['expected_kubun']='H008'
                with self.assertRaises(ValueError):
                    export_impact.export(c,broken)
                broken=copy.deepcopy(catalog)
                specific=next(i for i in broken['policy_items'] if i['id']=='specific')
                specific['variants'][0]['code_map'][0]['expected_grade']='III'
                with self.assertRaises(ValueError):
                    export_impact.export(c,broken)


if __name__ == '__main__':
    unittest.main()
