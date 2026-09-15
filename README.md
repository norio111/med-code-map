# med-code-map

日本のレセプト電算マスターを、区分番号・レセ電コード・ICD-10などの異なる軸を混同せずに保持できるか検証したSQLite PoCです。理学療法領域を入口に、公式配布ファイルの取込、対応関係のモデル化、検証クエリ、観察結果の可視化までを一つのケーススタディとしてまとめています。

## このPoCで扱った問い

- 点数表区分番号（`H001`など）と9桁の診療行為コードを、どう分離して保持するか
- 区分番号とコードの対応が改定で変わることを、どこに表現するか
- 同じコードの複数の改定を、上書きせずに1つのDBへ併存させられるか
- 施設基準のOR／AND構造を、算定可否の問い合わせに使える形で保持できるか
- 傷病名コードからICD-10へ写像したとき、どの粒度が失われるか
- 廃止病名と現行病名の移行関係を、欠損を埋めずにどう保存するか

## 見どころ

- `code_item`、`kubun`、`code_kubun_map`を分け、コード体系と対応関係を別テーブルにした
- 施設基準10枠を、グループ内OR・グループ間ANDとして保持した
- 元の文字列、手入力名称、検証状態を区別した
- 既知スナップショットでは期待件数を検証し、不一致時はDBを完成扱いにしない
- 点数やきざみ規則を改定に属させ、令和6年度版と令和8年度版を同じDBで比較できるようにした
- 集計上の観測と、設計理由についての仮説を分離した

可視化した読み物は「レセプト電算マスター図鑑」です。公開版は <https://norio111.github.io/med-code-map/> で読めます（ソースは [`index.html`](index.html)）。

## 施設別の改定影響チェッカー（MVP）

[`impact.html`](impact.html)を追加しました。脳血管・廃用・運動器のⅠ・Ⅱ・Ⅲ（9区分）を選択できます。収録は8制度項目。初期・急性期・データ提出加算のⅡ・Ⅲは要確認、総合計画評価料はⅢ単独では対象外です。令和6年度→令和8年度の比較で、判定は算定可否を保証しません。旧「リ減」と新「特定患者」は別項目として扱います。

主張ごとの根拠ページ、年度別内容、点数・期間・コード構成、実務上の確認事項、選択区分別のコード明細を表示します。手入力した制度解釈と、マスターから機械抽出した属性を区別し、人の最終確認は未実施と明記しています。

HTML・CSS・JavaScriptと生成済みデータのみで動くため、GitHub Pagesの静的構成を維持します。起動方法は2通りあります。

1. **直接表示**：フォルダ全体を展開し、`impact.html`をダブルクリックします（`file:///`）。`assets/impact-data.js`と`assets/impact.js`を含むフォルダ構成を保ってください。
2. **HTTP経由**：このフォルダで次を実行し、`http://localhost:8000/impact.html`を開きます。終了はCtrl+C。

```powershell
py -m http.server 8000 --bind 127.0.0.1
```

施設基準3件と比較改定が表示された後、施設基準を1つ以上選ぶと実行ボタンが有効になります。閲覧にSQLiteや公式CSVは不要です。

`file:///`でJSONの`fetch()`が遮断される不具合を修正し、両起動方法とも生成済みの`assets/impact-data.js`を通常のscriptタグで読み込みます。JavaScriptやデータが欠落・破損した場合は、画面内に原因と復旧・起動方法を表示します。JavaScript無効時もHTMLの案内が残ります。

データモデル・再生成方法・未収録範囲は[`docs/impact-design.md`](docs/impact-design.md)を参照してください。監査用の正本は`data/impact-catalog.json`です。`src/export_impact.py`が既存DBの機械抽出属性を結合し、同じデータから`assets/impact-data.json`と`assets/impact-data.js`を同時生成します。両生成物を手編集しないでください。DBテーブルの追加は行っていません。

## 重要な監査結果

公開版を作る際、公式資料との再照合で旧版の誤りを2点修正しました。

1. `s_20260501.csv`の10,192件は令和8年度版ではなく、令和6年度版（2026年5月31日まで適用）のスナップショットでした。
2. 傷病名マスターの項番22は「収載年月日」、項番23が「変更年月日」です。旧コードは項番22を変更年月日としていました。

1点目の結果として、診療行為が改定前、傷病名が改定後という版の混在が残っていました。2026年6月1日施行の令和8年度版を取り込み、両方を保持して比較できるようスキーマをv0.3へ更新しています。

差分の結果は次のとおりです。集計範囲によって件数が変わるため、両方を併記します。

| | H区分（項番85の英字部が`H`） | 単位系（項番8が`28`） |
|---|---|---|
| 令和6年度版 | 190 | 172 |
| 令和8年度版 | 234 | 210 |
| 両方にあるコード | 110 | 97 |
| 令和6年度版にのみ存在 | 80 | 75 |
| 令和8年度版にのみ存在 | 124 | 113 |
| 同一コードの点数変更 | 1 | 0 |

以下の標準手順は単位系の列を再現します。H区分の列を再現するには`--all`で全件を取り込み、抽出時に項番85の英字部で絞ってください。

その差分を読む過程で、こちらの解釈にも3点の誤りがありました。集計範囲を添えずに件数を書いたこと、同一コードの点数変更が少ないことから「点数が変わっていない」と読んだこと、廃止コードと新設コードの点数一致を対応関係の根拠としたことです。いずれも一次資料との照合で判明し、撤回と修正の経緯を [`docs/revision-diff-R06-R08.md`](docs/revision-diff-R06-R08.md) に残しています。

修正根拠と未解決事項は [`docs/audit-log.md`](docs/audit-log.md) と [`docs/evidence-map.md`](docs/evidence-map.md) に残しています。

## ディレクトリ構成

```text
med-code-map/
├─ README.md
├─ index.html                 レセプト電算マスター図鑑
├─ src/
│  ├─ load_master.py         医科診療行為マスター取込
│  ├─ load_disease.py        傷病名・移行対応取込
│  ├─ load_gigi.py           疑義解釈取り込み
│  └─ hash_sources.py        入力ファイルのSHA-256記録
├─ sql/
│  ├─ schema.sql
│  ├─ queries.sql
│  └─ revision-diff.sql     改定差分（:old / :new を渡す）
├─ docs/
│  ├─ design-notes.md
│  ├─ revision-diff-R06-R08.md  令和6年度版→令和8年度版の差分
│  ├─ data-sources.md
│  ├─ evidence-map.md
│  ├─ limitations.md
│  ├─ audit-log.md
│  └─ publishing-checklist.md
├─ data/
│  └─ README.md
└─ tests/
   └─ test_smoke.py
```

## セットアップ

Python 3.10以降を想定しています。

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

入力データはリポジトリに含めていません。公式サイトから取得し、`data/private/`へ置きます。取得元と対象版は [`docs/data-sources.md`](docs/data-sources.md) を参照してください。

### 1. 医科診療行為マスターを取り込む

このリポジトリで分析した10,192件の`2026-05-01`スナップショットは、令和6年度版です。

```powershell
py src/load_master.py data/private/s_20260501.csv work/med-code-map.db `
  --revision-id R06 `
  --revision-label "令和6年度診療報酬改定" `
  --effective-from 2024-06-01 `
  --effective-to 2026-05-31 `
  --expected-total-rows 10192 `
  --expected-selected-rows 172
```

既定では、データ規格コード28の行だけを取り込みます。全件を対象にする場合は`--all`を付け、`--expected-selected-rows`も全件数へ変更します。

現行版（令和8年度改定、2026年6月1日施行）を同じDBへ追加するには`--append`を使います。

```powershell
py src/load_master.py data/private/s_20260911.csv work/med-code-map.db --append `
  --revision-id R08 `
  --revision-label "令和8年度診療報酬改定" `
  --effective-from 2026-06-01 `
  --expected-total-rows 11833 `
  --expected-selected-rows 210
```

同じ改定IDが既に入っている場合は中止します。追加は既存DBの複製に対して行い、検証が通った場合だけ差し替えるため、途中で失敗しても元のDBは残ります。

2版を取り込むと、改定で何が変わったかを`sql/revision-diff.sql`で引けます。名前付きパラメータ`:old` `:new`へ改定IDを渡して1文ずつ実行してください。

### 2. 同じDBへ傷病名と移行関係を追加する

```powershell
py src/load_disease.py `
  data/private/b_20260601.txt `
  data/private/ikou_20260601.txt `
  work/med-code-map.db
```

既知版と異なるデータを試す場合だけ`--skip-known-profile-checks`を使用します。このオプションは列の意味を保証するものではありません。

## 疑義解釈を同じDBへ追加する

厚労省が公開する「疑義解釈検索ツール」（問答単位で構造化されたExcel）を取り込みます。診療行為・傷病名と異なり、疑義解釈は公表スケジュールが決まっていないため、取得元の更新検知は別リポジトリ（[gigi-ver-watch](https://github.com/norio111/gigi-ver-watch)）が担当し、このリポジトリはダウンロード済みのファイルを受け取って取り込むところまでを担います。

```powershell
py src/load_gigi.py data/private/Ver.1.1.4.xlsm work/med-code-map.db `
  --expected-total-rows 7629
```

引数を省略すると、2026-09-15時点の既知版（Ver.1.1.4、その12まで反映、7,629件）を基準に自動で検証します。未知版を試す場合は`--skip-known-profile-checks`を付けてください。このオプションは列の意味を保証するものではありません。

投入は同一`source_ver`に対して冪等です（再実行すると差し替え）。版が異なれば併存し、過去版は消しません。件名の全角/半角ゆれ（「その2)」「その２)」）や問番号の型混在（int/str）は取込時に正規化し、原文は保持します。柔道整復・あはき・治療用装具は療養費であり診療報酬改定に紐づかないため、`revision_code`はNULLになります（欠損ではなく仕様）。

厚労省は本ツールについて「検索結果はご参考です」「分類は参考です」「図や表については掲載していません」と明記しています。一次資料（事務連絡PDF）の代替ではないため、算定要件の判断に用いる場合は該当PDFを確認してください。

### 3. 検証クエリを実行する

`sql/queries.sql`には、区分別件数、上限値分布、施設基準の条件充足などの例を収録しています。冒頭の自施設データは架空値です。

## テスト

基本テストは架空の最小データと公開JSONで実行できます。`data/private/`に指定の両年度マスターがある場合は全件取込・H区分／単位系の実データ回帰も実行し、ない場合はそのテストだけskipします。

```powershell
py -m unittest discover -s tests -v
node --test tests/impact.test.cjs
```

実ブラウザでの検証（インストール済みMicrosoft Edgeを使用）：

```powershell
py -m pip install -r requirements-browser.txt
py tests/browser_impact.py
```

## データの扱い

公式配布ファイル、取得したPDF、生成DBはGit管理しません。公開リポジトリにはコード、スキーマ、出典、検証方法に加え、チェッカー用の制度注釈と必要範囲のコード属性JSONを置きます。名称・コードはマスターの値を保持し、編集判断は別フィールドにします。入力ファイルの同一性は`hash_sources.py`で記録できます。

```powershell
py src/hash_sources.py data/private --output work/source-manifest.csv
```

## 現在の射程

指定したスナップショットのDB比較に加え、3疾患のⅠ〜Ⅲ（9区分、一部対応は要確認）に関係する制度変更候補を抽出するMVPを実装しています。診療行為は複数の改定を併存できますが、傷病名は単一スナップショットのままです。告示・通知との完全な接続、医療機関の算定可否保証は対象外です。また、2版の集合差だけでは法的な廃止を確定できません。詳細は [`docs/limitations.md`](docs/limitations.md) を参照してください。

## 一次資料

- [厚生労働省 診療報酬情報提供サービス：ファイルダウンロード](https://shinryohoshu.mhlw.go.jp/shinryohoshu/downloadMenu/)
- [厚生労働省 診療報酬情報提供サービス：傷病名・修飾語マスター](https://shinryohoshu.mhlw.go.jp/shinryohoshu/standardMenu/doStandardMasterBz)
- [社会保険診療報酬支払基金：基本マスター](https://www.ssk.or.jp/smph/seikyushiharai/tensuhyo/kihonmasta/index.html)
- [令和8年度版マスターファイル仕様説明書（ファイルレイアウト）](https://shinryohoshu.mhlw.go.jp/shinryohoshu/file/spec/R08rec3.pdf)

## 免責

学習・検証用のPoCです。診療報酬請求、算定可否判定、患者情報の処理には使用できません。制度・マスターは更新されるため、実利用時は必ず最新の公式資料を確認してください。

公開・更新時の確認事項は [`docs/publishing-checklist.md`](docs/publishing-checklist.md) に記録しています。利用条件は検討中のため、現時点ではライセンスを設定していません。
