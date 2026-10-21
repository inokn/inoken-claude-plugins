#!/usr/bin/env bash
#
# baseline.sh - パスワードを伏せてから、作業フォルダを git で記録する（run.sh baseline から呼ばれる）
#
# - まず mask.py でパスワードらしき値を印に置き換える（本物の値は作業フォルダの外へ）
# - .git が無ければ git init し、伏せたあとの状態を「取得時点」としてコミットして、
#   タグ php-upgrade-baseline を付ける（手元だけ。リモートは作らない）
# - すでに .git があれば、未コミットの変更が無いことを確かめてから、伏せた状態をコミットしてタグを付ける
# - wp-config.php / .env とアップロード画像・キャッシュは記録しない
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_env.sh
. "$HERE/_env.sh"
need_py

[ -n "$(ls -A . 2>/dev/null)" ] || { echo "カレントディレクトリが空です。サイトのルートで実行してください。" >&2; exit 1; }

G=(git -c user.name="php-upgrade" -c user.email="php-upgrade@localhost" -c core.autocrlf=false -c core.quotepath=false)

if [ ! -d .git ]; then
  git init -q
  git config core.autocrlf false
  git config core.quotepath false
  git config core.longpaths true 2>/dev/null || true
  git config php-upgrade.created true
  fresh=1
else
  fresh=0
fi

# 記録しないもの（.gitignore はサイトのファイルなので触らず、info/exclude に書く）
EX=.git/info/exclude
mkdir -p .git/info
for p in "/.php-upgrade/" "wp-config.php" ".env" ".env.*" "/wp-content/uploads/" "/wp-content/cache/" \
         "/wp-content/upgrade/" "/wp-content/backup*/" "/wp-content/ai1wm-backups/" "/wp-content/updraft/" \
         "node_modules/" "*.log" "*.sql" "*.sql.gz" "*.zip" "*.tar.gz" ".DS_Store" "Thumbs.db"; do
  grep -qxF "$p" "$EX" 2>/dev/null || echo "$p" >> "$EX"
done

if git rev-parse -q --verify refs/tags/php-upgrade-baseline >/dev/null; then
  echo "すでに記録済みです（タグ php-upgrade-baseline: $(git log -1 --format='%h %ci' php-upgrade-baseline)）"
  exit 0
fi

if [ "$fresh" -eq 0 ] && [ -n "$(git status --porcelain)" ]; then
  echo "未コミットの変更があります。先に状態を確認してください（git status）。" >&2
  git status --short | head -20 >&2
  exit 1
fi

# 記録する前に伏せる（記録に本物の値を残さない）
"${PY[@]}" "$(to_native "$HERE/mask.py")" --no-commit

if [ "$fresh" -eq 1 ]; then
  git add -A
  "${G[@]}" commit -q -m "取得時点の状態（パスワードは伏せてある。php-upgrade baseline）" --allow-empty
elif [ -n "$(git status --porcelain)" ]; then
  git add -A
  "${G[@]}" commit -q -m "認証情報を伏せた（php-upgrade）"
  echo "⚠️ もともとあった git の履歴には、伏せる前の値が残っています。git log -p などで過去の履歴を表示しないでください。"
fi
git tag php-upgrade-baseline
echo "記録しました: $(git log -1 --format='%h' php-upgrade-baseline)（$(git ls-files | wc -l | tr -d ' ') ファイル）"
echo "除外: wp-config.php / .env / uploads / キャッシュ / バックアップ類"
