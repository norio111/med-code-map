-- =====================================================================
-- 疑義解釈（厚労省「疑義解釈検索ツール」由来）
-- =====================================================================
-- 出所: 厚生労働省「診療報酬関連情報」ページ掲載の疑義解釈検索ツール
--       https://www.mhlw.go.jp/content/12400000/Ver.1.1.4.xlsm
--       （ファイル名の Ver 番号が版管理を兼ねる。表紙シートの更新履歴に
--         「Ver1.1.4. 令和８年度診療報酬改定の疑義解釈（その12）を追加」と
--         記載があり、Ver 更新 = 疑義解釈1回分の追加 に対応する）
--
-- 取込元シート: 「管理用」（問答1件=1行で構造化済み）
--   ※「検索」シートはVBAマクロ実行後の結果表示用テンプレートで中身は空。
--     自動処理では「管理用」を直接読むこと。
--
-- !! 注意 !! 本ツールは厚労省自身が「参考」と位置づけている補助ツール。
--   ・分類（医科/歯科等）は「参考です」と明記されている
--   ・図表は収録されていない
--   ・正確な内容は該当の事務連絡PDFを確認すること
--   → verified 相当の扱いはせず、一次資料(PDF)との照合は別途必要。
-- =====================================================================

-- ---------------------------------------------------------------------
-- 取込元ファイルの版管理（Ver番号監視による差分検知に使う）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gigi_source (
    ver                TEXT PRIMARY KEY,   -- 'Ver.1.1.4'（ファイル名由来）
    sha256             TEXT,               -- ファイルハッシュ（更新検知用）
    fetched_at         TEXT,               -- 取得日時 ISO8601
    imported_at        TEXT,               -- DB投入日時 ISO8601
    row_count          INTEGER,            -- 管理用シートのデータ行数
    latest_issued_date TEXT,               -- 収録されている最新の発出年月日
    latest_doc_title   TEXT,               -- 同上の件名（「その12」等の確認用）
    update_note        TEXT                -- 表紙シートの更新履歴テキスト
);

-- ---------------------------------------------------------------------
-- 疑義解釈 本体（問答1件 = 1レコード）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gigi_kaishaku (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_ver    TEXT NOT NULL,           -- どの版から取り込んだか
    src_no        INTEGER NOT NULL,        -- ツールの No. 列（版内で一意）

    -- 改定との紐付け -------------------------------------------------
    -- revision_code は med-code-map の revision テーブルと同じ表記(R08等)。
    -- ただし柔整/あはき/治療用装具は療養費であり診療報酬改定に紐づかない
    -- ため NULL になる（実データで694件、これは欠損ではなく仕様）。
    revision_code TEXT,                    -- 'H18'〜'R08' / NULL
    kaitei_label  TEXT,                    -- 原文「令和8年度診療報酬改定」等

    -- 発出元文書 -----------------------------------------------------
    issued_date   TEXT NOT NULL,           -- 'YYYY-MM-DD'
    doc_title     TEXT NOT NULL,           -- 件名 原文のまま
    doc_series    TEXT,                    -- 系列名（正規化）
                                           --   'main'      = 疑義解釈資料の送付について
                                           --   'jusei'     = 柔道整復施術療養費
                                           --   'ahaki'     = はり・きゅう・あん摩
                                           --   'soug'      = 治療用装具
                                           --   'beia'      = ベースアップ評価料
                                           --   'other'
    sono_no       INTEGER,                 -- 「その◯」を半角整数化。無ければNULL
                                           -- !! 原文は全角/半角が混在する
                                           --    （「その2)」と「その２)」が別文字列）
                                           --    ので必ずこの正規化列で絞ること

    -- 分類 -----------------------------------------------------------
    bunrui        TEXT NOT NULL,           -- 医科/歯科/調剤/訪看/ＤＰＣ/柔整/
                                           -- あはき/材料/長収品/ベア評価料等/
                                           -- 不妊/治療用装具/看護職員の処遇改善/
                                           -- 費用請求/掲載/医科・歯科/その他
                                           -- ※厚労省が「参考」と明記している値

    -- 問番号 ---------------------------------------------------------
    -- 原文は int と str が混在（6225件 / 1404件）。
    -- str は「１．初再診料1」のような節見出し付きや「5-1」の階層番号。
    -- 原文を toi_no_raw に保持し、純粋な数値のときだけ toi_no_num を埋める。
    toi_no_raw    TEXT NOT NULL,
    toi_no_num    INTEGER,

    -- 本文 -----------------------------------------------------------
    question      TEXT NOT NULL,
    answer        TEXT,

    -- 状態 -----------------------------------------------------------
    -- 原文は該当行のみ文字列 '廃止済み' が入る形式。0/1 に正規化。
    is_haishi     INTEGER NOT NULL DEFAULT 0,

    imported_at   TEXT NOT NULL,

    UNIQUE (source_ver, src_no)
);

CREATE INDEX IF NOT EXISTS idx_gigi_bunrui   ON gigi_kaishaku (bunrui);
CREATE INDEX IF NOT EXISTS idx_gigi_revision ON gigi_kaishaku (revision_code);
CREATE INDEX IF NOT EXISTS idx_gigi_issued   ON gigi_kaishaku (issued_date);
CREATE INDEX IF NOT EXISTS idx_gigi_series   ON gigi_kaishaku (doc_series, sono_no);

-- ---------------------------------------------------------------------
-- 全文検索（FTS5）
-- 質問・回答からキーワードで引くため。元ツールのマクロ検索の代替。
-- ---------------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS gigi_fts USING fts5 (
    question,
    answer,
    content = 'gigi_kaishaku',
    content_rowid = 'id',
    tokenize = 'trigram'
);
