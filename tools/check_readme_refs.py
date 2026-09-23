#!/usr/bin/env python3
"""
README.md が参照しているファイルパスを抽出し、実際のリポジトリと突き合わせる。

「欠落・名称違い・生成物の扱い」を一覧にするための道具。med-code-mapの
load_gigi.py / load_master.py と同じ発想 --- 期待（READMEの記述）と実測
（ディスク上・gitの追跡状態）を機械的に照合し、人の目視漏れを減らす。

使い方（リポジトリのルートで実行）:
    py tools/check_readme_refs.py
    py tools/check_readme_refs.py --readme README.md
    py tools/check_readme_refs.py --json > report.json

判定:
    OK        : ファイルが存在し、gitに追跡されている（＝pushすれば公開される）
    UNTRACKED : ファイルは存在するが、gitに追跡されていない
                （新規ファイルでまだ git add していないか、.gitignore対象）
    IGNORED   : .gitignore の対象になっている（意図的な生成物/入力データか要確認）
    MISSING   : ファイルがディスク上に存在しない（README記述と実態が食い違い）

このスクリプト自体は判断をしない。「公開すべきか」はscopeの列で
人間が決めること。デフォルトでは全ファイルをscope=(未定)として出力する。
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

# README中でファイルパスとして拾う対象の拡張子。
# 拾いすぎ（URLの一部等）を避けるため、明示的なリストにしている。
PATH_EXTENSIONS = (
    ".py", ".sql", ".md", ".html", ".css", ".js", ".json",
    ".txt", ".cjs", ".db", ".csv", ".yml", ".yaml",
)

# 誤検出しやすいもの（URLの一部、バージョン番号等）を除外する
EXCLUDE_PATTERNS = [
    re.compile(r"^https?://"),
    re.compile(r"^Ver\.\d"),           # Ver.1.1.4.xlsm のような版名
    re.compile(r"^s_\d{8}\.csv$"),     # 入力データのファイル名例示
    re.compile(r"^b_\d{8}\.txt$"),
    re.compile(r"^ikou_\d{8}\.txt$"),
]

# バッククォートのインラインコード、および Markdown リンク [text](path) の
# path 部分からファイルパスらしき文字列を拾う。
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
MD_LINK_RE = re.compile(r"\]\(([^)]+)\)")
# ディレクトリツリーの1行。先頭の "│  " "   " の繰り返し（3文字単位）で
# 深さを判定し、├─ / └─ の後ろの名前を拾う。ディレクトリ行(name/)は
# スタックに積み、後続のファイル行のパスに合成する。
TREE_LINE_RE = re.compile(r"^((?:[│\s]{3})*)([├└])─\s*(\S+)")


def looks_like_path(s):
    """`inline code` や tree の1トークンが、拾うべきファイルパスらしいか。
    ディレクトリ名（拡張子なし）はここではFalseにし、tree解析側で
    別途ディレクトリとして扱う。
    """
    s = s.strip().strip("<>")
    if not s or " " in s:
        return False
    if any(p.match(s) for p in EXCLUDE_PATTERNS):
        return False
    if s.startswith("http://") or s.startswith("https://"):
        return False
    return s.endswith(PATH_EXTENSIONS)


FENCE_RE = re.compile(r"```[^\n]*\n([\s\S]*?)```")


def extract_referenced_paths(readme_text):
    candidates = set()

    # 3連バッククォート(```)のコードブロックは、単発の`code`用正規表現と
    # 衝突して誤爆する（ブロック全体を1つのインラインコードとして飲み込む）
    # ため、まずブロック本文を退避してから、本文以外でインラインコードと
    # リンクを拾う。
    fence_bodies = FENCE_RE.findall(readme_text)
    text_without_fences = FENCE_RE.sub("\uE000", readme_text)

    for m in INLINE_CODE_RE.finditer(text_without_fences):
        s = m.group(1)
        if looks_like_path(s):
            candidates.add(s)

    for m in MD_LINK_RE.finditer(text_without_fences):
        s = m.group(1)
        gh = re.match(r"https://github\.com/[^/]+/[^/]+/blob/main/(.+)", s)
        if gh:
            candidates.add(gh.group(1))
        elif looks_like_path(s):
            candidates.add(s)

    # ディレクトリツリーのコードブロックを、インデント階層を追いながら解析する
    dir_stack = []  # 深さごとの現在のディレクトリ名
    tree_lines = set()
    for line in readme_text.splitlines():
        m = TREE_LINE_RE.match(line)
        if not m:
            continue
        tree_lines.add(line)
        prefix, _, token = m.groups()
        depth = len(prefix) // 3
        is_dir = token.endswith("/")
        clean_name = token.rstrip("/")

        dir_stack = dir_stack[:depth]
        if is_dir:
            dir_stack.append(clean_name)
        elif looks_like_path(clean_name):
            full = "/".join(dir_stack + [clean_name]) if dir_stack else clean_name
            candidates.add(full)

    # フェンス内の残り（ツリー以外のコマンド例）から、パスらしきトークンを拾う。
    # 例: "py -m pip install -r requirements-browser.txt" の末尾トークン
    for body in fence_bodies:
        for line in body.splitlines():
            if line in tree_lines or TREE_LINE_RE.match(line):
                continue
            for tok in line.split():
                tok = tok.strip("`'\"")
                if looks_like_path(tok):
                    candidates.add(tok)

    return sorted(candidates)



def git(*args, cwd="."):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                            text=True, timeout=10)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return 1, "", "git コマンドが見つからない"


def classify(path, repo_root):
    full = Path(repo_root) / path
    exists = full.exists()

    rc, out, _ = git("ls-files", "--error-unmatch", path, cwd=repo_root)
    tracked = rc == 0

    rc2, out2, _ = git("check-ignore", "-q", path, cwd=repo_root)
    ignored = rc2 == 0

    if not exists:
        status = "MISSING"
    elif tracked:
        status = "OK"
    elif ignored:
        status = "IGNORED"
    else:
        status = "UNTRACKED"

    return {"path": path, "exists": exists, "tracked": tracked,
            "ignored": ignored, "status": status}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--readme", default="README.md")
    p.add_argument("--repo-root", default=".")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()

    readme_path = Path(a.repo_root) / a.readme
    if not readme_path.exists():
        print(f"README が見つからない: {readme_path}", file=sys.stderr)
        return 1

    text = readme_path.read_text(encoding="utf-8")
    paths = extract_referenced_paths(text)
    results = [classify(p_, a.repo_root) for p_ in paths]

    if a.json:
        import json
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    by_status = {}
    for r in results:
        by_status.setdefault(r["status"], []).append(r["path"])

    order = ["MISSING", "UNTRACKED", "IGNORED", "OK"]
    labels = {
        "MISSING": "■ MISSING — READMEが参照するが、ディスク上に存在しない",
        "UNTRACKED": "■ UNTRACKED — 存在するが git 未追跡（add忘れ、または新規）",
        "IGNORED": "■ IGNORED — .gitignore 対象（生成物/入力データとして意図的か要確認）",
        "OK": "■ OK — 存在し、git追跡済み",
    }
    for status in order:
        items = by_status.get(status, [])
        print(f"\n{labels[status]}  ({len(items)}件)")
        for path in sorted(items):
            print(f"  {path}")

    print(f"\n合計: {len(results)}件のパスをREADMEから抽出")
    missing = len(by_status.get("MISSING", []))
    untracked = len(by_status.get("UNTRACKED", []))
    if missing or untracked:
        print(f"要対応: MISSING {missing}件 / UNTRACKED {untracked}件", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
