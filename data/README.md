# Data directory

公式配布ファイルはこのリポジトリに含めません。

`impact-catalog.json`は施設別チェッカーの編集元です。制度項目・主張単位の根拠・明示コード対応を収録しています。必要範囲のマスター属性を付加した公開JSONは`assets/impact-data.json`です。これは全マスターの複製ではありません。生成方法は[`docs/impact-design.md`](../docs/impact-design.md)を参照してください。

ローカルでは`data/private/`を作り、取得したマスターを置いてください。このディレクトリは`.gitignore`の対象です。取得元、版、更新日は[`docs/data-sources.md`](../docs/data-sources.md)に記録します。

公開可能な架空サンプルが必要な場合は、実データの行を匿名化・改変して再配布するのではなく、仕様から独立に生成してください。テストではこの方式を採用しています。
