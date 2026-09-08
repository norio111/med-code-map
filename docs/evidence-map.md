# Evidence Map

確認基準日：2026-09-08

| Claim | Evidence | Source | Source type | Date | Confidence |
|---|---|---|---|---|---|
| 分析した医科診療行為マスターは10,192件 | 配布ページの件数とローカル集計が一致 | 厚生労働省「ファイルダウンロード」 | government primary source | 2026-05-01 | High |
| 10,192件版は令和6年度版である | 配布ページが令和6年度版・2026-05-31まで適用と表示 | 同上 | government primary source | 2026-09-08確認 | High |
| 項番8はデータ規格コード、30-35はきざみ値、72-81は施設基準 | 公式ファイルレイアウトの項目名 | 令和8年度版マスターファイル仕様説明書 ファイルレイアウト p.228-229 | government primary source | 2026-07-31掲載版 | High |
| 傷病名の項番22/23/24は収載/変更/廃止年月日 | 公式ファイルレイアウト | 同資料 p.219-220 | government primary source | 2026-07-31掲載版 | High |
| 傷病名27,684件中、ICD-10コード2ありは1,482件 | ローカル集計。期待件数チェックで再現 | `load_disease.py` | reproducible local analysis | 2026-09-03 | High for this snapshot |
| 移行8,032件中6,037件は現行病名に結合できる | ローカルJOIN集計 | `load_disease.py` | reproducible local analysis | 2026-09-03 | High for this snapshot |
| 非NULLの移行先が現行マスターに存在する | 外部キー制約と取込成功で検査 | `schema.sql` / `load_disease.py` | reproducible local analysis | 2026-09-08 | High when loader succeeds |
| ICD-10から傷病名コードを一意に逆引きできない | 複数傷病名が同一ICD-10へ対応 | ローカル集計 | reproducible local analysis | 2026-09-03 | High for non-invertibility |
| 病名と診療行為で廃止表現が異なる理由 | 配布ファイルには理由が記載されていない | － | inference | 2026-09-08 | Low |
| 7000番台が後発語の受け皿になった | コード帯と分類の偏りからの推測 | 修飾語マスター集計 | inference | 2026-09-03 | Low |
| 評価尺度・ICFとの直接対応がない | 分析した5ファイルには対応列を確認できない | ローカル列調査 | bounded observation | 2026-09-03 | Medium |

`Confidence`は主張の一般的真理ではなく、記載した証拠がその主張をどの程度支えるかを表します。

