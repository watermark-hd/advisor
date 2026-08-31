#!/bin/bash
# setup.sh — high_sierra_claude (advisor) のセットアップスクリプト
#
# 対象: Mavericks(10.9)〜High Sierra(10.13)以降のIntel Mac(Tier B)。
# これらは標準のcurlが既にTLS1.2に対応しているため、追加のビルドなしで
# そのまま使える。もし ~/claude-toolchain (ppc_claude_cli と同じ手順で
# ビルドしたTLS対応curl/OpenSSL、Tier A=Snow Leopard〜Mountain Lion向け)
# が既にあれば、そちらを自動的に優先して使う。
#
# やること:
#   1. 使うAI(Gemini / Anthropic)の選択
#   2. APIキーの案内と安全な入力・保存 (~/.claude-agent-env)
#   3. claude-agent.pl と models.txt を ~/claude-build/ に配置
#   4. ~/bin/advisor ラッパーコマンドの設置
#   5. bash補完の設置 (~/.bash_profile から source)
#   6. ダブルクリック用 Advisor.app の生成 (~/Applications、osacompile使用)
#   7. 実際にAPIを叩いて疎通確認

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$HOME/.claude-agent-env"
BUILD_DIR="$HOME/claude-build"
BIN_DIR="$HOME/bin"
COMPLETION_FILE="$HOME/.advisor-completion.bash"
APP_PATH="$HOME/Applications/Advisor.app"
LAUNCHER_SRC="$SCRIPT_DIR/launcher/advisor-launcher.applescript"

# ~/.claude-agent-env の1行を差し替える(無ければ追記)
upsert_env() {
  local var="$1" val="$2"
  touch "$ENV_FILE"
  grep -v "^export ${var}=" "$ENV_FILE" > "$ENV_FILE.tmp" 2>/dev/null || true
  mv "$ENV_FILE.tmp" "$ENV_FILE"
  printf 'export %s=%s\n' "$var" "$val" >> "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}

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

echo "=== high_sierra_claude (advisor) セットアップ ==="
echo ""

# 既存の設定を読み込んでおく(キーの使い回し判定に使う)
[ -f "$ENV_FILE" ] && . "$ENV_FILE" 2>/dev/null || true

# --- 1. 使うAIを選ぶ ---
echo "どちらのAIを使いますか?"
echo "  1) Gemini (Google)   — 無料枠あり・クレジットカード不要        [既定]"
echo "  2) Anthropic (Claude) — 高性能・従量課金(要クレジットチャージ)"
printf "番号を入力 [1]: "
read -r PROVIDER_CHOICE
PROVIDER_CHOICE="${PROVIDER_CHOICE:-1}"

if [ "$PROVIDER_CHOICE" = "2" ]; then
  PROVIDER="anthropic"
  KEY_VAR="ANTHROPIC_API_KEY"
else
  PROVIDER="gemini"
  KEY_VAR="GEMINI_API_KEY"
fi
echo "→ $PROVIDER を使います。"
echo ""

# --- 2. APIキー ---
# 既にそのプロバイダのキーが保存済みなら、それを使う
EXISTING_KEY="$(eval "printf '%s' \"\${$KEY_VAR}\"")"
if [ -n "$EXISTING_KEY" ]; then
  echo "保存済みの $KEY_VAR をそのまま使います。"
  echo "別のキーに変えたい場合は 'rm $ENV_FILE' してから再実行してください。"
  API_KEY="$EXISTING_KEY"
  echo ""
else
  if [ "$PROVIDER" = "gemini" ]; then
    echo "Gemini APIキーが必要です。まだお持ちでない場合:"
    echo "  1. https://aistudio.google.com/apikey を開く"
    echo "  2. Googleアカウントでログイン"
    echo "  3. 'Create API key' でキーを発行(無料枠を使う分にはカード登録不要)"
    echo ""
    echo "'AIza' で始まる文字列がAPIキーです。"
  else
    echo "Anthropic APIキーが必要です。まだお持ちでない場合:"
    echo "  1. https://console.anthropic.com/ を開く (claude.aiとは別サイトです)"
    echo "  2. アカウントを作成 / ログイン"
    echo "  3. 左メニューの 'API Keys' から新しいキーを発行"
    echo "  4. 'Billing' で少額のクレジットをチャージ(従量課金)"
    echo ""
    echo "注意: claude.aiにログインする時のパスワードとは別物です。"
    echo "'sk-ant-api03-' で始まる長い文字列がAPIキーです。"
  fi
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

  if [ "$PROVIDER" = "gemini" ]; then
    case "$API_KEY" in
      AIza*) ;;
      *) echo "警告: 'AIza' で始まっていません。貼り付けミスがないか確認してください(このまま続けます)。" ;;
    esac
  else
    case "$API_KEY" in
      sk-ant-api*) ;;
      *) echo "警告: 'sk-ant-api' で始まっていません。claude.aiのパスワードなどを貼り付けていませんか?(このまま続けます)" ;;
    esac
  fi

  key_len=$(echo -n "$API_KEY" | wc -c | tr -d ' ')
  if [ "$key_len" -lt 30 ]; then
    echo "警告: キーが ${key_len} 文字しかありません。コピーが途中で切れていませんか?"
  fi

  upsert_env "$KEY_VAR" "$API_KEY"
  echo "$ENV_FILE に保存しました(あなたのアカウントだけが読めるファイルです)"
  echo ""
fi

upsert_env "CLAUDE_PROVIDER" "$PROVIDER"

# --- 3. エージェント本体を配置 ---
mkdir -p "$BUILD_DIR"
cp "$SCRIPT_DIR/agent/claude-agent.pl" "$BUILD_DIR/claude-agent.pl"
cp "$SCRIPT_DIR/models.txt" "$BUILD_DIR/models.txt"
echo "$BUILD_DIR に claude-agent.pl / models.txt を配置しました。"

# --- 4. advisor コマンド(ラッパー)の設置 ---
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/advisor" << WRAPEOF
#!/bin/bash
# advisor — high_sierra_claude ラッパーコマンド (setup.sh が自動生成)
set -e

ENV_FILE="$ENV_FILE"
MODELS_FILE="$BUILD_DIR/models.txt"
AGENT_SCRIPT="$BUILD_DIR/claude-agent.pl"
CURL_BIN="$CURL_BIN"
CACERT="$CACERT"

source "\$ENV_FILE"

show_help() {
  cat <<EOF
使い方: advisor [オプション]

  -h, --help              このヘルプを表示
      --version           バージョンを表示
  -m, --model <ID>        このセッションだけモデルを指定して起動
      --select-model      モデルを選ぶメニューを表示し、既定として保存
      --list-models       選択可能なモデルの一覧を表示
      --list-history      保存済みの会話を一覧表示 (パスフレーズが必要)
      --resume            保存済みの会話を選んで続きから再開
      --no-history        今回は会話を保存しない (パスフレーズも尋ねない)
      --change-passphrase 履歴パスフレーズを変更
      --set-recovery      合言葉 (パスフレーズを忘れたとき用の秘密の質問) を設定

引数なしで実行すると、保存済みの設定で起動します。
使うAI(anthropic/gemini)は setup.sh で選択。会話中に /claude・/gemini で
切り替えられます。会話は既定で ~/.claude-agent/history に暗号化保存されます
(初回起動時にパスフレーズを設定。合言葉も任意で設定できます)。
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
    --version) echo "advisor (high_sierra_claude) 0.1"; exit 0 ;;
    --list-models) list_models; exit 0 ;;
    --select-model) select_model; shift ;;
    --list-history) PERL_ARGS[\${#PERL_ARGS[@]}]="--list-history"; shift ;;
    --resume) PERL_ARGS[\${#PERL_ARGS[@]}]="--resume"; shift ;;
    --change-passphrase) PERL_ARGS[\${#PERL_ARGS[@]}]="--change-passphrase"; shift ;;
    --set-recovery) PERL_ARGS[\${#PERL_ARGS[@]}]="--set-recovery"; shift ;;
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
chmod +x "$BIN_DIR/advisor"
echo "$BIN_DIR/advisor を作成しました。"
# 旧名(claude)が残っていれば片付ける
[ -e "$BIN_DIR/claude" ] && rm -f "$BIN_DIR/claude" && echo "旧 $BIN_DIR/claude を削除しました。"

if ! grep -qF 'export PATH=$HOME/bin:$PATH' "$HOME/.bash_profile" 2>/dev/null; then
  echo "export PATH=\$HOME/bin:\$PATH" >> "$HOME/.bash_profile"
  echo "PATHに $BIN_DIR を追加しました。"
fi

# --- 5. bash補完の設置 ---
cp "$SCRIPT_DIR/completion/advisor-completion.bash" "$COMPLETION_FILE"
if ! grep -qF "source $COMPLETION_FILE" "$HOME/.bash_profile" 2>/dev/null; then
  echo "source $COMPLETION_FILE" >> "$HOME/.bash_profile"
  echo "bash補完を設置しました($COMPLETION_FILE)。"
fi
# 旧補完(claude)の後始末
if [ -f "$HOME/.claude-completion.bash" ]; then
  grep -v "source $HOME/.claude-completion.bash" "$HOME/.bash_profile" > "$HOME/.bash_profile.tmp" 2>/dev/null && mv "$HOME/.bash_profile.tmp" "$HOME/.bash_profile" || true
  rm -f "$HOME/.claude-completion.bash"
fi
echo "(次回ログインから有効。今すぐ使うには 'source ~/.bash_profile' を実行するか、新しいターミナルを開いてください)"
echo ""

# --- 6. ダブルクリック用 Advisor.app の生成 ---
# ターミナルに不慣れな人でもアイコンから始められるようにするためのランチャー。
# osacompile はどの macOS にも標準で入っているので追加ビルドは不要。
if command -v osacompile >/dev/null 2>&1 && [ -f "$LAUNCHER_SRC" ]; then
  mkdir -p "$HOME/Applications"
  rm -rf "$APP_PATH" "$HOME/Applications/Claude.app"
  if osacompile -o "$APP_PATH" "$LAUNCHER_SRC" 2>/dev/null; then
    echo "$APP_PATH を作成しました。"
    echo "  Finderで ~/Applications を開き、Advisor をダブルクリックすると起動します。"
    echo "  Dockやデスクトップにドラッグしておくと次回から一発です。"
  else
    echo "Advisor.app の生成に失敗しました(スキップ)。ターミナルから 'advisor' で問題なく使えます。"
  fi
else
  echo "osacompile が見つからないため Advisor.app の生成はスキップします。"
  echo "ターミナルから 'advisor' と打てば起動します。"
fi
echo ""

# --- 7. 疎通確認 ---
echo "APIへの疎通を確認しています..."
RESPONSE_FILE="/tmp/advisor-setup-check-$$.json"
if [ -n "$CACERT" ]; then
  CACERT_OPT=(--cacert "$CACERT")
else
  CACERT_OPT=()
fi

if [ "$PROVIDER" = "gemini" ]; then
  GEMINI_MODEL="${CLAUDE_MODEL:-gemini-3.5-flash-lite}"
  case "$GEMINI_MODEL" in gemini*) ;; *) GEMINI_MODEL="gemini-3.5-flash-lite" ;; esac
  HTTP_CODE=$("$CURL_BIN" -s "${CACERT_OPT[@]}" \
    "https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent" \
    -H "x-goog-api-key: $API_KEY" \
    -H "content-type: application/json" \
    -d '{"contents":[{"parts":[{"text":"hi"}]}],"generationConfig":{"maxOutputTokens":8}}' \
    -o "$RESPONSE_FILE" \
    -w "%{http_code}")
else
  HTTP_CODE=$("$CURL_BIN" -s "${CACERT_OPT[@]}" \
    https://api.anthropic.com/v1/messages \
    -H "x-api-key: $API_KEY" \
    -H "anthropic-version: 2023-06-01" \
    -H "content-type: application/json" \
    -d '{"model":"claude-sonnet-5","max_tokens":10,"messages":[{"role":"user","content":"hi"}]}' \
    -o "$RESPONSE_FILE" \
    -w "%{http_code}")
fi

echo ""
if [ "$HTTP_CODE" = "200" ]; then
  echo "疎通確認OK。準備完了です。"
  echo ""
  echo "使い方: ターミナルで 'advisor' と打つだけです。"
  echo "  advisor --help            オプション一覧"
  echo "  advisor --select-model    使うモデルを選ぶ"
  echo "  advisor -m <ID>           このセッションだけモデルを指定"
  echo "  (会話中に /claude・/gemini でAIを切り替え)"
else
  echo "APIエラー(HTTP $HTTP_CODE)。キーが正しいか、"
  if [ "$PROVIDER" = "gemini" ]; then
    echo "AI Studio でキーが有効か確認してください。"
  else
    echo "Console でクレジットがチャージされているか確認してください。"
  fi
  echo "--- サーバーからの応答 ---"
  cat "$RESPONSE_FILE"
  echo ""
fi
rm -f "$RESPONSE_FILE"
