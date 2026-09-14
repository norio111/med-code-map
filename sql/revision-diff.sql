-- =====================================================================
-- med-code-map : 改定差分クエリ
--   :old / :new へ revision_id を渡して 1 文ずつ実行する。
--   名前付きパラメータを使うため executescript では動かない。
--
--   前提：1つのDBへ2つ以上の改定を取り込んでいること。
--     py src/load_master.py <旧マスター> work/map.db --revision-id R06 ...
--     py src/load_master.py <新マスター> work/map.db --append --revision-id R08 ...
-- =====================================================================

-- [D1] DBに入っている改定と件数
SELECT r.revision_id, r.label, r.effective_from, r.effective_to,
       COUNT(i.code) AS codes
FROM revision r LEFT JOIN code_item i ON i.revision_id=r.revision_id
GROUP BY r.revision_id ORDER BY r.effective_from;

-- [D2] 新設：新しい改定にあり、古い改定に無いコード
SELECT n.code, substr(n.display_short,1,40) AS 名称, n.point AS 点数,
       m.kubun_no AS 区分番号
FROM code_item n
LEFT JOIN code_item o
  ON o.cs_id=n.cs_id AND o.code=n.code AND o.revision_id=:old
LEFT JOIN code_kubun_map m
  ON m.cs_id=n.cs_id AND m.code=n.code AND m.revision_id=n.revision_id
WHERE n.revision_id=:new AND o.code IS NULL
ORDER BY m.kubun_no, n.code;

-- [D3] 消滅：古い改定にあり、新しい改定に無いコード
--   配布マスターが現行有効分のみの場合、廃止されたコードはここに現れる。
--   ただし「廃止」と「配布対象から外れた」を、この2版の比較だけでは区別できない。
SELECT o.code, substr(o.display_short,1,40) AS 名称, o.point AS 点数,
       m.kubun_no AS 区分番号
FROM code_item o
LEFT JOIN code_item n
  ON n.cs_id=o.cs_id AND n.code=o.code AND n.revision_id=:new
LEFT JOIN code_kubun_map m
  ON m.cs_id=o.cs_id AND m.code=o.code AND m.revision_id=o.revision_id
WHERE o.revision_id=:old AND n.code IS NULL
ORDER BY m.kubun_no, o.code;

-- [D4] 点数改定：両方にあり、点数が変わったコード
SELECT o.code, substr(o.display_short,1,34) AS 名称,
       o.point AS 旧点数, n.point AS 新点数,
       ROUND(n.point - o.point, 2) AS 差
FROM code_item o
JOIN code_item n
  ON n.cs_id=o.cs_id AND n.code=o.code AND n.revision_id=:new
WHERE o.revision_id=:old AND o.point IS NOT NULL AND n.point IS NOT NULL
  AND o.point <> n.point
ORDER BY ABS(n.point - o.point) DESC;

-- [D5] 名称変更：両方にあり、省略漢字名称が変わったコード
SELECT o.code, o.display_short AS 旧名称, n.display_short AS 新名称
FROM code_item o
JOIN code_item n
  ON n.cs_id=o.cs_id AND n.code=o.code AND n.revision_id=:new
WHERE o.revision_id=:old AND o.display_short <> n.display_short
ORDER BY o.code;

-- [D6] 区分番号ごとの増減
--   FULL JOIN を使わず、両版の区分番号を UNION してから左結合する。
WITH kubun_all AS (
  SELECT kubun_no FROM code_kubun_map WHERE revision_id=:old
  UNION
  SELECT kubun_no FROM code_kubun_map WHERE revision_id=:new
),
old_n AS (SELECT kubun_no, COUNT(*) AS n FROM code_kubun_map
          WHERE revision_id=:old GROUP BY kubun_no),
new_n AS (SELECT kubun_no, COUNT(*) AS n FROM code_kubun_map
          WHERE revision_id=:new GROUP BY kubun_no)
SELECT a.kubun_no AS 区分番号,
       COALESCE(o.n,0) AS 旧, COALESCE(w.n,0) AS 新,
       COALESCE(w.n,0) - COALESCE(o.n,0) AS 増減
FROM kubun_all a
LEFT JOIN old_n o ON o.kubun_no=a.kubun_no
LEFT JOIN new_n w ON w.kubun_no=a.kubun_no
ORDER BY 1;

-- [D7] 1日上限単位（きざみ上限値）が変わったコード
SELECT q_old.code, substr(i.display_short,1,34) AS 名称,
       q_old.upper_value AS 旧上限, q_new.upper_value AS 新上限
FROM code_quantity_rule q_old
JOIN code_quantity_rule q_new
  ON q_new.cs_id=q_old.cs_id AND q_new.code=q_old.code
 AND q_new.revision_id=:new
JOIN code_item i
  ON i.cs_id=q_new.cs_id AND i.code=q_new.code AND i.revision_id=q_new.revision_id
WHERE q_old.revision_id=:old AND q_old.upper_value <> q_new.upper_value
ORDER BY q_old.code;

-- [D8] 施設基準の要求が変わったコード（要求する基準コードの集合で比較）
WITH req AS (
  SELECT revision_id, code,
         GROUP_CONCAT(kijun_code, '+') AS kijun_set
  FROM (SELECT revision_id, code, kijun_code FROM code_facility_req
        ORDER BY revision_id, code, group_no, slot_no)
  GROUP BY revision_id, code
)
SELECT o.code, substr(i.display_short,1,30) AS 名称,
       o.kijun_set AS 旧要求, n.kijun_set AS 新要求
FROM req o
JOIN req n ON n.code=o.code AND n.revision_id=:new
JOIN code_item i ON i.code=n.code AND i.revision_id=n.revision_id
WHERE o.revision_id=:old AND o.kijun_set <> n.kijun_set
ORDER BY o.code;
