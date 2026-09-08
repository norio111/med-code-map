-- =====================================================================
-- med-code-map : 対応表スキーマ v0.2
--   レセプト電算処理システムの医科診療行為・傷病名マスターを、
--   区分番号や ICD-10 と混同せず別軸で保持するための PoC。
--
--   現段階は単一スナップショットの取込を対象とする。同じコードの時系列差分を
--   1 DB に併存させる版管理スキーマは未実装（docs/limitations.md 参照）。
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- REVISION : 診療報酬改定
-- ---------------------------------------------------------------------
CREATE TABLE revision (
    revision_id     TEXT PRIMARY KEY,       -- 'R08'
    label           TEXT NOT NULL,
    effective_from  DATE NOT NULL,
    effective_to    DATE
);

-- ---------------------------------------------------------------------
-- CODESYSTEM : コード体系
-- ---------------------------------------------------------------------
CREATE TABLE codesystem (
    cs_id           INTEGER PRIMARY KEY,
    master_type     TEXT,                   -- 項番2 マスター種別 'S'
    name            TEXT NOT NULL,
    fhir_uri        TEXT UNIQUE,
    authority       TEXT,
    code_format     TEXT
);

-- ---------------------------------------------------------------------
-- CODE_ITEM : レセ電コード（請求データに載る値）
--   複合PK。コード値はコードシステム内でのみ一意。
-- ---------------------------------------------------------------------
CREATE TABLE code_item (
    cs_id           INTEGER NOT NULL REFERENCES codesystem(cs_id),
    code            TEXT    NOT NULL,       -- 項番3  診療行為コード（9桁）
    display_short   TEXT    NOT NULL,       -- 項番5  省略漢字名称
    display_full    TEXT,                   -- 項番113 基本漢字名称
    unit_code       TEXT,                   -- 項番8  データ規格コード（28=単位）
    unit_name       TEXT,                   -- 項番10 データ規格名
    point_kind      TEXT,                   -- 項番11 点数識別（3=点数プラス）
    point           REAL,                   -- 項番12 新又は現点数
    kokuji_kind     TEXT,                   -- 項番68 告示等識別区分(1)
    changed_on      TEXT,                   -- 項番87 変更年月日（YYYYMMDD、原文保持）
    abolished_on    TEXT,                   -- 項番88 廃止年月日（99999999=現行）
    PRIMARY KEY (cs_id, code)
);

-- ---------------------------------------------------------------------
-- CODE_QUANTITY_RULE : きざみ値による点数計算（項番30〜35）
--   リハの「1日◯単位まで」はここに入る。患者1人あたりの上限。
--   従事者1人あたりの上限（18単位/日・108単位/週）はマスターに無い。
-- ---------------------------------------------------------------------
CREATE TABLE code_quantity_rule (
    cs_id           INTEGER NOT NULL,
    code            TEXT    NOT NULL,
    lower_value     INTEGER,                -- 項番31 下限値
    upper_value     INTEGER,                -- 項番32 上限値
    step_value      INTEGER,                -- 項番33 きざみ値
    step_point      REAL,                   -- 項番34 きざみ点数
    error_handling  TEXT,                   -- 項番35 上下限エラー処理 0-3
    PRIMARY KEY (cs_id, code),
    FOREIGN KEY (cs_id, code) REFERENCES code_item(cs_id, code) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------
-- KUBUN : 点数表の区分番号（H001 など）
--   改定ごとに存在するので (kubun_no, revision_id) が識別子。
-- ---------------------------------------------------------------------
CREATE TABLE kubun (
    kubun_no        TEXT NOT NULL,
    revision_id     TEXT NOT NULL REFERENCES revision(revision_id),
    name            TEXT,                   -- マスターに無い。点数表から手入力
    chapter         TEXT,                   -- 項番90 章
    part            TEXT,                   -- 項番91 部
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0,1)),
                                             -- 1=原典で確認済み
    PRIMARY KEY (kubun_no, revision_id)
);

-- ---------------------------------------------------------------------
-- CODE_KUBUN_MAP : 区分番号 × コード（改定依存）
--   マスターでは項番85（英字部）と項番92（数字部）に分解されている。
--   ここで再結合し、改定という軸を明示的に持たせる。
-- ---------------------------------------------------------------------
CREATE TABLE code_kubun_map (
    cs_id           INTEGER NOT NULL,
    code            TEXT    NOT NULL,
    revision_id     TEXT    NOT NULL,
    kubun_no        TEXT    NOT NULL,
    item_no         TEXT,                   -- 項番94 項番
    kubun_text      TEXT,                   -- 項番117 点数表区分番号（原文）
    PRIMARY KEY (cs_id, code, revision_id),
    FOREIGN KEY (cs_id, code)            REFERENCES code_item(cs_id, code) ON DELETE CASCADE,
    FOREIGN KEY (kubun_no, revision_id)  REFERENCES kubun(kubun_no, revision_id)
);

-- ---------------------------------------------------------------------
-- FACILITY_KIJUN : 施設基準コード（別紙7-8）
-- ---------------------------------------------------------------------
CREATE TABLE facility_kijun (
    kijun_code      TEXT PRIMARY KEY,
    name            TEXT,
    is_meyose       INTEGER NOT NULL DEFAULT 0 CHECK (is_meyose IN (0,1))
                                             -- 名寄せコード（8000番台）か
);

-- ---------------------------------------------------------------------
-- CODE_FACILITY_REQ : 施設基準の要求（項番72〜81）
--   ここが本体。10枠は3グループに分かれ、
--     グループ内 = OR（いずれか1つ満たせばよい）
--     グループ間 = AND（すべて満たす必要がある）
--   という連言標準形（CNF）。枠の位置に意味があるので slot_no を保つ。
--     group 1 = 項番72〜77 / group 2 = 項番78〜80 / group 3 = 項番81
-- ---------------------------------------------------------------------
CREATE TABLE code_facility_req (
    cs_id           INTEGER NOT NULL,
    code            TEXT    NOT NULL,
    revision_id     TEXT    NOT NULL,
    group_no        INTEGER NOT NULL CHECK (group_no IN (1,2,3)),
    slot_no         INTEGER NOT NULL,       -- 項番72=1 … 項番81=10
    kijun_code      TEXT    NOT NULL REFERENCES facility_kijun(kijun_code),
    PRIMARY KEY (cs_id, code, revision_id, slot_no),
    FOREIGN KEY (cs_id, code) REFERENCES code_item(cs_id, code) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------
-- MY_FACILITY : 自施設が届出している施設基準（算定可否判定用）
-- ---------------------------------------------------------------------
CREATE TABLE my_facility (
    kijun_code      TEXT PRIMARY KEY REFERENCES facility_kijun(kijun_code),
    notified_on     DATE
);

CREATE INDEX idx_map_kubun  ON code_kubun_map(kubun_no, revision_id);
CREATE INDEX idx_req_kijun  ON code_facility_req(kijun_code);
CREATE INDEX idx_item_short ON code_item(display_short);

-- ---------------------------------------------------------------------
-- DISEASE : 傷病名マスター（Bマスター）
--   b_20260601.txt から読み込む。項番は厚生労働省「令和8年度版
--   マスターファイル仕様説明書 ファイルレイアウト」p.219-220 と照合済み。
--   v0.1 で変更年月日としていた項番22は収載年月日であり、項番23へ訂正した。
-- ---------------------------------------------------------------------
CREATE TABLE disease (
    disease_code        TEXT PRIMARY KEY,   -- 項番3  傷病名コード
    name                 TEXT NOT NULL,     -- 項番6  基本傷病名基本名称
    icd10_code1           TEXT,             -- 項番16 ICD-10-1（2013）
    icd10_code2           TEXT,             -- 項番17 ICD-10-2（2013）
    single_use_prohibited INTEGER NOT NULL DEFAULT 0
        CHECK (single_use_prohibited IN (0,1)), -- 項番19 00→0 / 01→1
    excluded_from_claim   INTEGER NOT NULL DEFAULT 0
        CHECK (excluded_from_claim IN (0,1)),   -- 項番20 0/1
    listed_on             TEXT,             -- 項番22 収載年月日（YYYYMMDD）
    changed_on            TEXT,             -- 項番23 変更年月日（YYYYMMDD）
    abolished_on          TEXT              -- 項番24 廃止年月日（YYYYMMDD）
);

-- ---------------------------------------------------------------------
-- DISEASE_MIGRATION : 傷病名移行マスター
--   ikou_20260601.txt から読み込む。項番5（新コード）は移行先なしの場合に
--   NULL。外部キーは NULL を許すため、非 NULL の移行先だけ参照整合性を検証する。
--   移行対応テーブル固有の7列レイアウトは、取得元資料との再照合を継続する。
-- ---------------------------------------------------------------------
CREATE TABLE disease_migration (
    old_code    TEXT PRIMARY KEY,           -- 項番2 旧傷病名コード
    old_name    TEXT NOT NULL,              -- 項番3 旧傷病名称
    new_code    TEXT REFERENCES disease(disease_code),
                                             -- 項番5 新傷病名コード（移行先なしはNULL）
    new_name    TEXT                        -- 項番7 新傷病名称
);

CREATE INDEX idx_disease_icd1     ON disease(icd10_code1);
CREATE INDEX idx_disease_icd2     ON disease(icd10_code2);
CREATE INDEX idx_migration_newcode ON disease_migration(new_code);
