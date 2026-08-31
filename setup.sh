#!/bin/bash
# setup.sh — high_sierra_claude のセットアップスクリプト
#
# 対象: Mavericks(10.9)〜High Sierra(10.13)以降のIntel Mac(Tier B)。
# これらは標準のcurlが既にTLS1.2に対応しているため、追加のビルドなしで
# そのまま使える。もし ~/claude-toolchain (ppc_claude_cli と同じ手順で
# ビルドしたTLS対応curl/OpenSSL、Tier A=Snow Leopard〜Mountain Lion向け)
# が既にあれば、そちらを自動的に優先して使う。
#
# やること:
#   1. Anthropic APIキーの案内と安全な入力・保存 (~/.claude-agent-env)
#   2. claude-agent.pl と models.txt を ~/claude-build/ に配置
#   3. ~/bin/claude ラッパーコマンドの設置 (--help/--model/--select-model等)
#   4. bash補完の設置 (~/.bash_profile から source)
#   5. ダブルクリック用 Claude.app の生成 (~/Applications、osacompile使用)
#   6. 実際にAPIを叩いて疎通確認

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$HOME/.claude-agent-env"
BUILD_DIR="$HOME/claude-build"
BIN_DIR="$HOME/bin"
COMPLETION_FILE="$HOME/.claude-completion.bash"

# Tier A の自前ビルドtoolchainがあればそちらを使い、無ければ標準curlを使う
if [ -x "$HOME/claude-toolchain/bin/curl" ]; then
  CURL_BIN="$HOME/claude-toolchain/bin/curl"
  CACERT="$HOME/claude-toolchain/cacert.pem"
  echo "Tier A toolchain (~/claude-toolchain) が見つかりました。こちらを使います。"
else
  CURL_BIN="curl"
  CACERT=""
  echo "標準のcurlを使います(Mavericks以降はTLS1.2対応済みのため追加ビルド不要)。"
fi
echo ""

echo "=== high_sierra_claude セットアップ ==="
echo ""

if [ -f "$ENV_FILE" ]; then
  echo "既存のAPIキー($ENV_FILE)をそのまま使います(バージョンアップ時は毎回これでOK)。"
  echo "別のキーに変えたい場合は、このファイルを削除してからもう一度実行してください:"
  echo "  rm $ENV_FILE"
  echo ""
else
  echo "Anthropic APIキーが必要です。まだお持ちでない場合:"
  echo "  1. https://console.anthropic.com/ を開く (claude.aiとは別サイトです)"
  echo "  2. アカウントを作成 / ログイン"
  echo "  3. 左メニューの 'API Keys' から新しいキーを発行"
  echo "  4. 'Billing' で少額のクレジットをチャージ(従量課金)"
  echo ""
  echo "注意: claude.aiにログインする時のパスワードとは別物です。"
  echo "'sk-ant-api03-' で始まる長い文字列がAPIキーです。"
  echo ""

  printf "APIキーを貼り付けてEnter(画面には表示されません): "
  stty -echo 2>/dev/null || true
  read -r API_KEY
  stty echo 2>/dev/null || true
  echo ""

  API_KEY=$(echo "$API_KEY" | sed 's/^[ \t]*//;s/[ \t]*$//')

  if [ -z "$API_KEY" ]; then
    echo "エラー: 何も入力されませんでした。もう一度実行してください。"
    exit 1
  fi

  case "$API_KEY" in
    \<*|*\>)
      echo "エラー: '<' か '>' が含まれています。"
      echo "説明文のプレースホルダー記号を誤って一緒に貼り付けていませんか?"
      echo "記号を含めず、キーの値だけを貼り付けてください。"
      exit 1
      ;;
  esac

  case "$API_KEY" in
    sk-ant-api*) ;;
    *)
      echo "警告: 'sk-ant-api' で始まっていません。"
      echo "claude.aiのパスワードなど別のものを貼り付けていませんか?"
      echo "このまま処理を続けますが、動作確認で失敗する可能性があります。"
      ;;
  esac

  key_len=$(echo -n "$API_KEY" | wc -c | tr -d ' ')
  if [ "$key_len" -lt 50 ]; then
    echo "警告: キーが ${key_len} 文字しかありません。コピーが途中で切れていませんか?"
  fi

  printf 'export ANTHROPIC_API_KEY=%s\n' "$API_KEY" > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "$ENV_FILE に保存しました(あなたのアカウントだけが読めるファイルです)"
  echo ""
fi

# shellcheck disable=SC1090
source "$ENV_FILE"
API_KEY="$ANTHROPIC_API_KEY"

# --- エージェント本体を配置 ---
mkdir -p "$BUILD_DIR"
cp "$SCRIPT_DIR/agent/claude-agent.pl" "$BUILD_DIR/claude-agent.pl"
cp "$SCRIPT_DIR/models.txt" "$BUILD_DIR/models.txt"
echo "$BUILD_DIR に claude-agent.pl / models.txt を配置しました。"

# --- claude コマンド(ラッパー)の設置 ---
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/claude" << WRAPEOF
#!/bin/bash
# claude — high_sierra_claude ラッパーコマンド (setup.sh が自動生成)
set -e

ENV_FILE="$ENV_FILE"
MODELS_FILE="$BUILD_DIR/models.txt"
AGENT_SCRIPT="$BUILD_DIR/claude-agent.pl"
CURL_BIN="$CURL_BIN"
CACERT="$CACERT"

source "\$ENV_FILE"

show_help() {
  cat <<EOF
使い方: claude [オプション]

  -h, --help              このヘルプを表示
      --version           バージョンを表示
  -m, --model <ID>        このセッションだけモデルを指定して起動
      --select-model      モデルを選ぶメニューを表示し、既定として保存
      --list-models       選択可能なモデルの一覧を表示
      --list-history      保存済みの会話を一覧表示 (パスフレーズが必要)
      --resume            保存済みの会話を選んで続きから再開
      --no-history        今回は会話を保存しない (パスフレーズも尋ねない)

引数なしで実行すると、保存済みの設定でエージェントを起動します。
会話は既定で ~/.claude-agent/history に暗号化して保存されます
(初回起動時にパスフレーズを設定)。
EOF
}

list_models() {
  awk -F'|' '{printf "  %-32s %s\n", \$1, \$2}' "\$MODELS_FILE"
}

select_model() {
  echo "モデルを選んでください:"
  local i=1
  local ids=()
  while IFS='|' read -r id desc; do
    printf "  %d) %-28s %s\n" "\$i" "\$id" "\$desc"
    ids+=("\$id")
    i=\$((i+1))
  done < "\$MODELS_FILE"
  printf "番号を入力 [1]: "
  read -r choice
  choice=\${choice:-1}
  local chosen="\${ids[\$((choice-1))]}"
  if [ -z "\$chosen" ]; then
    echo "無効な選択です。"
    exit 1
  fi
  grep -v '^export CLAUDE_MODEL=' "\$ENV_FILE" > "\$ENV_FILE.tmp" 2>/dev/null || true
  mv "\$ENV_FILE.tmp" "\$ENV_FILE"
  echo "export CLAUDE_MODEL=\$chosen" >> "\$ENV_FILE"
  chmod 600 "\$ENV_FILE"
  echo "既定モデルを \$chosen に設定しました。"
  export CLAUDE_MODEL="\$chosen"
}

PERL_ARGS=()
while [ \$# -gt 0 ]; do
  case "\$1" in
    -h|--help) show_help; exit 0 ;;
    --version) echo "claude (high_sierra_claude) 0.1"; exit 0 ;;
    --list-models) list_models; exit 0 ;;
    --select-model) select_model; shift ;;
    --list-history) PERL_ARGS[\${#PERL_ARGS[@]}]="--list-history"; shift ;;
    --resume) PERL_ARGS[\${#PERL_ARGS[@]}]="--resume"; shift ;;
    --no-history) export CLAUDE_NO_HISTORY=1; shift ;;
    -m|--model)
      export CLAUDE_MODEL="\$2"
      shift 2
      ;;
    *)
      echo "不明なオプション: \$1" >&2
      show_help
      exit 1
      ;;
  esac
done

export CLAUDE_CURL="\$CURL_BIN"
[ -n "\$CACERT" ] && export CLAUDE_CACERT="\$CACERT"
if [ \${#PERL_ARGS[@]} -gt 0 ]; then
  exec perl "\$AGENT_SCRIPT" "\${PERL_ARGS[@]}"
else
  exec perl "\$AGENT_SCRIPT"
fi
WRAPEOF
chmod +x "$BIN_DIR/claude"
echo "$BIN_DIR/claude を作成しました。"

if ! grep -qF 'export PATH=$HOME/bin:$PATH' "$HOME/.bash_profile" 2>/dev/null; then
  echo "export PATH=\$HOME/bin:\$PATH" >> "$HOME/.bash_profile"
  echo "PATHに $BIN_DIR を追加しました。"
fi

# --- bash補完の設置 ---
cp "$SCRIPT_DIR/completion/claude-completion.bash" "$COMPLETION_FILE"
if ! grep -qF "source $COMPLETION_FILE" "$HOME/.bash_profile" 2>/dev/null; then
  echo "source $COMPLETION_FILE" >> "$HOME/.bash_profile"
  echo "bash補完を設置しました($COMPLETION_FILE)。"
fi
echo "(次回ログインから有効。今すぐ使うには 'source ~/.bash_profile' を実行するか、新しいターミナルを開いてください)"
echo ""

# --- ダブルクリック用 Claude.app の生成 ---
# ターミナルに不慣れな人でもアイコンから始められるようにするためのランチャー。
# osacompile はどの macOS にも標準で入っているので追加ビルドは不要。
APP_PATH="$HOME/Applications/Claude.app"
LAUNCHER_SRC="$SCRIPT_DIR/launcher/claude-launcher.applescript"
if command -v osacompile >/dev/null 2>&1 && [ -f "$LAUNCHER_SRC" ]; then
  mkdir -p "$HOME/Applications"
  rm -rf "$APP_PATH"
  if osacompile -o "$APP_PATH" "$LAUNCHER_SRC" 2>/dev/null; then
    echo "$APP_PATH を作成しました。"
    echo "  Finderで ~/Applications を開き、Claude をダブルクリックすると起動します。"
    echo "  Dockやデスクトップにドラッグしておくと次回から一発です。"
  else
    echo "Claude.app の生成に失敗しました(スキップ)。ターミナルから 'claude' で問題なく使えます。"
  fi
else
  echo "osacompile が見つからないため Claude.app の生成はスキップします。"
  echo "ターミナルから 'claude' と打てば起動します。"
fi
echo ""

# --- 疎通確認 ---
echo "APIへの疎通を確認しています..."
RESPONSE_FILE="/tmp/claude-setup-check-$$.json"
if [ -n "$CACERT" ]; then
  CACERT_OPT=(--cacert "$CACERT")
else
  CACERT_OPT=()
fi
HTTP_CODE=$("$CURL_BIN" -s "${CACERT_OPT[@]}" \
  https://api.anthropic.com/v1/messages \
  -H "x-api-key: $API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-sonnet-5","max_tokens":10,"messages":[{"role":"user","content":"hi"}]}' \
  -o "$RESPONSE_FILE" \
  -w "%{http_code}")

echo ""
if [ "$HTTP_CODE" = "200" ]; then
  echo "疎通確認OK。準備完了です。"
  echo ""
  echo "使い方: ターミナルで 'claude' と打つだけです。"
  echo "  claude --help            オプション一覧"
  echo "  claude --select-model    使うモデルを選ぶ"
  echo "  claude -m <ID>           このセッションだけモデルを指定"
else
  echo "APIエラー(HTTP $HTTP_CODE)。キーが正しいか、Consoleでクレジットが"
  echo "チャージされているか確認してください。"
  echo "--- サーバーからの応答 ---"
  cat "$RESPONSE_FILE"
  echo ""
fi
rm -f "$RESPONSE_FILE"
