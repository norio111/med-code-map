const test = require('node:test');
const assert = require('node:assert/strict');
const data = require('../assets/impact-data.json');
const {classify, selectItems, evidenceURL} = require('../assets/impact.js');
const all = data.facilities.map(f => f.id);
test('browser script evaluates to exactly the JSON export, including provenance', () => {
  const fs = require('node:fs');
  const vm = require('node:vm');
  const context = {};
  vm.runInNewContext(fs.readFileSync(require.resolve('../assets/impact-data.js'), 'utf8'), context);
  assert.deepEqual(JSON.parse(JSON.stringify(context.MED_CODE_MAP_IMPACT_DATA)), data);
});
test('nine facilities return eight items and retain distinct variants', () => {
  const results = selectItems(data, all, 'R06-R08');
  assert.equal(results.length, 8);
  for (const row of results) {
    assert.equal(row.status, ['initial','acute','data'].includes(row.item.id) ? 'unknown' : 'conditional');
    assert.deepEqual(row.variants.map(v => v.facility_id), all);
  }
});
test('single selections never include a sibling scope, despite shared kijun 732', () => {
  for (const id of all) {
    const rows = selectItems(data, [id], 'R06-R08');
    assert.equal(rows.length, id.endsWith('_iii') ? 7 : 8);
    for (const row of rows) assert.deepEqual(row.variants.map(v => v.facility_id), [id]);
  }
});
test('no selection, explicit exclusions and unknown revision', () => {
  assert.deepEqual(selectItems(data, [], 'R06-R08', true), []);
  assert.equal(selectItems(data, all, 'R06-R08', true).filter(r => r.status === 'excluded').length, 1);
  assert.ok(selectItems(data, all, 'R04-R06').every(r => r.status === 'unknown'));
});
test('missing mappings and unknown relations do not become excluded or direct', () => {
  const item = structuredClone(data.policy_items[0]);
  item.variants = [];
  assert.equal(classify(item, all, 'R06-R08').status, 'unknown');
  item.variants = [{facility_id:all[0],relation:'unknown'}];
  assert.equal(classify(item, all, 'R06-R08').status, 'unknown');
  item.variants[0].relation = 'direct';
  assert.equal(classify(item, [all[0]], 'R06-R08').status, 'conditional');
  item.checks = [];
  assert.equal(classify(item, [all[0]], 'R06-R08').status, 'direct');
});
test('PDF navigation uses physical one-based page, not printed page', () => {
  assert.equal(evidenceURL(data.evidence.early), data.evidence.early.url + '#page=573');
  assert.equal(evidenceURL(data.evidence.master_R06), data.evidence.master_R06.url);
});

test('nine identities separate disease, grade and fee schedule number', () => {
  assert.equal(all.length, 9);
  assert.equal(new Set(all).size, 9);
  const scopes = {cerebrovascular:'H001', disuse:'H001-2', musculoskeletal:'H002'};
  for (const f of data.facilities) {
    assert.equal(f.kubun_no, scopes[f.rehab_type]);
    assert.equal(f.id, `${f.rehab_type}_${f.grade.toLowerCase()}`);
    assert.ok(f.evidence_ids.length && f.review_status);
    const rows = selectItems(data, [f.id], 'R06-R08', true);
    for (const row of rows.filter(r => r.item.id !== 'lymph')) {
      const expected = row.item.id === 'plan' && f.grade === 'III' ? 'excluded'
        : ['initial','acute','data'].includes(row.item.id) && f.grade !== 'I' ? 'unknown' : 'conditional';
      assert.equal(row.status, expected, `${f.id}/${row.item.id}`);
      if (expected !== 'conditional') assert.deepEqual(row.variants[0].code_map, []);
    }
  }
});
test('multiple grades retain individual relations and incomplete coverage stays unknown', () => {
  const plan = data.policy_items.find(i => i.id === 'plan');
  assert.equal(classify(plan, ['disuse_i','disuse_iii'], 'R06-R08').status, 'conditional');
  assert.equal(classify(plan, ['disuse_iii'], 'R06-R08').status, 'excluded');
  assert.equal(classify(plan, ['disuse_i','unregistered'], 'R06-R08').status, 'unknown');
});
