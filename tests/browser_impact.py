"""Real Edge checks for HTTP and file URLs, including missing/broken scripts."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import shutil
import tempfile
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def exercise(page, url, mode):
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url)
    page.wait_for_function('window.ImpactStartup.ready')
    assert page.locator('input[name=facility]').count() == 9
    assert page.locator('#comparison option').count() == 1
    assert page.locator('#comparison').input_value() == 'R06-R08'
    assert page.locator('#comparison option').inner_text().replace(' ', '') == '令和6年度→令和8年度'
    assert page.locator('#startup-help').is_hidden()
    assert page.locator('#run').is_disabled()
    for f in json.loads((ROOT/'assets/impact-data.json').read_text(encoding='utf-8'))['facilities']:
        facility = f['id']
        page.locator(f'input[value="{facility}"]').check()
        assert page.locator('#run').is_enabled()
        page.locator('#run').click()
        assert page.locator('article.card').count() == (7 if f['grade']=='III' else 8)
        assert page.locator('article .card-heading .badge.conditional').count() == (8 if f['grade']=='I' else 4 if f['grade']=='III' else 5)
        assert page.locator('article .card-heading .badge.unknown').count() == (0 if f['grade']=='I' else 3)
        for card in page.locator('article').all():
            assert card.locator('.change-table tbody tr').count() > 0
            assert card.locator('.check-list li').count() > 0
            assert card.locator('.main-sources a').count() > 0
            assert card.locator('.audit-details').get_attribute('open') is None
            assert card.locator('.variant').get_attribute('open') is None
            ordinary = card.inner_text()
            assert 'Fact' not in ordinary and 'Interpretation' not in ordinary
            assert '人による最終確認は未実施' not in ordinary
            expected = ('選択した施設基準との関係を、現在の収録資料だけでは確認できていません。' if card.locator('.badge.unknown').first.count()
                else 'この変更は、選択した施設基準に関係します。実際に算定できるかは、')
            assert expected in card.locator('.relation-copy').inner_text()
            card.get_by_text('判定根拠・コード・監査情報を確認する', exact=True).click()
            assert card.locator('.final-review').inner_text() == '専門職による最終確認：未実施'
            assert card.locator('.audit-sources a').count() > 0
            assert card.locator('.audit-claims li').count() == card.locator('.change-table tbody tr').count()
            assert card.locator('[data-facility]').count() == 1
            assert card.locator('[data-facility]').get_attribute('data-facility') == facility
            card.locator('.variant summary').click()
            if f['grade'] != 'I' and card.get_attribute('data-policy') in ('initial','acute','data'):
                assert card.locator('.no-codes').inner_text() == 'この区分へのコード対応は未登録です'
                assert card.locator('.code-list').count() == 0
                assert not any(line.strip() == '-' for line in card.locator('.variant-body').inner_text().splitlines())
            else:
                assert card.locator('.code-list li').count() > 0
                assert '診療行為マスターで確認（Fact／機械抽出）' in card.locator('.variant-body').inner_text()
                assert '本アプリで制度項目と対応付け（Interpretation／手入力）' in card.locator('.variant-body').inner_text()
        page.locator(f'input[value="{facility}"]').uncheck()
        assert page.locator('#run').is_disabled()
        assert page.locator('article').count() == 0
    for checkbox in page.locator('input[name=facility]').all():
        checkbox.check()
    page.locator('#run').click()
    assert page.locator('article').count() == 8
    first = page.locator('article').first
    assert '25点／単位' in first.locator('.change-table').inner_text()
    assert '1～3日目60点・4～14日目25点／単位' in first.locator('.change-table').inner_text()
    assert '#page=573' in first.locator('.main-sources a').first.get_attribute('href')
    # Exercise the real target=_blank link; stub only external content so this
    # UI test does not depend on the ministry network or Edge's PDF viewer.
    href = first.locator('.main-sources a').first.get_attribute('href')
    page.context.route(href.split('#')[0], lambda route: route.fulfill(content_type='text/html', body='<title>Evidence destination</title>'))
    with page.expect_popup() as popup_info:
        first.locator('.main-sources a').first.click()
    popup = popup_info.value
    popup.wait_for_load_state()
    assert popup.url == href
    popup.close()
    page.context.unroute(href.split('#')[0])
    first.get_by_text('判定根拠・コード・監査情報を確認する', exact=True).click()
    for scope, kubun, code in [('cerebrovascular_i','H001','180763870'), ('disuse_i','H001-2','180767070'), ('musculoskeletal_i','H002','180770270')]:
        group = first.locator(f'[data-facility="{scope}"]')
        assert group.get_attribute('open') is None
        group.locator('summary').click()
        assert group.get_by_text(f'R08／{code}／区分番号 {kubun}', exact=True).count() == 1
    page.locator('#excluded').check()
    assert page.locator('article').count() == 9
    assert page.locator('article .card-heading .badge.excluded').count() == 1
    checked = page.locator('input[name=facility]:checked').evaluate_all('(nodes) => nodes.map(node => node.value)')
    for facility in checked: page.locator(f'input[value="{facility}"]').uncheck()
    page.locator('input[value="cerebrovascular_iii"]').check()
    assert page.locator('article[data-policy="plan"] .relation-copy').inner_text() == 'この変更は、選択した施設基準単独では対象になりません。ほかの届出を併せている場合は確認が必要です。'
    assert 'Ⅲは含まれません' in page.locator('article[data-policy="plan"] .relation-note').inner_text()
    page.locator('article[data-policy="plan"] .audit-details summary').first.click()
    page.locator('article[data-policy="plan"] .variant summary').click()
    assert page.locator('article[data-policy="plan"] .no-codes').inner_text() == 'この区分へのコード対応は未登録です'
    # Display-only fixture: exercise the direct wording without adding a policy claim.
    page.evaluate('''() => {
      const item = window.MED_CODE_MAP_IMPACT_DATA.policy_items.find(i => i.id === 'early');
      item.checks = [];
      item.variants.find(v => v.facility_id === 'cerebrovascular_i').relation = 'direct';
    }''')
    page.locator('input[value="cerebrovascular_iii"]').uncheck()
    page.locator('input[value="cerebrovascular_i"]').check()
    assert page.locator('article[data-policy="early"] .badge.direct').count() == 1
    assert page.locator('article[data-policy="early"] .relation-copy').inner_text() == 'この変更は、選択した施設基準に直接関係します。'
    page.locator('#excluded').uncheck()
    page.evaluate('scrollTo(0, 0)')
    page.screenshot(path=str(ROOT/f'work/startup-{mode}-desktop.png'))
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(ROOT/f'work/startup-{mode}-mobile.png'))
    page.locator('#facilities').screenshot(path=str(ROOT/f'work/grades-{mode}-mobile.png'))
    page.locator('#clear').click()
    assert page.locator('article').count() == 0
    assert page.locator('input[name=facility]:checked').count() == 0
    assert page.locator('#run').is_disabled()
    assert not errors, errors
    print(f'{mode}: 9 facilities, revision, enable/disable, single/all filters, 8 items, evidence, scopes, exclusions, reset and layout passed')


def main():
    (ROOT/'work').mkdir(exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://localhost:{server.server_port}/'
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            for mode, url in [('http',base+'impact.html'), ('file',(ROOT/'impact.html').as_uri())]:
                page = browser.new_page(viewport={'width':1280,'height':1000})
                exercise(page, url, mode)
                page.close()
            page = browser.new_page()
            page.goto(base+'index.html')
            page.get_by_role('link',name='施設別の改定影響チェッカー →').click()
            page.wait_for_function('window.ImpactStartup.ready')
            page.close()
            cases = [
                ('missing-data','impact-data.js',None,'impact-data.js'),
                ('missing-app','impact.js',None,'impact.js'),
                ('broken-data','impact-data.js','this is invalid javascript !','impact-data.js'),
                ('broken-app','impact.js','this is invalid javascript !','impact.js'),
                ('invalid-data','impact-data.js','globalThis.MED_CODE_MAP_IMPACT_DATA = {};','形式'),
            ]
            with tempfile.TemporaryDirectory(dir=ROOT/'work') as temp:
                folder = Path(temp)
                for name, filename, content, expected in cases:
                    case = folder/name
                    (case/'assets').mkdir(parents=True)
                    shutil.copy2(ROOT/'impact.html', case/'impact.html')
                    for asset in ('impact.css','impact.js','impact-data.js'):
                        if asset != filename:
                            shutil.copy2(ROOT/'assets'/asset, case/'assets'/asset)
                    if content is not None:
                        (case/'assets'/filename).write_text(content, encoding='utf-8')
                    for mode in ('http','file'):
                        url = base+(case/'impact.html').relative_to(ROOT).as_posix() if mode=='http' else (case/'impact.html').as_uri()
                        page = browser.new_page()
                        page.goto(url)
                        assert page.locator('#startup-help').is_visible()
                        reason = page.locator('#startup-reason').inner_text()
                        assert expected in reason or (mode=='file' and name.startswith('broken-') and 'JavaScriptの実行に失敗' in reason), reason
                        assert '読み込めません' in page.locator('#facilities').inner_text()
                        assert '読み込めません' in page.locator('#comparison').inner_text()
                        assert 'http://localhost' in page.locator('#startup-help').inner_text()
                        assert 'ダブルクリック' in page.locator('#startup-help').inner_text()
                        assert page.locator('#run').is_disabled()
                        if name=='missing-app' and mode=='file':
                            page.screenshot(path=str(ROOT/'work/startup-file-error.png'), full_page=True)
                        page.close()
                        print(f'{mode}: {name} visible error passed')
            for url in (base+'impact.html', (ROOT/'impact.html').as_uri()):
                page = browser.new_page(java_script_enabled=False)
                page.goto(url)
                assert page.locator('#startup-help').is_visible()
                assert 'JavaScript' in page.locator('#startup-help').inner_text()
                assert page.locator('#facilities').inner_text()
                assert page.locator('#comparison').inner_text()
                page.close()
            browser.close()
            print('All browser checks passed; HTTP/file success, 10 failure scenarios, JavaScript-disabled guidance.')
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
