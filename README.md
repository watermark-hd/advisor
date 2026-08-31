# high_sierra_claude

古いIntel Macを、捨てずに実用的なAIコーディングアシスタントとして使うためのプロジェクトです。
[ppc_claude_cli](../ppc_claude_cli)(PowerPC iBook G4 / Tiger向け)の軽量Perlエージェントを、
Snow Leopard(10.6)〜High Sierra(10.13)以降のIntel Mac全般に広げることを目標にしています。

## 対応OSの階層

- **Tier B: Mavericks(10.9)〜High Sierra(10.13)以降** — 標準のcurlが既にTLS1.2に対応しているため、
  追加のビルドなしでそのまま動く。今のところ実装済みなのはこちら。
- **Tier A: Snow Leopard〜Mountain Lion(10.6-10.8)** — 標準curlがTLS1.0にも届かないため、
  ppc_claude_cliと同じ手順(モダンな機器でソース取得→scp転送→対象機でローカルビルド)で
  OpenSSL/curlをビルドする必要がある。未着手(次のステップ)。

## セットアップ (Tier B: High Sierra など)

```bash
bash setup.sh
```

APIキーの案内・保存、`claude` コマンドの設置、bash補完の設置、
ダブルクリック用 `Claude.app` の生成、疎通確認までを行います。
完了したら新しいターミナルを開くか `source ~/.bash_profile` してから `claude` と打つだけです。

## ダブルクリックで起動 (Claude.app)

ターミナルに不慣れな人でもアイコンから始められるよう、`setup.sh` は
`~/Applications/Claude.app` を生成します（`launcher/claude-launcher.applescript` を
`osacompile` でコンパイルしたもの。追加のビルドツールは不要）。
ダブルクリックすると Terminal.app が開いて `claude` が起動します。
Dockやデスクトップに置いておくと次回から一発です。

## `claude` コマンド

エージェント本体(`agent/claude-agent.pl`)は対話ループのみのシンプルな作りのままにし、
オプション処理やモデル選択メニューは `~/bin/claude` (bashラッパー、setup.shが生成)側に持たせています。

```
claude                    保存済みの設定で起動
claude -h, --help         ヘルプを表示
claude --version          バージョンを表示
claude -m <ID>            このセッションだけモデルを指定して起動
claude --select-model     モデルを選ぶメニューを表示し、既定として保存
claude --list-models      選択可能なモデルの一覧を表示
claude --list-history     保存済みの会話を一覧表示 (パスフレーズが必要)
claude --resume           保存済みの会話を選んで続きから再開
claude --no-history       今回は会話を保存しない (パスフレーズも尋ねない)
claude --change-passphrase 履歴パスフレーズを変更
claude --set-recovery     合言葉 (パスフレーズを忘れたとき用) を設定
```

`--select-model` で選んだモデルは `~/.claude-agent-env` に `CLAUDE_MODEL` として保存され、
以降 `claude` を引数なしで起動したときの既定値になります。

新しいターミナルでは `claude ` と打ってTabキーを押すとオプション名が、
`claude -m ` の後でTabを押すと選択可能なモデルIDが補完されます
(`completion/claude-completion.bash`、High Sierra標準のbash 3.2で動作確認)。

## 会話履歴 (暗号化してローカル保存)

会話は既定で `~/.claude-agent/history/<日時>.json.enc` に暗号化して保存されます。
家族と1台のMacを共有していても、パスフレーズを知らない人には読めません。

### しくみ

- ランダムな**マスター鍵**で各会話ファイルを暗号化し、そのマスター鍵自体を
  **パスフレーズ**(と、任意で**合言葉**)で包んで `key.enc` / `key.recovery.enc` に保存します。
  どちらか一方でマスター鍵を取り出せるので、パスフレーズを忘れても合言葉で復旧できます。
- 暗号化は `openssl enc -aes-256-cbc` にシェルアウトして行います(High Sierra標準の
  LibreSSLで動作)。秘密は環境変数経由でopensslに渡し、`ps` 出力やコマンドライン、
  ディスクには出しません。
- High SierraのLibreSSLは `-pbkdf2` 非対応のため鍵導出はMD5ベースとやや弱めですが、
  平文でそのまま置くよりははるかに安全、という位置づけです。

### 使い方

- 初回起動時にパスフレーズを設定します(2回入力)。続けて合言葉(秘密の質問)も
  任意で設定できます。以降は起動のたびにパスフレーズを1回だけ聞かれます(非表示)。
  打ち間違えても回数制限はなく、何度でも入れ直せます。何も入力せずEnterを押せば、
  その回だけ履歴を保存せずに起動します。
- パスフレーズを忘れたら、プロンプトで `r` と入力すると合言葉での復旧に進めます
  (合言葉を設定してある場合のみ)。復旧後にパスフレーズを再設定できます。
  合言葉の答えは大文字小文字と前後・連続空白を区別しません。
- `claude --resume` で前回の続きから、`claude --list-history` で一覧を確認。
- `claude --change-passphrase` でパスフレーズ変更、`claude --set-recovery` で
  合言葉の設定/変更(いずれもマスター鍵を包み直すだけなので既存の履歴はそのまま)。
- `claude --no-history`(または環境変数 `CLAUDE_NO_HISTORY=1`)で保存を無効化。
  このときパスフレーズは尋ねられません。
- **パスフレーズも合言葉も両方忘れると、それまでの履歴は復号できなくなります。**
  作り直す場合は `~/.claude-agent/history/` を削除して再設定してください。

> 注意: 合言葉の答え(「初めて買った車の名前」など)は推測されやすいと、そこが
> 一番の弱点になります。パスワード並みに自明でないものを選ぶか、その弱さを承知で
> 使ってください。

## エージェントについて (`agent/claude-agent.pl`)

- 単一ファイル、外部CPANモジュール依存ゼロ
- JSON encode/decodeは自前実装(再帰下降パーサー)
- 4つのツール: `read_file` / `write_file` / `list_dir` / `run_shell`(書き込み・実行は確認プロンプトあり)
- HTTP通信はcurlをサブプロセスとして呼び出す方式(TLSをPerl側に持たせない)
- 会話履歴は `openssl` にシェルアウトして暗号化保存(上記参照)
- `CLAUDE_CURL` / `CLAUDE_CACERT` 環境変数で、Tier A向けの自前ビルドtoolchainに差し替え可能
  (`setup.sh` は `~/claude-toolchain` があれば自動的にそちらを優先する)

## 課金について

このリポジトリ自体は自由に使えますが、実際にAPIを使うには各自Anthropicの
[console.anthropic.com](https://console.anthropic.com/)でAPIキーを発行し、
自分の利用分だけ課金される仕組みです(claude.aiのPro/Max等のサブスクリプションとは別)。
コードにAPIキーは一切含まれていません。
