/* Pure matching is shared by the browser and Node regression tests. */
(function (root) {
  'use strict';
  const labels = {direct: '対象', conditional: '条件付き', unknown: '要確認', excluded: '対象外'};
  function classify(item, selected, comparison) {
    if (comparison !== `${item.revision_from}-${item.revision_to}` || !selected.length)
      return {status: 'unknown', variants: [], reason: '比較年度または施設基準を確認してください。'};
    const variants = item.variants.filter(v => selected.includes(v.facility_id));
    if (!variants.length) return {status: item.outside_reason ? 'excluded' : 'unknown', variants,
      reason: item.outside_reason || '対応情報が未登録です。関係なしとは判定できません。'};
    const missing = selected.some(id => !variants.some(v => v.facility_id === id));
    const status = missing || variants.some(v => v.relation === 'unknown') ? 'unknown'
      : variants.every(v => v.relation === 'excluded') ? 'excluded'
      : variants.some(v => v.relation === 'conditional') || item.checks.length ? 'conditional' : 'direct';
    return {status, variants, reason: variants.map(v => v.reason).filter((v, i, a) => a.indexOf(v) === i).join(' ')};
  }
  function selectItems(data, selected, comparison, showExcluded = false) {
    if (!selected.length) return [];
    return data.policy_items.map(item => ({item, ...classify(item, selected, comparison)}))
      .filter(result => showExcluded || result.status !== 'excluded');
  }
  function evidenceURL(e) { return e.url + (e.pdf_page ? `#page=${e.pdf_page}` : ''); }
  const api = {labels, classify, selectItems, evidenceURL};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.Impact = api;
  if (typeof document === 'undefined') return;

  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const status = document.getElementById('status');
  const results = document.getElementById('results');
  const form = document.getElementById('profile');
  const run = document.getElementById('run');
  let data;
  let executed = false;
  const selected = () => [...form.querySelectorAll('input[name="facility"]:checked')].map(n => n.value);

  const relationText = {
    direct: 'この変更は、選択した施設基準に直接関係します。',
    conditional: 'この変更は、選択した施設基準に関係します。実際に算定できるかは、患者の状態、入院日、実施内容などの追加条件を確認してください。',
    unknown: '選択した施設基準との関係を、現在の収録資料だけでは確認できていません。施設基準の告示・通知を確認してください。',
    excluded: 'この変更は、選択した施設基準単独では対象になりません。ほかの届出を併せている場合は確認が必要です。'
  };
  const auditLabel = (epistemic, origin) => {
    if (epistemic === 'Fact' && origin === 'manual') return '資料に記載された変更（Fact／手入力）';
    if (epistemic === 'Fact' && origin === 'machine') return '診療行為マスターで確認（Fact／機械抽出）';
    if (epistemic === 'Interpretation' && origin === 'manual') return '本アプリで制度項目と対応付け（Interpretation／手入力）';
    if (epistemic === 'Hypothesis') return '未確認情報（Hypothesis）';
    return `${epistemic}／${origin}`;
  };
  const reviewText = value => (value || '').replace(/(?:・|／)?人による最終確認(?:は|：)?(?:未実施|待ち)/g, '').trim();
  const sourceIds = (item, variants) => [...new Set([
    ...item.changes.flatMap(change => change.evidence_ids),
    ...(item.outside_evidence_ids || []),
    ...variants.flatMap(variant => [
      ...variant.evidence_ids,
      ...(data.facilities.find(f => f.id === variant.facility_id)?.evidence_ids || []),
      ...variant.code_map.flatMap(mapping => [
        ...mapping.evidence_ids, ...(mapping.observation?.evidence_id ? [mapping.observation.evidence_id] : [])
      ])
    ])
  ])];
  const sourceLink = (source, label) => {
    const a = el('a', label);
    a.href = evidenceURL(source); a.target = '_blank'; a.rel = 'noopener noreferrer';
    return a;
  };

  function mainEvidence(parent, item, variants) {
    const ids = sourceIds(item, variants);
    // A short route into the source material; the complete claim-level roster
    // with URLs, pages and review states remains in the audit disclosure.
    const preferred = [
      ...item.changes.flatMap(change => change.evidence_ids)
        .filter(id => data.evidence[id]?.source_kind === 'primary_proposal'),
      ...variants.flatMap(variant => variant.evidence_ids)
        .filter(id => id.startsWith('scope_') || id === 'grades_plan'),
      ...ids.filter(id => data.evidence[id]?.source_kind === 'primary_notice')
    ];
    const chosen = [];
    const seen = new Set();
    for (const id of [...preferred, ...ids]) {
      const source = data.evidence[id];
      if (!source) continue;
      const url = evidenceURL(source);
      if (seen.has(url)) continue;
      seen.add(url); chosen.push(source);
      if (chosen.length === 2) break;
    }
    if (!chosen.length) return;
    const line = el('p', undefined, 'main-sources');
    line.append(el('strong', '主な根拠資料：'));
    chosen.forEach((source, index) => {
      if (index) line.append(document.createTextNode(' ／ '));
      line.append(sourceLink(source, `${source.title} — ${source.locator}`));
    });
    parent.append(line);
  }

  function auditEvidence(parent, ids) {
    if (!ids.length) return;
    const roster = el('section', undefined, 'audit-sources');
    roster.append(el('h4', '根拠資料・ページ・確認状態'));
    const grouped = new Map();
    for (const id of ids) {
      const source = data.evidence[id];
      if (!source) continue;
      const key = evidenceURL(source);
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push({id, source});
    }
    for (const entries of grouped.values()) {
      const first = entries[0].source;
      const line = el('div', undefined, 'source');
      const locators = [...new Set(entries.map(entry => entry.source.locator))].join('；');
      line.append(sourceLink(first, `${first.title} — ${locators}`));
      for (const {id, source} of entries) {
        const metadata = [`根拠ID：${id}`, `確認状態：${reviewText(source.review_status) || '記録なし'}`];
        if (source.summary) metadata.push(`資料の要旨：${source.summary}`);
        if (source.reviewed_on) metadata.push(`確認日：${source.reviewed_on}`);
        if (source.printed_page != null) metadata.push(`本文ページ：${source.printed_page}`);
        if (source.pdf_page != null) metadata.push(`PDF通しページ：${source.pdf_page}`);
        if (source.sha256) metadata.push(`入力ファイルSHA-256：${source.sha256}`);
        if (source.filename) metadata.push(`ファイル名：${source.filename}`);
        if (source.source_kind) metadata.push(`資料種別：${source.source_kind}`);
        if (source.audit_record) metadata.push(`監査記録：${source.audit_record}`);
        line.append(el('p', metadata.join(' ／ '), 'meta'));
      }
      roster.append(line);
    }
    if (grouped.size) parent.append(roster);
  }

  function finalReview(item, variants, ids) {
    const entries = [
      ...item.changes,
      ...variants,
      ...variants.flatMap(v => v.code_map),
      ...variants.map(v => data.facilities.find(f => f.id === v.facility_id)).filter(Boolean),
      ...ids.map(id => data.evidence[id]).filter(Boolean)
    ];
    const records = [...new Set(entries.map(entry => entry.human_review).filter(Boolean)
      .map(value => typeof value === 'string' ? value : JSON.stringify(value)))];
    return records.length ? `専門職による最終確認：記録あり（${records.join(' ／ ')}）`
      : '専門職による最終確認：未実施';
  }

  function render() {
    const choices = selected();
    results.replaceChildren();
    if (!choices.length) {
      status.textContent = '施設基準を1つ以上選択してください。';
      return;
    }
    const rows = selectItems(data, choices, document.getElementById('comparison').value,
      document.getElementById('excluded').checked);
    const counts = Object.fromEntries(Object.keys(labels).map(k => [k, rows.filter(r => r.status === k).length]));
    const names = choices.map(id => data.facilities.find(f => f.id === id).name).join('・');
    status.textContent = `${rows.length}項目：対象 ${counts.direct}／条件付き ${counts.conditional}／要確認 ${counts.unknown}／対象外 ${counts.excluded}。選択：${names}`;
    for (const result of rows) {
      const {item, variants} = result;
      const card = el('article', undefined, 'card'); card.dataset.policy = item.id;
      const heading = el('div', undefined, 'card-heading');
      heading.append(el('span', labels[result.status], `badge ${result.status}`), el('h3', item.name));
      card.append(heading);
      if (item.changes.length) {
        card.append(el('h4', '何が変わったか'));
        const tableWrap = el('div', undefined, 'table-wrap');
        const table = el('table', undefined, 'change-table');
        const head = el('tr');
        ['変更の種類', '令和6年度', '令和8年度'].forEach(t => { const h = el('th', t); h.scope = 'col'; head.append(h); });
        const thead = el('thead'); thead.append(head); table.append(thead);
        const body = el('tbody');
        item.changes.forEach(change => {
          const row = el('tr');
          const h = el('th', change.kind); h.scope = 'row'; row.append(h, el('td', change.old), el('td', change.new));
          body.append(row);
        });
        table.append(body); tableWrap.append(table); card.append(tableWrap);
      }
      card.append(el('h4', '自院の届出との関係'));
      const relation = el('p', relationText[result.status], 'relation-copy');
      card.append(relation);
      const limited = result.status === 'excluded' && item.id === 'plan'
        ? variants.map(v => v.reason).filter(Boolean) : result.status === 'unknown'
          ? variants.filter(v => v.relation === 'unknown').map(v => v.reason).filter(Boolean) : [];
      for (const reason of [...new Set(limited)]) card.append(el('p', reason, 'relation-note'));
      if (item.checks.length) {
        card.append(el('h4', '実務上確認すべきこと'));
        const checks = el('ul', undefined, 'check-list');
        item.checks.forEach(t => checks.append(el('li', t)));
        card.append(checks);
      }
      mainEvidence(card, item, variants);

      const details = el('details', undefined, 'audit-details');
      details.append(el('summary', '判定根拠・コード・監査情報を確認する'));
      const auditBody = el('div', undefined, 'audit-body');
      const ids = sourceIds(item, variants);
      auditBody.append(el('p', finalReview(item, variants, ids), 'final-review'));
      auditBody.append(el('p', '判定方法：監査対応表によるルール判定。選択区分と編集済みの制度対応を照合しています。算定可否の最終判断ではありません。', 'meta'));
      if (result.reason) auditBody.append(el('p', `登録された対応理由：${result.reason}`, 'meta'));
      if (item.changes.length) {
        const claims = el('section', undefined, 'audit-claims');
        claims.append(el('h4', '制度変更の記載と対応付け'));
        const list = el('ul');
        for (const change of item.changes) {
          const li = el('li');
          li.append(el('strong', `${change.kind}：${auditLabel(change.epistemic, change.origin)}`));
          li.append(el('p', `確認状態：${reviewText(change.review_status) || '記録なし'} ／ 根拠ID：${change.evidence_ids.join('、')}`, 'meta'));
          list.append(li);
        }
        claims.append(list); auditBody.append(claims);
      }
      if (variants.length) {
        const variantSection = el('section', undefined, 'audit-variants');
        variantSection.append(el('h4', '選択区分ごとの判定とコード'));
        variantSection.append(el('p', 'コードの所属は編集済み対応表、点数・名称・年度間の存在は診療行為マスターの記載です。集合差だけでは制度上の新設・廃止を確定できません。共通コードは複数区分に再掲します。', 'meta'));
        for (const variant of variants) {
          const facility = data.facilities.find(f => f.id === variant.facility_id);
          const group = el('details', undefined, 'variant'); group.dataset.facility = facility.id;
          group.append(el('summary', `${facility.name}／区分番号 ${facility.kubun_no}：${labels[variant.relation]}`));
          const content = el('div', undefined, 'variant-body');
          content.append(el('p', variant.reason));
          content.append(el('p', `${auditLabel(variant.epistemic, variant.origin)} ／ 対応の確認状態：${reviewText(variant.review_status) || '記録なし'} ／ 根拠ID：${variant.evidence_ids.join('、')}`, 'meta'));
          content.append(el('p', `施設選択肢の確認状態：${reviewText(facility.review_status) || '記録なし'} ／ 根拠ID：${facility.evidence_ids.join('、')}`, 'meta'));
          if (!variant.code_map.length) {
            content.append(el('p', 'この区分へのコード対応は未登録です', 'no-codes'));
          } else {
            const list = el('ul', undefined, 'code-list');
            for (const mapping of variant.code_map) {
              const o = mapping.observation;
              const presence = {both: '両年度に存在', old_only: 'R06のみ（集合差）', new_only: 'R08のみ（集合差）'}[o.presence];
              const li = el('li');
              li.append(el('code', `${mapping.revision_id}／${mapping.code}／区分番号 ${o.kubun_no}`));
              li.append(el('div', `${o.display_short}：${o.point}点（点数識別 ${o.point_kind}）`));
              li.append(el('p', `${auditLabel(o.epistemic, o.origin)}：${presence}。同一コード点数変更：${o.presence === 'both' ? (o.same_code_point_changed ? 'あり' : 'なし') : '比較対象なし'}。きざみ上限：${o.upper_value ?? '記録なし'}。根拠ID：${o.evidence_id}`, 'meta'));
              if (o.facility_requirements.length) li.append(el('p', '施設基準枠：' + o.facility_requirements.map(r => `G${r.group_no}・枠${r.slot_no}=${r.kijun_code}`).join(' ／ '), 'meta'));
              li.append(el('p', `${auditLabel(mapping.epistemic, mapping.origin)} ／ 対応の確認状態：${reviewText(mapping.review_status) || '記録なし'} ／ 根拠ID：${mapping.evidence_ids.join('、')}`, 'meta'));
              list.append(li);
            }
            content.append(list);
          }
          group.append(content); variantSection.append(group);
        }
        auditBody.append(variantSection);
      }
      auditEvidence(auditBody, ids);
      details.append(auditBody); card.append(details);
      results.append(card);
    }
  }

  form.addEventListener('submit', event => { event.preventDefault(); if (data) { executed = true; render(); } });
  form.addEventListener('change', () => {
    run.disabled = !data || !selected().length || root.ImpactStartup.failed;
    if (executed && !root.ImpactStartup.failed) render();
  });
  document.getElementById('clear').addEventListener('click', () => {
    form.querySelectorAll('input[name="facility"]').forEach(n => { n.checked = false; });
    results.replaceChildren(); status.textContent = '施設基準を選択して実行してください。'; executed = false;
    run.disabled = true;
  });
  try {
    if (root.ImpactStartup.failed) return;
    const value = root.MED_CODE_MAP_IMPACT_DATA;
    if (!value) throw new Error('impact-data.js のデータがありません。');
    if (value.schema_version !== 1 || !Array.isArray(value.facilities) || !value.facilities.length ||
        !value.facilities.every(f => f.id && f.name && f.kubun_no && f.rehab_type && f.grade && f.evidence_ids?.length) ||
        !value.comparison?.id || !value.comparison?.label ||
        !Array.isArray(value.policy_items) || !value.policy_items.length || !value.evidence ||
        !value.machine?.scope_counts?.H || !value.machine?.scope_counts?.unit28)
      throw new Error('impact-data.js の形式または必須項目が不正です。');
    data = value;
    const choices = document.getElementById('facilities');
    choices.replaceChildren();
    for (const type of [...new Set(data.facilities.map(f => f.rehab_type))]) {
      const members = data.facilities.filter(f => f.rehab_type === type);
      const group = el('fieldset', undefined, 'disease-group');
      group.append(el('legend', members[0].rehab_name));
      group.append(el('p', '区分番号 ' + members[0].kubun_no, 'meta'));
      const grades = el('div', undefined, 'grade-choices');
      members.forEach(f => {
      const label = el('label', undefined, 'choice');
      const input = el('input'); input.type = 'checkbox'; input.name = 'facility'; input.value = f.id;
      input.setAttribute('aria-label', f.name);
      label.append(input, el('span', {I:'Ⅰ', II:'Ⅱ', III:'Ⅲ'}[f.grade])); grades.append(label);
      });
      group.append(grades);
      const sources = el('details'); sources.append(el('summary', '選択肢の根拠・確認状態'));
      sources.append(el('p', `選択肢の確認状態：${reviewText(members[0].review_status) || '記録なし'}`, 'meta'));
      auditEvidence(sources, members[0].evidence_ids);
      group.append(sources); choices.append(group);
    }
    const select = document.getElementById('comparison');
    const option = el('option', data.comparison.label); option.value = data.comparison.id; select.replaceChildren(option);
    select.disabled = false;
    const counts = data.machine.scope_counts;
    document.getElementById('scope-counts').textContent = `単位系（規格28）：${counts.unit28.old}→${counts.unit28.new}件、消滅75・新設113・同一コード点数変更0。H区分：${counts.H.old}→${counts.H.new}件、消滅80・新設124・同一コード点数変更1。`;
    status.textContent = '施設基準を選択して実行してください。'; run.disabled = true;
    document.getElementById('clear').disabled = false;
    root.ImpactStartup.ready = true;
    document.getElementById('startup-help').hidden = true;
  } catch (error) {
    data = undefined;
    root.ImpactStartup.fail('初期化できませんでした。' + error.message);
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
