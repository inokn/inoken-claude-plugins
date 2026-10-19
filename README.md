# inoken-claude-plugins

[inoken.ai](https://inoken.ai) が公開している [Claude Code](https://code.claude.com) 用プラグインの marketplace です。

| プラグイン | できること | 対応OS |
|---|---|---|
| [`illustrator-to-html`](plugins/illustrator-to-html/skills/illustrator-to-html/README.md) | Illustrator のカンプ（`.ai`）から実測値を取り出して HTML/CSS を実装し、ブラウザでレンダリングしてカンプとのズレを数値（Δy/Δx）で照合する | Windows / macOS |

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
    "illustrator-to-html@inoken-ai": true
  }
}
```

- すでに Managed settings に設定がある場合は、上のキーをその JSON に足してください（丸ごと置き換えると既存の設定が消えます）
- `autoUpdate: true` で、このリポジトリの更新が自動で各 PC に届きます
- 届いたかは、各 PC で Claude Code を起動して `/plugin` を開くと確認できます

## 個人で入れる

Claude Code で:

```
/plugin marketplace add https://github.com/inokn/inoken-claude-plugins.git
/plugin install illustrator-to-html@inoken-ai
```

## 入れたあと（illustrator-to-html）

各 PC で一度だけ、Claude Code に「illustrator-to-html の環境チェックをして」と頼んでください。
足りないもの（Node.js / Python / ブラウザ用パッケージ）があれば、入れ方を案内します。
詳しくは [プラグインの README](plugins/illustrator-to-html/skills/illustrator-to-html/README.md) を参照してください。

## ライセンス

[MIT](LICENSE)
