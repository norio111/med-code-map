# med-code-map

日本のレセプト電算マスターを、区分番号・レセ電コード・ICD-10などの異なる軸を混同せずに保持できるか検証したSQLite PoCです。理学療法領域を入口に、公式配布ファイルの取込、対応関係のモデル化、検証クエリ、観察結果の可視化までを一つのケーススタディとしてまとめています。

## このPoCで扱った問い

- 点数表区分番号（`H001`など）と9桁の診療行為コードを、どう分離して保持するか
- 区分番号とコードの対応が改定で変わることを、どこに表現するか
- 施設基準のOR／AND構造を、算定可否の問い合わせに使える形で保持できるか
- 傷病名コードからICD-10へ写像したとき、どの粒度が失われるか
- 廃止病名と現行病名の移行関係を、欠損を埋めずにどう保存するか

## 見どころ

- `code_item`、`kubun`、`code_kubun_map`を分け、コード体系と対応関係を別テーブルにした
- 施設基準10枠を、グループ内OR・グループ間ANDとして保持した
- 元の文字列、手入力名称、検証状態を区別した
- 既知スナップショットでは期待件数を検証し、不一致時はDBを完成扱いにしない
- 集計上の観測と、設計理由についての仮説を分離した

可視化した読み物は [`index.html`](index.html) の「レセプト電算マスター図鑑」です。GitHub Pagesを有効にすると、そのまま静的サイトとして表示できます。

## 重要な監査結果

公開版を作る際、公式資料との再照合で旧版の誤りを2点修正しました。

1. `s_20260501.csv`の10,192件は令和8年度版ではなく、令和6年度版（2026年5月31日まで適用）のスナップショットでした。
2. 傷病名マスターの項番22は「収載年月日」、項番23が「変更年月日」です。旧コードは項番22を変更年月日としていました。

修正根拠と未解決事項は [`docs/audit-log.md`](docs/audit-log.md) と [`docs/evidence-map.md`](docs/evidence-map.md) に残しています。

## ディレクトリ構成

```text
med-code-map/
├─ README.md
├─ index.html                 レセプト電算マスター図鑑
├─ src/
│  ├─ load_master.py         医科診療行為マスター取込
│  ├─ load_disease.py        傷病名・移行対応取込
│  └─ hash_sources.py        入力ファイルのSHA-256記録
├─ sql/
│  ├─ schema.sql
│  └─ queries.sql
├─ docs/
│  ├─ design-notes.md
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

既定では、データ規格コード28の172件だけを取り込みます。全件を対象にする場合は`--all`を付け、`--expected-selected-rows`も全件数へ変更します。

### 2. 同じDBへ傷病名と移行関係を追加する

```powershell
py src/load_disease.py `
  data/private/b_20260601.txt `
  data/private/ikou_20260601.txt `
  work/med-code-map.db
```

既知版と異なるデータを試す場合だけ`--skip-known-profile-checks`を使用します。このオプションは列の意味を保証するものではありません。

### 3. 検証クエリを実行する

`sql/queries.sql`には、区分別件数、上限値分布、施設基準の条件充足などの例を収録しています。冒頭の自施設データは架空値です。

## テスト

テストは架空の最小データを生成するため、公式マスターを必要としません。

```powershell
py -m unittest discover -s tests -v
```

## データの扱い

公式配布ファイル、取得したPDF、生成DBはGit管理しません。公開リポジトリにはコード、スキーマ、出典、検証方法だけを置きます。入力ファイルの同一性は`hash_sources.py`で記録できます。

```powershell
py src/hash_sources.py data/private --output work/source-manifest.csv
```

## 現在の射程

このPoCは、指定したスナップショットを一つのDBへ取り込むところまでです。同一コードの複数時点を併存させる履歴モデル、告示・通知との完全な接続、医療機関の算定可否保証は対象外です。詳細は [`docs/limitations.md`](docs/limitations.md) を参照してください。

## 一次資料

- [厚生労働省 診療報酬情報提供サービス：ファイルダウンロード](https://shinryohoshu.mhlw.go.jp/shinryohoshu/downloadMenu/)
- [厚生労働省 診療報酬情報提供サービス：傷病名・修飾語マスター](https://shinryohoshu.mhlw.go.jp/shinryohoshu/standardMenu/doStandardMasterBz)
- [社会保険診療報酬支払基金：基本マスター](https://www.ssk.or.jp/smph/seikyushiharai/tensuhyo/kihonmasta/index.html)
- [令和8年度版マスターファイル仕様説明書（ファイルレイアウト）](https://shinryohoshu.mhlw.go.jp/shinryohoshu/file/spec/R08rec3.pdf)

## 免責

学習・検証用のPoCです。診療報酬請求、算定可否判定、患者情報の処理には使用できません。制度・マスターは更新されるため、実利用時は必ず最新の公式資料を確認してください。

公開前は [`docs/publishing-checklist.md`](docs/publishing-checklist.md) を確認してください。ライセンスは利用条件を本人が決めてから追加するため、現時点では同梱していません。
