#!/usr/bin/env bash
#
# run.sh - php-upgrade の入口。すべての操作はこれ経由で呼ぶ。
#
#   run.sh preflight              環境チェック
#   run.sh setup                  点検ツール（phpcs + PHPCompatibility）を入れる / 更新する
#   run.sh baseline               パスワードを伏せてから、作業フォルダを git で記録する
#   run.sh mask [--add <file> <行> | --status]  パスワードを伏せる（人が指定した行を追加で伏せる）
#   run.sh target <今のPHP版>      移行先のPHPを決める（例: run.sh target 8.2.32）
#   run.sh inventory              サイトの種類・WordPress本体・プラグイン・テーマを調べる
#   run.sh scan                   互換性を点検する
#   run.sh report                 判定・レポート・一覧表用の1行を作る
#   run.sh recode open|close <file> Shift_JIS などのファイルを一時的に UTF-8 にして直し、元に戻す
#   run.sh finalize               修正差分・アップロード一覧・元ファイル・作業票を作る
#
# カレントディレクトリ＝サイトのルート（FTPでダウンロードしたフォルダ）として扱う。
# サーバーには一切接続しない。出力は ./.php-upgrade/ にまとまる。
#
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_env.sh
. "$HERE/_env.sh"

cmd="${1:-}"; shift || true
case "$cmd" in
  preflight) exec bash "$HERE/preflight.sh" "$@" ;;
  setup)     exec bash "$HERE/setup-tools.sh" "$@" ;;
  baseline)  exec bash "$HERE/baseline.sh" "$@" ;;
  target|inventory|scan|report|recode|mask|finalize)
    need_py
    exec "${PY[@]}" "$(to_native "$HERE/$cmd.py")" "$@" ;;
  *)
    sed -n '3,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2 ;;
esac
