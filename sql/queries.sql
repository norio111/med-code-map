-- デモ用の届出（架空施設が脳血管Ⅰのみ届出している想定）
-- 実データへ適用する前に、この2行を削除または自施設の値へ置き換える。
DELETE FROM my_facility;
INSERT INTO my_facility VALUES ('732','2024-06-01');

-- [1] 区分番号ごとの件数
SELECT m.kubun_no, k.name, COUNT(*) AS codes
FROM code_kubun_map m JOIN kubun k
  ON k.kubun_no=m.kubun_no AND k.revision_id=m.revision_id
GROUP BY m.kubun_no ORDER BY codes DESC;

-- [2] 患者1人あたりの1日上限（きざみ上限値）の分布
SELECT upper_value AS 上限単位, error_handling AS ｴﾗｰ処理, COUNT(*) AS n
FROM code_quantity_rule GROUP BY 1,2 ORDER BY n DESC;

-- [3] CNF判定：施設基準が不要、または全グループを満たすコード
WITH need AS (
  SELECT cs_id, code, revision_id, COUNT(DISTINCT group_no) AS groups_needed
  FROM code_facility_req GROUP BY 1,2,3),
have AS (
  SELECT r.cs_id, r.code, r.revision_id, COUNT(DISTINCT r.group_no) AS groups_met
  FROM code_facility_req r JOIN my_facility f ON f.kijun_code=r.kijun_code
  GROUP BY 1,2,3)
SELECT COUNT(*) AS 施設基準条件を満たすコード数
FROM code_item i
LEFT JOIN need n ON n.cs_id=i.cs_id AND n.code=i.code
LEFT JOIN have h ON h.cs_id=i.cs_id AND h.code=i.code
WHERE n.groups_needed IS NULL
   OR COALESCE(h.groups_met,0) = n.groups_needed;

-- [4] 同上、中身を数件（施設基準不要のコードも含む）
WITH need AS (
  SELECT cs_id, code, revision_id, COUNT(DISTINCT group_no) AS gn
  FROM code_facility_req GROUP BY 1,2,3),
have AS (
  SELECT r.cs_id, r.code, r.revision_id, COUNT(DISTINCT r.group_no) AS gm
  FROM code_facility_req r JOIN my_facility f ON f.kijun_code=r.kijun_code
  GROUP BY 1,2,3)
SELECT i.code, substr(i.display_short,1,40) AS 名称, i.point AS 点数,
       q.upper_value AS 上限単位
FROM code_item i
LEFT JOIN need n ON n.cs_id=i.cs_id AND n.code=i.code
LEFT JOIN have h ON h.cs_id=i.cs_id AND h.code=i.code
LEFT JOIN code_quantity_rule q ON q.cs_id=i.cs_id AND q.code=i.code
WHERE n.gn IS NULL OR COALESCE(h.gm,0) = n.gn
LIMIT 6;

-- [5] 逆：届出が足りず算定できないコード（不足している基準つき）
WITH need AS (
  SELECT cs_id, code, revision_id, COUNT(DISTINCT group_no) AS gn
  FROM code_facility_req GROUP BY 1,2,3),
have AS (
  SELECT r.cs_id, r.code, r.revision_id, COUNT(DISTINCT r.group_no) AS gm
  FROM code_facility_req r JOIN my_facility f ON f.kijun_code=r.kijun_code
  GROUP BY 1,2,3)
SELECT COUNT(*) AS 算定不可コード数 FROM need n
LEFT JOIN have h USING (cs_id, code, revision_id)
WHERE COALESCE(h.gm,0) < n.gn;

-- [6] グループ②以降を使う＝AND条件を持つコードがあるか
SELECT group_no, COUNT(DISTINCT code) AS codes FROM code_facility_req
GROUP BY group_no;

-- [7] 施設基準を2つ以上OR で並べているコード（グループ①内の複数枠）
SELECT i.code, substr(i.display_short,1,34) AS 名称,
       GROUP_CONCAT(r.kijun_code,' or ') AS いずれか
FROM code_facility_req r JOIN code_item i ON i.cs_id=r.cs_id AND i.code=r.code
WHERE r.group_no=1 GROUP BY r.code HAVING COUNT(*)>=3 LIMIT 5;
