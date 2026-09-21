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
#   6. ダブルクリック用 Advisor.app (GUI) の生成 (~/Applications)
#   7. 実際にAPIを叩いて疎通確認
#
# 日英対応: ダウンロードの7割が海外ユーザーとのことで必須になった。
# GUI(advisor_gui.py)・エージェント(claude-agent.pl)と同じく、macOSの
# システム言語設定を直接見て判定する(LANG環境変数はSSH/GUI起動時に
# あてにならないことがあるため)。bash 3.2(旧Macの標準)には連想配列が
# 無いので、msg()内のcase文で日英を切り替える方式にしている。

set -e

# --- 言語判定 ---
# CLAUDE_LANG=en/ja があれば最優先(システム言語を変えずに英語表示を
# 確認したいとき用)。例: CLAUDE_LANG=en bash setup.sh
IS_EN=0
case "${CLAUDE_LANG:-}" in
  en) IS_EN=1 ;;
  ja) IS_EN=0 ;;
  *)
    if command -v defaults >/dev/null 2>&1; then
      LOCALE_DETECTED="$(defaults read -g AppleLocale 2>/dev/null || true)"
      case "$LOCALE_DETECTED" in
        ja*|"") IS_EN=0 ;;
        *) IS_EN=1 ;;
      esac
    fi
    ;;
esac

# msg <key> [printf-args...]: キーに対応する文言を表示する。
# IS_EN=1のとき英語のcaseにヒットすればそれを、無ければ日本語(既定)に
# フォールバックする(訳し漏れがあっても壊れず日本語表示になるだけ)。
msg() {
  local key="$1"; shift
  local fmt=""
  if [ "$IS_EN" = "1" ]; then
    case "$key" in
      tier_a) fmt="Found the Tier A toolchain (~/claude-toolchain). Using it." ;;
      stock_curl) fmt="Using the system curl (Mavericks and later already support TLS 1.2, no extra build needed)." ;;
      title) fmt="=== high_sierra_claude (advisor) setup ===" ;;
      ask_provider) fmt="Which AI do you want to use?" ;;
      opt_gemini) fmt="  1) Gemini (Google)    — free tier available, no credit card needed   [default]" ;;
      opt_anthropic) fmt="  2) Anthropic (Claude) — high performance, pay-as-you-go (needs a credit charge)" ;;
      enter_number) fmt="Enter a number [1]: " ;;
      using_provider) fmt="→ Using %s." ;;
      reuse_key) fmt="Using the already-saved %s." ;;
      reuse_key_hint) fmt="To use a different key, run 'rm %s' and start over." ;;
      gemini_key_intro) fmt="A Gemini API key is required. If you don't have one yet:" ;;
      gemini_key_1) fmt="  1. Open https://aistudio.google.com/apikey" ;;
      gemini_key_2) fmt="  2. Sign in with your Google account" ;;
      gemini_key_3) fmt="  3. Click 'Create API key' (no card needed for the free tier)" ;;
      gemini_key_hint) fmt="The API key is the string starting with 'AIza'." ;;
      anthropic_key_intro) fmt="An Anthropic API key is required. If you don't have one yet:" ;;
      anthropic_key_1) fmt="  1. Open https://console.anthropic.com/ (a different site from claude.ai)" ;;
      anthropic_key_2) fmt="  2. Create an account / sign in" ;;
      anthropic_key_3) fmt="  3. Create a new key from 'API Keys' in the left menu" ;;
      anthropic_key_4) fmt="  4. Add a small credit charge under 'Billing' (pay-as-you-go)" ;;
      anthropic_key_note) fmt="Note: this is not the password you use to sign in to claude.ai." ;;
      anthropic_key_hint) fmt="The API key is the long string starting with 'sk-ant-api03-'." ;;
      paste_key) fmt="Paste your API key and press Enter (it won't be shown on screen): " ;;
      err_empty_key) fmt="Error: nothing was entered. Please run this again." ;;
      err_placeholder) fmt="Error: found '<' or '>' in the key." ;;
      err_placeholder2) fmt="Did you accidentally paste the placeholder brackets from the instructions too?" ;;
      err_placeholder3) fmt="Please paste just the key value, without those brackets." ;;
      warn_gemini_prefix) fmt="Warning: it doesn't start with 'AIza'. Please check you copied it correctly (continuing anyway)." ;;
      warn_anthropic_prefix) fmt="Warning: it doesn't start with 'sk-ant-api'. Did you paste your claude.ai password by mistake? (continuing anyway)" ;;
      warn_short_key) fmt="Warning: the key is only %s characters. Did the copy get cut off?" ;;
      saved_key) fmt="Saved to %s (readable only by your account)" ;;
      placed_files) fmt="Placed claude-agent.pl / models.txt / advisor_gui.py in %s." ;;
      created_wrapper) fmt="Created %s." ;;
      removed_old_wrapper) fmt="Removed the old %s." ;;
      added_path) fmt="Added %s to PATH." ;;
      installed_completion) fmt="Installed bash completion (%s)." ;;
      path_effective) fmt="(Takes effect next login. To use it now, run 'source ~/.bash_profile' or open a new Terminal window.)" ;;
      no_python3) fmt="python3 was not found, so skipping the Advisor.app build." ;;
      created_app) fmt="Created %s (double-click to launch the GUI; no Terminal window opens)." ;;
      created_app_hint) fmt="  Drag it into the Dock or onto your Desktop for one-click access next time." ;;
      building_app) fmt="Building Advisor.app (first time may take a minute)..." ;;
      building_app_clt) fmt="Installing Xcode Command Line Tools (one-time, ~190MB, needed to sign the app)..." ;;
      app_build_fallback) fmt="Couldn't build the proper app bundle, so using the simple version instead (menu bar will show \"Python\" as the app name)." ;;
      checking_api) fmt="Checking the connection to the API..." ;;
      api_ok) fmt="Connection OK. You're all set." ;;
      usage_intro) fmt="Usage: just type 'advisor' in Terminal." ;;
      usage_help) fmt="  advisor --help            show all options" ;;
      usage_select) fmt="  advisor --select-model    choose which AI to use" ;;
      usage_model) fmt="  advisor -m <ID>           use a different AI for this session only" ;;
      usage_switch) fmt="  (during a conversation, switch AI with /claude or /gemini)" ;;
      api_error) fmt="API error (HTTP %s). Please check that the key is correct, and" ;;
      api_error_gemini) fmt="check in AI Studio that the key is active." ;;
      api_error_anthropic) fmt="check in the Console that credit has been charged." ;;
      api_error_body) fmt="--- Response from the server ---" ;;
    esac
  fi
  if [ -z "$fmt" ]; then
    case "$key" in
      tier_a) fmt="Tier A toolchain (~/claude-toolchain) が見つかりました。こちらを使います。" ;;
      stock_curl) fmt="標準のcurlを使います(Mavericks以降はTLS1.2対応済みのため追加ビルド不要)。" ;;
      title) fmt="=== high_sierra_claude (advisor) セットアップ ===" ;;
      ask_provider) fmt="どちらのAIを使いますか?" ;;
      opt_gemini) fmt="  1) Gemini (Google)   — 無料枠あり・クレジットカード不要        [既定]" ;;
      opt_anthropic) fmt="  2) Anthropic (Claude) — 高性能・従量課金(要クレジットチャージ)" ;;
      enter_number) fmt="番号を入力 [1]: " ;;
      using_provider) fmt="→ %s を使います。" ;;
      reuse_key) fmt="保存済みの %s をそのまま使います。" ;;
      reuse_key_hint) fmt="別のキーに変えたい場合は 'rm %s' してから再実行してください。" ;;
      gemini_key_intro) fmt="Gemini APIキーが必要です。まだお持ちでない場合:" ;;
      gemini_key_1) fmt="  1. https://aistudio.google.com/apikey を開く" ;;
      gemini_key_2) fmt="  2. Googleアカウントでログイン" ;;
      gemini_key_3) fmt="  3. 'Create API key' でキーを発行(無料枠を使う分にはカード登録不要)" ;;
      gemini_key_hint) fmt="'AIza' で始まる文字列がAPIキーです。" ;;
      anthropic_key_intro) fmt="Anthropic APIキーが必要です。まだお持ちでない場合:" ;;
      anthropic_key_1) fmt="  1. https://console.anthropic.com/ を開く (claude.aiとは別サイトです)" ;;
      anthropic_key_2) fmt="  2. アカウントを作成 / ログイン" ;;
      anthropic_key_3) fmt="  3. 左メニューの 'API Keys' から新しいキーを発行" ;;
      anthropic_key_4) fmt="  4. 'Billing' で少額のクレジットをチャージ(従量課金)" ;;
      anthropic_key_note) fmt="注意: claude.aiにログインする時のパスワードとは別物です。" ;;
      anthropic_key_hint) fmt="'sk-ant-api03-' で始まる長い文字列がAPIキーです。" ;;
      paste_key) fmt="APIキーを貼り付けてEnter(画面には表示されません): " ;;
      err_empty_key) fmt="エラー: 何も入力されませんでした。もう一度実行してください。" ;;
      err_placeholder) fmt="エラー: '<' か '>' が含まれています。" ;;
      err_placeholder2) fmt="説明文のプレースホルダー記号を誤って一緒に貼り付けていませんか?" ;;
      err_placeholder3) fmt="記号を含めず、キーの値だけを貼り付けてください。" ;;
      warn_gemini_prefix) fmt="警告: 'AIza' で始まっていません。貼り付けミスがないか確認してください(このまま続けます)。" ;;
      warn_anthropic_prefix) fmt="警告: 'sk-ant-api' で始まっていません。claude.aiのパスワードなどを貼り付けていませんか?(このまま続けます)" ;;
      warn_short_key) fmt="警告: キーが %s 文字しかありません。コピーが途中で切れていませんか?" ;;
      saved_key) fmt="%s に保存しました(あなたのアカウントだけが読めるファイルです)" ;;
      placed_files) fmt="%s に claude-agent.pl / models.txt / advisor_gui.py を配置しました。" ;;
      created_wrapper) fmt="%s を作成しました。" ;;
      removed_old_wrapper) fmt="旧 %s を削除しました。" ;;
      added_path) fmt="PATHに %s を追加しました。" ;;
      installed_completion) fmt="bash補完を設置しました(%s)。" ;;
      path_effective) fmt="(次回ログインから有効。今すぐ使うには 'source ~/.bash_profile' を実行するか、新しいターミナルを開いてください)" ;;
      no_python3) fmt="python3 が見つからないため Advisor.app の生成はスキップします。" ;;
      created_app) fmt="%s を作成しました（ダブルクリックで GUI が起動。ターミナルは開きません）。" ;;
      created_app_hint) fmt="  Dock やデスクトップにドラッグしておくと次回から一発です。" ;;
      building_app) fmt="Advisor.app をビルドしています(初回は少し時間がかかります)..." ;;
      building_app_clt) fmt="Xcode Command Line Tools を導入しています(初回のみ・約190MB、アプリの署名に必要です)..." ;;
      app_build_fallback) fmt="正式なアプリとしてビルドできなかったため、簡易版で作成します(メニューバーのアプリ名は「Python」のままになります)。" ;;
      checking_api) fmt="APIへの疎通を確認しています..." ;;
      api_ok) fmt="疎通確認OK。準備完了です。" ;;
      usage_intro) fmt="使い方: ターミナルで 'advisor' と打つだけです。" ;;
      usage_help) fmt="  advisor --help            オプション一覧" ;;
      usage_select) fmt="  advisor --select-model    使うモデルを選ぶ" ;;
      usage_model) fmt="  advisor -m <ID>           このセッションだけモデルを指定" ;;
      usage_switch) fmt="  (会話中に /claude・/gemini でAIを切り替え)" ;;
      api_error) fmt="APIエラー(HTTP %s)。キーが正しいか、" ;;
      api_error_gemini) fmt="AI Studio でキーが有効か確認してください。" ;;
      api_error_anthropic) fmt="Console でクレジットがチャージされているか確認してください。" ;;
      api_error_body) fmt="--- サーバーからの応答 ---" ;;
      *) fmt="$key" ;;
    esac
  fi
  if [ $# -gt 0 ]; then
    printf -- "$fmt\n" "$@"
  else
    printf '%s\n' "$fmt"
  fi
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$HOME/.claude-agent-env"
BUILD_DIR="$HOME/claude-build"
BIN_DIR="$HOME/bin"
COMPLETION_FILE="$HOME/.advisor-completion.bash"
APP_PATH="$HOME/Applications/Advisor.app"
ICON_SRC="$SCRIPT_DIR/launcher/advisor.icns"

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
  msg tier_a
else
  CURL_BIN="curl"
  CACERT=""
  msg stock_curl
fi
echo ""

msg title
echo ""

# 既存の設定を読み込んでおく(キーの使い回し判定に使う)
[ -f "$ENV_FILE" ] && . "$ENV_FILE" 2>/dev/null || true

# --- 1. 使うAIを選ぶ ---
msg ask_provider
msg opt_gemini
msg opt_anthropic
printf "$(msg enter_number)"
read -r PROVIDER_CHOICE
PROVIDER_CHOICE="${PROVIDER_CHOICE:-1}"

if [ "$PROVIDER_CHOICE" = "2" ]; then
  PROVIDER="anthropic"
  KEY_VAR="ANTHROPIC_API_KEY"
else
  PROVIDER="gemini"
  KEY_VAR="GEMINI_API_KEY"
fi
msg using_provider "$PROVIDER"
echo ""

# --- 2. APIキー ---
# 既にそのプロバイダのキーが保存済みなら、それを使う
EXISTING_KEY="$(eval "printf '%s' \"\${$KEY_VAR}\"")"
if [ -n "$EXISTING_KEY" ]; then
  msg reuse_key "$KEY_VAR"
  msg reuse_key_hint "$ENV_FILE"
  API_KEY="$EXISTING_KEY"
  echo ""
else
  if [ "$PROVIDER" = "gemini" ]; then
    msg gemini_key_intro
    msg gemini_key_1
    msg gemini_key_2
    msg gemini_key_3
    echo ""
    msg gemini_key_hint
  else
    msg anthropic_key_intro
    msg anthropic_key_1
    msg anthropic_key_2
    msg anthropic_key_3
    msg anthropic_key_4
    echo ""
    msg anthropic_key_note
    msg anthropic_key_hint
  fi
  echo ""

  printf "$(msg paste_key)"
  stty -echo 2>/dev/null || true
  read -r API_KEY
  stty echo 2>/dev/null || true
  echo ""

  API_KEY=$(echo "$API_KEY" | sed 's/^[ \t]*//;s/[ \t]*$//')

  if [ -z "$API_KEY" ]; then
    msg err_empty_key
    exit 1
  fi

  case "$API_KEY" in
    \<*|*\>)
      msg err_placeholder
      msg err_placeholder2
      msg err_placeholder3
      exit 1
      ;;
  esac

  if [ "$PROVIDER" = "gemini" ]; then
    case "$API_KEY" in
      AIza*) ;;
      *) msg warn_gemini_prefix ;;
    esac
  else
    case "$API_KEY" in
      sk-ant-api*) ;;
      *) msg warn_anthropic_prefix ;;
    esac
  fi

  key_len=$(echo -n "$API_KEY" | wc -c | tr -d ' ')
  if [ "$key_len" -lt 30 ]; then
    msg warn_short_key "$key_len"
  fi

  upsert_env "$KEY_VAR" "$API_KEY"
  msg saved_key "$ENV_FILE"
  echo ""
fi

upsert_env "CLAUDE_PROVIDER" "$PROVIDER"

# --- 3. エージェント本体を配置 ---
mkdir -p "$BUILD_DIR"
cp "$SCRIPT_DIR/agent/claude-agent.pl" "$BUILD_DIR/claude-agent.pl"
cp "$SCRIPT_DIR/models.txt" "$BUILD_DIR/models.txt"
[ -f "$SCRIPT_DIR/gui/advisor_gui.py" ] && cp "$SCRIPT_DIR/gui/advisor_gui.py" "$BUILD_DIR/advisor_gui.py"
[ -f "$SCRIPT_DIR/launcher/advisor.png" ] && cp "$SCRIPT_DIR/launcher/advisor.png" "$BUILD_DIR/advisor.png"
msg placed_files "$BUILD_DIR"

# --- 4. advisor コマンド(ラッパー)の設置 ---
mkdir -p "$BIN_DIR"
WRAP_IS_EN="$IS_EN"
cat > "$BIN_DIR/advisor" << WRAPEOF
#!/bin/bash
# advisor — high_sierra_claude ラッパーコマンド (setup.sh が自動生成)
set -e

ENV_FILE="$ENV_FILE"
MODELS_FILE="$BUILD_DIR/models.txt"
AGENT_SCRIPT="$BUILD_DIR/claude-agent.pl"
CURL_BIN="$CURL_BIN"
CACERT="$CACERT"
# CLAUDE_LANG=en/ja がその場で指定されていればそちらを優先し、
# 無ければセットアップ時に判定した言語を使う。
case "\${CLAUDE_LANG:-}" in
  en) IS_EN=1 ;;
  ja) IS_EN=0 ;;
  *) IS_EN="$WRAP_IS_EN" ;;
esac

# 端末の文字コードを UTF-8 に固定する。これが C ロケール等になっていると、
# 素の行入力(canonical mode)で日本語1文字(3バイト)をtty側が1バイト単位で
# 扱ってしまい、Backspace でカーソルと文字の位置がずれる・数文字先を消す、
# という現象になる。Terminal の設定に依存せず必ず UTF-8 にする。
if [ -z "\$LANG" ] || [ "\${LANG#*.}" = "\$LANG" ]; then
  export LANG="ja_JP.UTF-8"
fi
export LC_CTYPE="\${LC_CTYPE:-\$LANG}"

source "\$ENV_FILE"

show_help() {
  if [ "\$IS_EN" = "1" ]; then
    cat <<EOF
Usage: advisor [option]

  -h, --help              show this help
      --version           show the version
      --select-model [N]  choose which AI to use; add a number to decide right away (e.g. advisor --select-model 3)
      --list-models       list the available AIs
  -m, --model <ID>        use a different AI for this session only
      --list-history      list saved conversations (needs your passphrase)
      --resume            pick a saved conversation and continue it
      --no-history        don't save this conversation (and don't ask for a passphrase)
      --change-passphrase change the history passphrase
      --set-recovery      set a recovery question (used if you forget your passphrase)

Run with no arguments to start with your saved settings.
Switch AI anytime by typing its number at the prompt (type /model to see the list again).
To pick one from the shell instead, use --select-model [N].
Conversations are encrypted and saved to ~/.claude-agent/history by default
(you set a passphrase on first run; a recovery question is optional).
EOF
  else
    cat <<EOF
使い方: advisor [オプション]

  -h, --help              このヘルプを表示
      --version           バージョンを表示
      --select-model [番号] 使うAIを選ぶ。番号を付ければ即決定 (例: advisor --select-model 3)
      --list-models       使えるAIの一覧を表示
  -m, --model <ID>        今回だけ別のAIで起動
      --list-history      保存済みの会話を一覧表示 (パスフレーズが必要)
      --resume            保存済みの会話を選んで続きから再開
      --no-history        今回は会話を保存しない (パスフレーズも尋ねない)
      --change-passphrase 履歴パスフレーズを変更
      --set-recovery      合言葉 (パスフレーズを忘れたとき用の秘密の質問) を設定

引数なしで実行すると、保存済みの設定で起動します。
使うAIは、起動後に一覧の番号を入力するだけで切り替わります(一覧の再表示は /model)。
シェルから決めたいときは --select-model [番号]。
会話は既定で ~/.claude-agent/history に暗号化保存されます
(初回起動時にパスフレーズを設定。合言葉も任意で設定できます)。
EOF
  fi
}

list_models() {
  # models.txt は id|日本語説明|English description。IS_ENに応じて列を選ぶ。
  if [ "\$IS_EN" = "1" ]; then
    awk -F'|' '{printf "  %-32s %s\n", \$1, (\$3 != "" ? \$3 : \$2)}' "\$MODELS_FILE"
  else
    awk -F'|' '{printf "  %-32s %s\n", \$1, \$2}' "\$MODELS_FILE"
  fi
}

# id が gemini... なら gemini、それ以外は anthropic
provider_of() {
  case "\$1" in gemini*) echo gemini ;; *) echo anthropic ;; esac
}

# 使うAIを選ぶ。引数に番号があれば非対話。CLAUDE_MODEL と CLAUDE_PROVIDER を
# セットで書き換えるので「Geminiのモデルを選んだのに中身はClaudeのまま」が起きない。
select_model() {
  local want="\$1"
  local i=1
  local ids=()
  if [ "\$IS_EN" = "1" ]; then echo "Choose which AI to use:"; else echo "使うAIを選んでください:"; fi
  while IFS='|' read -r id desc_ja desc_en; do
    local desc="\$desc_ja"
    if [ "\$IS_EN" = "1" ] && [ -n "\$desc_en" ]; then desc="\$desc_en"; fi
    printf "  %d) %s\n" "\$i" "\$desc"
    ids[\$i]="\$id"
    i=\$((i+1))
  done < "\$MODELS_FILE"
  local choice="\$want"
  if [ -z "\$choice" ]; then
    if [ "\$IS_EN" = "1" ]; then printf "Enter a number [1]: "; else printf "番号を入力 [1]: "; fi
    read -r choice
  fi
  choice=\${choice:-1}
  local chosen="\${ids[\$choice]}"
  if [ -z "\$chosen" ]; then
    if [ "\$IS_EN" = "1" ]; then echo "Invalid choice."; else echo "無効な選択です。"; fi
    exit 1
  fi
  local prov
  prov="\$(provider_of "\$chosen")"
  grep -v -e '^export CLAUDE_MODEL=' -e '^export CLAUDE_PROVIDER=' "\$ENV_FILE" > "\$ENV_FILE.tmp" 2>/dev/null || true
  mv "\$ENV_FILE.tmp" "\$ENV_FILE"
  echo "export CLAUDE_MODEL=\$chosen" >> "\$ENV_FILE"
  echo "export CLAUDE_PROVIDER=\$prov" >> "\$ENV_FILE"
  chmod 600 "\$ENV_FILE"
  if [ "\$IS_EN" = "1" ]; then echo "→ Using \$chosen."; else echo "→ \$chosen を使います。"; fi
  local keyvar=ANTHROPIC_API_KEY
  [ "\$prov" = gemini ] && keyvar=GEMINI_API_KEY
  if ! grep -q "^export \$keyvar=" "\$ENV_FILE"; then
    local slash=claude
    [ "\$prov" = gemini ] && slash=gemini
    if [ "\$IS_EN" = "1" ]; then
      echo "※ You don't have a key for this AI yet. Run 'advisor' and type /\$slash to register one."
    else
      echo "※ このAIのキーがまだありません。'advisor' を起動して /\$slash と打つと登録できます。"
    fi
  fi
}

PERL_ARGS=()
while [ \$# -gt 0 ]; do
  raw="\$1"
  # ダッシュの数(- でも -- でも無しでも)や大文字小文字を気にしなくて
  # いいように正規化してから判定する。--version か -version か version か、で
  # 迷って挫折しないように。
  norm="\$(printf '%s' "\$raw" | sed 's/^-*//' | tr 'A-Z' 'a-z')"
  case "\$norm" in
    "") shift ;;
    h|help|"?") show_help; exit 0 ;;
    v|version) echo "advisor (high_sierra_claude) 0.1"; exit 0 ;;
    list-models|listmodels|models) list_models; exit 0 ;;
    select-model|selectmodel|select)
      # 設定だけして終了する(起動は次に 'advisor' と打てばよい)
      if [ -n "\$2" ] && [ "\$2" -eq "\$2" ] 2>/dev/null; then
        select_model "\$2"
      else
        select_model
      fi
      exit 0
      ;;
    [0-9]|[0-9][0-9])
      # 「advisor 3」= 3番のAIにして起動
      select_model "\$norm"; shift ;;
    gui|window|app)
      PERL_ARGS[\${#PERL_ARGS[@]}]="--gui"; shift ;;
    list-history|listhistory|history|log)
      PERL_ARGS[\${#PERL_ARGS[@]}]="--list-history"; shift ;;
    resume|continue|cont)
      PERL_ARGS[\${#PERL_ARGS[@]}]="--resume"; shift ;;
    change-passphrase|changepassphrase|passphrase|password)
      PERL_ARGS[\${#PERL_ARGS[@]}]="--change-passphrase"; shift ;;
    set-recovery|setrecovery|recovery)
      PERL_ARGS[\${#PERL_ARGS[@]}]="--set-recovery"; shift ;;
    no-history|nohistory|nohist)
      export CLAUDE_NO_HISTORY=1; shift ;;
    m|model)
      export CLAUDE_MODEL="\$2"
      case "\$2" in
        gemini*) export CLAUDE_PROVIDER=gemini ;;
        claude*) export CLAUDE_PROVIDER=anthropic ;;
      esac
      shift 2
      ;;
    *)
      if [ "\$IS_EN" = "1" ]; then
        echo "That option wasn't recognized. Usually you can just run:" >&2
        echo "  advisor            start (this is usually all you need)" >&2
        echo "  advisor version    show the version" >&2
        echo "  advisor help       detailed usage" >&2
        echo "(the leading - is optional either way)" >&2
      else
        echo "そのオプションは分かりませんでした。ふつうは何も付けずに:" >&2
        echo "  advisor            起動する(たいていこれだけでOK)" >&2
        echo "  advisor version    バージョンを表示" >&2
        echo "  advisor help       詳しい使い方" >&2
        echo "(ダッシュ - は付けても付けなくてもかまいません)" >&2
      fi
      exit 1
      ;;
  esac
done

export CLAUDE_CURL="\$CURL_BIN"
[ -n "\$CACERT" ] && export CLAUDE_CACERT="\$CACERT"
export CLAUDE_MODELS_FILE="\$MODELS_FILE"
if [ \${#PERL_ARGS[@]} -gt 0 ]; then
  exec perl "\$AGENT_SCRIPT" "\${PERL_ARGS[@]}"
else
  exec perl "\$AGENT_SCRIPT"
fi
WRAPEOF
chmod +x "$BIN_DIR/advisor"
msg created_wrapper "$BIN_DIR/advisor"
# 旧名(claude)が残っていれば片付ける
[ -e "$BIN_DIR/claude" ] && rm -f "$BIN_DIR/claude" && msg removed_old_wrapper "$BIN_DIR/claude"

if ! grep -qF 'export PATH=$HOME/bin:$PATH' "$HOME/.bash_profile" 2>/dev/null; then
  echo "export PATH=\$HOME/bin:\$PATH" >> "$HOME/.bash_profile"
  msg added_path "$BIN_DIR"
fi

# --- 5. bash補完の設置 ---
cp "$SCRIPT_DIR/completion/advisor-completion.bash" "$COMPLETION_FILE"
if ! grep -qF "source $COMPLETION_FILE" "$HOME/.bash_profile" 2>/dev/null; then
  echo "source $COMPLETION_FILE" >> "$HOME/.bash_profile"
  msg installed_completion "$COMPLETION_FILE"
fi
# 旧補完(claude)の後始末
if [ -f "$HOME/.claude-completion.bash" ]; then
  grep -v "source $HOME/.claude-completion.bash" "$HOME/.bash_profile" > "$HOME/.bash_profile.tmp" 2>/dev/null && mv "$HOME/.bash_profile.tmp" "$HOME/.bash_profile" || true
  rm -f "$HOME/.claude-completion.bash"
fi
msg path_effective
echo ""

# --- 6. ダブルクリック用 Advisor.app (GUI) の生成 ---
# py2appで単体アプリとしてビルドする。python3を直接execするだけの簡易版だと
# メニューバー/DockにOS標準の「Python」という表示が出てしまう(python.org
# 配布のpython3実行ファイル自体にその名前が埋め込まれており、シェルスクリプト
# 経由のexecでは上書きできないため)。py2appでビルドすると実行ファイル自体が
# バンドル内に生成され、正しく「Advisor」と表示される。
# ビルドに失敗した場合(ネットワーク不通など)は簡易版にフォールバックする
# (動作は変わらず、メニューバー表示だけ「Python」のままになる)。
PY3="$(command -v python3 || true)"
[ -z "$PY3" ] && [ -x /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 ] \
  && PY3=/Library/Frameworks/Python.framework/Versions/3.10/bin/python3
[ -z "$PY3" ] && PY3=/usr/bin/python3

build_advisor_app_simple() {
  mkdir -p "$APP_PATH/Contents/MacOS" "$APP_PATH/Contents/Resources"
  cat > "$APP_PATH/Contents/MacOS/Advisor" << APPEOF
#!/bin/bash
export PATH="\$HOME/bin:/usr/local/bin:/usr/bin:/bin"
exec "$PY3" "\$HOME/claude-build/advisor_gui.py"
APPEOF
  chmod +x "$APP_PATH/Contents/MacOS/Advisor"
  cat > "$APP_PATH/Contents/Info.plist" << 'PLISTEOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Advisor</string>
  <key>CFBundleDisplayName</key><string>Advisor</string>
  <key>CFBundleIdentifier</key><string>com.high-sierra-claude.advisor</string>
  <key>CFBundleVersion</key><string>0.1</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Advisor</string>
  <key>CFBundleIconFile</key><string>advisor.icns</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLISTEOF
  printf 'APPL????' > "$APP_PATH/Contents/PkgInfo"
  [ -f "$ICON_SRC" ] && cp "$ICON_SRC" "$APP_PATH/Contents/Resources/advisor.icns"
}

build_advisor_app_py2app() {
  # コード署名にXcode Command Line Toolsが要る。無ければその場で導入する
  # (softwareupdateはこの用途では管理者権限が無くても実行できる)。
  if ! xcode-select -p >/dev/null 2>&1; then
    msg building_app_clt
    touch /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
    local clt_label
    clt_label="$(softwareupdate -l 2>/dev/null | grep -o 'Command Line Tools[^,]*for Xcode-[0-9.]*' | tail -1)"
    [ -n "$clt_label" ] && softwareupdate -i "$clt_label" >/dev/null 2>&1
    rm -f /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
    xcode-select -p >/dev/null 2>&1 || return 1
  fi

  # pyobjc-framework-Cocoa はメニューバーのAbout/隠す/サービス/終了といった
  # Tk自身が固定の英語文字列で自動生成する項目を、OSのネイティブメニューへ
  # 直接アクセスして日本語化するために使う(advisor_gui.py側で使用)。
  "$PY3" -m pip install --user --quiet py2app pyobjc-framework-Cocoa \
    >/tmp/advisor-py2app-install.log 2>&1 || return 1

  local build_dir="$HOME/.advisor-app-build"
  mkdir -p "$build_dir"
  local iconfile_opt=""
  [ -f "$ICON_SRC" ] && iconfile_opt="\"iconfile\": \"$ICON_SRC\","
  cat > "$build_dir/setup.py" << PYEOF
from setuptools import setup
APP = ["$HOME/claude-build/advisor_gui.py"]
OPTIONS = {
    "argv_emulation": False,
    $iconfile_opt
    "plist": {
        "CFBundleName": "Advisor",
        "CFBundleDisplayName": "Advisor",
        "CFBundleIdentifier": "com.high-sierra-claude.advisor",
        "CFBundleVersion": "0.1",
        "CFBundleShortVersionString": "0.1",
        "NSHighResolutionCapable": True,
    },
}
setup(app=APP, options={"py2app": OPTIONS}, setup_requires=["py2app"])
PYEOF
  ( cd "$build_dir" && rm -rf build dist && "$PY3" setup.py py2app -A ) \
    >/tmp/advisor-py2app-build.log 2>&1 || return 1
  [ -d "$build_dir/dist/Advisor.app" ] || return 1

  rm -rf "$APP_PATH"
  mkdir -p "$HOME/Applications"
  cp -R "$build_dir/dist/Advisor.app" "$APP_PATH"
}

if [ -n "$PY3" ]; then
  mkdir -p "$HOME/Applications"
  rm -rf "$HOME/Applications/Claude.app"
  msg building_app
  if ! build_advisor_app_py2app; then
    msg app_build_fallback
    rm -rf "$APP_PATH"
    build_advisor_app_simple
  fi
  touch "$APP_PATH"

  msg created_app "$APP_PATH"
  msg created_app_hint
else
  msg no_python3
fi
echo ""

# --- 7. 疎通確認 ---
msg checking_api
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
  msg api_ok
  echo ""
  msg usage_intro
  msg usage_help
  msg usage_select
  msg usage_model
  msg usage_switch
else
  msg api_error "$HTTP_CODE"
  if [ "$PROVIDER" = "gemini" ]; then
    msg api_error_gemini
  else
    msg api_error_anthropic
  fi
  msg api_error_body
  cat "$RESPONSE_FILE"
  echo ""
fi
rm -f "$RESPONSE_FILE"
