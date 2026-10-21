# inoken-claude-plugins

[inoken.ai](https://inoken.ai) が公開している [Claude Code](https://code.claude.com) 用プラグインの marketplace です。

| プラグイン | できること | 対応OS |
|---|---|---|
| [`illustrator-to-html`](plugins/illustrator-to-html/skills/illustrator-to-html/README.md) | Illustrator のカンプ（`.ai`）から実測値を取り出して HTML/CSS を実装し、ブラウザでレンダリングしてカンプとのズレを数値（Δy/Δx）で照合する | Windows / macOS |
| [`php-upgrade`](plugins/php-upgrade/skills/php-upgrade/README.md) | 手元に持ってきた PHP サイト（WordPress 含む）を、脆弱性の修正が入った PHP へ上げられるか点検し、自作コードを直して、アップロード一覧・元ファイル・作業票を出す（サーバーには接続しない） | Windows / macOS / Linux |

## 組織に一括で配る（Claude Team / Enterprise）

組織の Owner が claude.ai の **Organization settings > Claude Code > Managed settings** に次の JSON を追加すると、
組織のアカウントで Claude Code にログインしている全員に、次回起動時から自動で入ります。
メンバーに GitHub アカウントは不要です（PC に git があれば足ります。Windows 版 Claude Code が使う Git for Windows で可）。

```json
{
  "extraKnownMarketplaces": {
    "inoken-ai": {
      "source": { "source": "git", "url": "https://github.com/inokn/inoken-claude-plugins.git" },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "illustrator-to-html@inoken-ai": true,
    "php-upgrade@inoken-ai": true
  }
}
```

- `enabledPlugins` に書いたプラグインだけが入ります。使わないものは行ごと消してください
- php-upgrade を使う場合は、パスワードのファイルを読めなくする `permissions.deny` もあわせて設定してください（[プラグインの README](plugins/php-upgrade/skills/php-upgrade/README.md#パスワードの扱い2段構え)）
- すでに Managed settings に設定がある場合は、上のキーをその JSON に足してください（丸ごと置き換えると既存の設定が消えます）
- `autoUpdate: true` で、このリポジトリの更新が自動で各 PC に届きます
- 届いたかは、各 PC で Claude Code を起動して `/plugin` を開くと確認できます

## 個人で入れる

Claude Code で:

```
/plugin marketplace add https://github.com/inokn/inoken-claude-plugins.git
/plugin install illustrator-to-html@inoken-ai
/plugin install php-upgrade@inoken-ai
```

## 入れたあと（illustrator-to-html）

各 PC で一度だけ、Claude Code に「illustrator-to-html の環境チェックをして」と頼んでください。
足りないもの（Node.js / Python / ブラウザ用パッケージ）があれば、入れ方を案内します。
詳しくは [プラグインの README](plugins/illustrator-to-html/skills/illustrator-to-html/README.md) を参照してください。

## 入れたあと（php-upgrade）

各 PC で一度だけ、Claude Code に「php-upgrade の環境チェックをして」と頼んでください（PHP が無ければ入れ方を案内します）。
そのあとは、FTP でダウンロードしたサイトのフォルダで「このサイトのPHP移行チェックをして。今のPHPは 8.0.30」のように頼みます。
詳しくは [プラグインの README](plugins/php-upgrade/skills/php-upgrade/README.md) を参照してください。

## ライセンス

[MIT](LICENSE)
