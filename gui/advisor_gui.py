#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
advisor_gui.py  ―  advisor の1画面GUIフロントエンド

裏で `advisor gui`(= perl claude-agent.pl --gui)を起動し、1行1件のJSONで
やり取りする。入力はノート下部の書き込み欄(OSの日本語入力がそのまま
普通に使える。Terminal.app の2バイト文字バグを回避できる)、質問と回答は
1枚のノートに交互に追記されていく(枠付きの入力ボックスは無い)。

見た目は2つ:
  - ノート : 生成りの紙に書いていく感じ。相手の返答は2文字ぶん字下げ。
  - ハッカー: 黒地に緑文字。

必要なもの: Python 3.x + tkinter(標準同梱)のみ。外部ライブラリ不要。
"""

import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import font as tkfont
from tkinter import messagebox

# 本文の左インセット(px)。ノート左の赤い縦罫(大学ノートの余白線)の
# すぐ右から書き始める、という要望に合わせた小さめの値。
EDGE = 10

# ---------- 言語 ----------
# ダウンロードの7割が海外ユーザーとのことで日英対応が必須になった。
# LANG環境変数はGUIアプリをダブルクリック起動した時に空になることが
# あり(ログインシェルを経由しないため)あてにできない。macOS自体の
# 言語設定を直接読む。判定できなければ、この項目の既存ユーザーに
# 合わせて日本語を既定にする。ボタン文字は _S/L() で切り替えるだけで
# レイアウト(padx等)自体は変えていないので、英語の方が長い/短い場合は
# 別途ヘッダーの余白調整が要るかもしれない。
def _detect_lang():
    # CLAUDE_LANG=en/ja があれば最優先(システム言語を変えずに英語表示を
    # 確認したいとき用)。
    override = os.environ.get("CLAUDE_LANG", "").strip().lower()
    if override in ("en", "ja"):
        return override
    try:
        out = subprocess.check_output(
            ["defaults", "read", "-g", "AppleLocale"],
            stderr=subprocess.DEVNULL, timeout=2,
        ).decode("utf-8", "replace").strip()
        if out and not out.lower().startswith("ja"):
            return "en"
    except Exception:
        pass
    return "ja"


LANG = _detect_lang()

# key: (日本語, English)。フォーマット文字列は L(key, **kwargs) で埋める。
_S = {
    "tab_chat": ("会話", "Chat"),
    "tab_cmd": ("コマンド", "Cmd"),
    "hist_btn": ("続きから", "Resume"),
    "switch_btn": ("AIを切替 ▾", "Switch AI ▾"),
    "stop_btn": ("中止", "Stop"),
    "write_mark": ("▶ ここに書いてください（Enterで送信）",
                   "▶ Type here (Enter to send)"),
    "busy_running": ("(実行中です。中止 ボタンか Ctrl-C で止めてください)\n",
                      "(Already running. Use Stop or Ctrl-C.)\n"),
    "no_such_folder": ("cd: そのフォルダはありません: {path}\n",
                        "cd: no such folder: {path}\n"),
    "cannot_run": ("実行できません: {err}\n", "Could not run: {err}\n"),
    "history_encrypted": ("暗号化保存", "encrypted"),
    "history_off": ("保存しない", "off"),
    "ready_status": ("準備完了（履歴: {hist}）", "Ready (history: {hist})"),
    "using_tool": ("— {name} を使います —", "— using {name} —"),
    "confirm_title": ("確認", "Confirm"),
    "confirm_body": ("AIが次のことをしようとしています:\n\n{prompt}\n\n許可しますか？",
                      "The AI wants to do the following:\n\n{prompt}\n\nAllow it?"),
    "passphrase_default": ("パスフレーズ", "Passphrase"),
    "turn_end": ("[終了 {code}]\n", "[exit {code}]\n"),
    "bye_status": ("advisor を終了しました", "advisor has exited"),
    "querying_status": ("問い合わせ中…", "Thinking…"),
    "starting_status": ("起動中…", "Starting…"),
    "currently_using": ("  ← 使用中", "  ← current"),
    "passphrase_title": ("パスフレーズ", "Passphrase"),
    "ok": ("OK", "OK"),
    "recover_with_answer": ("合言葉で復旧", "Recover with answer"),
    "secret_title": ("合言葉", "Recovery answer"),
    "secret_new_body": ("パスフレーズを忘れたときの復旧用です(必須)。\n"
                         "あなたにしか答えられない質問にしてください。\n"
                         "例: 初めて買った車の名前は？",
                         "Used to recover if you forget your passphrase "
                         "(required).\nPick a question only you can answer.\n"
                         "Example: What was your first car?"),
    "question_label": ("質問", "Question"),
    "secret_unlock_body": ("合言葉で履歴を復旧します。", "Recover history with your answer."),
    "question_prefix": ("質問: {q}", "Question: {q}"),
    "answer_label": ("答え", "Answer"),
    "resume_title": ("続きから", "Resume"),
    "no_saved_history": ("保存された会話がありません。", "No saved conversations."),
    "resume_pick": ("続きから始める会話を選んでください", "Choose a conversation to resume"),
    "open": ("開く", "Open"),
    "cancel": ("やめる", "Cancel"),
    "resume_page": ("（{page}ページ目 / 全{total}ページ）", "(page {page} of {total})"),
    "resume_loaded": ("（ここまで読み込みました。続きをどうぞ）",
                       "(loaded up to here — continue below)"),
    "cannot_start_title": ("起動できません", "Could not start"),
    "cannot_start_body": ("advisor を起動できませんでした:\n{err}",
                          "Could not start advisor:\n{err}"),
    "internal_error": ("(内部エラー: {err})", "(internal error: {err})"),
    # macOS メニューバー(画面最上部のOSメニュー。アプリ内ヘッダーとは別物)
    "menu_edit": ("編集", "Edit"),
    "menu_cut": ("切り取り", "Cut"),
    "menu_copy": ("コピー", "Copy"),
    "menu_paste": ("貼り付け", "Paste"),
    "menu_select_all": ("すべてを選択", "Select All"),
    "menu_window": ("ウインドウ", "Window"),
    "menu_minimize": ("しまう", "Minimize"),
    # 初回起動時、APIキー未登録のときに出す案内画面
    "onboard_intro": (
        "はじめまして。Advisorを使うには、Gemini(無料)かAnthropic(有料)の"
        "どちらかのAPIキーが必要です。まずはGeminiの無料枠で気軽に始められます。",
        "Welcome. To use Advisor, you'll need an API key from either Gemini "
        "(free) or Anthropic (paid). Gemini's free tier is a good way to "
        "start without any cost.",
    ),
    "onboard_gemini": ("Gemini(無料)", "Gemini (free)"),
    "onboard_anthropic": ("Anthropic(有料)", "Anthropic (paid)"),
    "onboard_key_label": ("APIキー:", "API key:"),
    "onboard_start": ("はじめる", "Get Started"),
    "onboard_checking": ("確認しています…", "Checking…"),
    "onboard_err_empty": ("APIキーを入力してください。", "Please enter an API key."),
    "onboard_err_api": (
        "APIキーを確認できませんでした(HTTP {code})。キーが正しいかご確認ください。",
        "Couldn't verify the API key (HTTP {code}). Please check that it's correct.",
    ),
}


def L(key, **kw):
    ja, en = _S[key]
    s = en if LANG == "en" else ja
    return s.format(**kw) if kw else s


def theme_label(spec):
    return spec.get("label_en", spec["label"]) if LANG == "en" else spec["label"]


# 書き込み欄が空のときに出す案内。クリックすると全体が消えて先頭から
# 書ける(_write_click_clear)。点滅する縦線のカーソルの代わりに、
# 点滅だけ止めて(insertofftime=0)この矢印で書き始めの位置を示す。
WRITE_MARK = L("write_mark")

CFG_PATH = os.path.expanduser("~/.claude-agent/gui.json")

# ```lang ... ``` のコードブロック検出
FENCE_RE = re.compile(r"```[ \t]*([\w+.\-]*)[ \t]*\n(.*?)```", re.DOTALL)
# ざっくりした汎用ハイライト(python/js/sh/json あたりを想定)。
# 並び順が優先度: 文字列 → コメント → 数値 → キーワード。
CODE_RE = re.compile(r"""
    (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)
  | (?P<com>\#[^\n]*|//[^\n]*|/\*.*?\*/)
  | (?P<num>\b\d+(?:\.\d+)?\b)
  | (?P<kw>\b(?:def|class|return|if|elif|else|for|while|import|from|as|try|
        except|finally|raise|with|lambda|pass|break|continue|yield|True|False|
        None|and|or|not|in|is|async|await|function|const|let|var|new|typeof|
        export|default|extends|super|this|null|undefined|echo|then|fi|do|done|
        case|esac|local|self|print)\b)
""", re.VERBOSE | re.DOTALL)
HL_TAG = {"str": "code_str", "com": "code_com", "num": "code_num", "kw": "code_kw"}

# テーマ定義。レイアウトは全モード共通(読みやすさ優先):
#   自分の発言 = 右寄せ、ブロックの左は 1/3 空ける
#   相手の返答 = 左寄せ、ブロックの右は 1/3 空ける
#   発言の間に薄い区切り線。色・書体・穴だけモードで変える。
#   prompt_prefix = 自分の発言に色付き「watermark> 」を付ける(端末系)
#   handwriting   = 手書き風フォントが入っていれば使う(環境依存)
#   holes         = 左にルーズリーフの穴
THEMES = {
    "paper": {
        "label": "ノート", "label_en": "Note", "handwriting": True, "holes": True,
        # 背景を少し明るく、文字(質問・回答とも)は逆にもう少し濃くして
        # はっきりさせた(明るくした分そのままだとコントラストが落ちる
        # ため。実際にはコントラスト比は上がっている: fg 9.57→12.5,
        # ai 7.74→10.8)。
        "bg": "#faf4e6", "fg": "#1a2c54", "ai": "#463420",   # 青黒インク / 茶
        "dim": "#9a8f78", "err": "#a5341f", "rule": "#d7b7ab", "code_bg": "#efe6cf",
        "line": "#c96b63",                                    # 昔のルーズリーフの赤い罫
        "hline": "#9fb0c9",     # 横罫線(紺グレー)。PhotoImageでの埋め込みは
                                # このマシンで描画されなかったため、既に
                                # 描けている縦罫(Canvas.create_line)と同じ
                                # 実部品(tk.Frame)を使う方式に変更した
        "vline": "#c96b63",                                   # 左の縦罫(赤)。書き始めの目印
        "input_bg": "#faf4e6", "input_fg": "#1a2c54",
        "hl": {"kw": "#7a3b8f", "str": "#8a5a2b", "com": "#9a8f78", "num": "#3a5a3a"},
        "font": ("Hiragino Maru Gothic ProN", 12),  # 少し小さめにして行数を稼ぐ
    },
    "coding": {
        "label": "コーディング", "label_en": "Code", "prompt_prefix": True,
        "bg": "#1e1e1e", "fg": "#d4d4d4", "ai": "#cfcfcf", "prompt": "#c586c0",
        "dim": "#7a7a7a", "err": "#f48771", "rule": "#3a3a3a", "code_bg": "#252526",
        "line": "#3a3a3a", "input_bg": "#1e1e1e", "input_fg": "#d4d4d4",
        "hl": {"kw": "#569cd6", "str": "#ce9178", "com": "#6a9955", "num": "#b5cea8"},
        "font": ("Menlo", 13),
    },
    "hacker": {
        "label": "ハッカー", "label_en": "Hacker", "prompt_prefix": True,
        # エラー/終了コード(err)以外は全部緑にする、との要望。以前は
        # promptとhl.kw/numがシアン系だったので緑に寄せた。
        "bg": "#000000", "fg": "#39ff5a", "ai": "#33dd88", "prompt": "#00ff66",
        "dim": "#2e7d4f", "err": "#ff5555", "rule": "#2e9d55", "code_bg": "#041004",
        "line": "#2e9d55", "input_bg": "#000000", "input_fg": "#39ff5a",
        "hl": {"kw": "#00ff66", "str": "#9dff9d", "com": "#2e7d4f", "num": "#a8ffcb"},
        "font": ("Menlo", 13),
    },
}


def pick_font(family, size):
    """指定 family が無ければ順に代替。手書き風は入っていれば拾う。"""
    try:
        import tkinter.font as tkfont
        have = set(tkfont.families())
    except Exception:
        return (family, size)
    cands = [family,
             "Hiragino Maru Gothic ProN", "YuKyokasho", "Klee",
             "Chalkboard SE", "Hiragino Sans", "ヒラギノ角ゴシック"]
    for c in cands:
        if c in have:
            return (c, size)
    return (family, size)


ENV_FILE_PATH = os.path.expanduser("~/.claude-agent-env")


def read_env_file():
    # ~/.claude-agent-env の "export VAR=値" 形式を辞書にして返す。
    result = {}
    try:
        with open(ENV_FILE_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("export "):
                    continue
                k, sep, v = line[len("export "):].partition("=")
                if sep:
                    result[k.strip()] = v.strip()
    except Exception:
        pass
    return result


def has_valid_api_key():
    env = read_env_file()
    provider = env.get("CLAUDE_PROVIDER", "")
    if provider == "gemini":
        return bool(env.get("GEMINI_API_KEY"))
    if provider == "anthropic":
        return bool(env.get("ANTHROPIC_API_KEY"))
    return False


def _bundled_resource_dir():
    # setup.shでビルドした場合は自分自身(advisor_gui.py)と同じフォルダに
    # claude-agent.pl / models.txt が既にある(~/claude-build/)。
    # ダブルクリックだけで動く単体アプリ(py2appの標準ビルド)の場合は、
    # アプリ本体の Contents/Resources/ に同梱されているはずなのでそちらを探す。
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.isfile(os.path.join(here, "claude-agent.pl")):
        return here
    try:
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        resources = os.path.normpath(os.path.join(exe_dir, "..", "Resources"))
        if os.path.isfile(os.path.join(resources, "claude-agent.pl")):
            return resources
    except Exception:
        pass
    return None


def ensure_backend_files():
    # setup.shを一度も実行していない(=~/claude-buildが無い)環境でも、
    # アプリに同梱したエージェント本体を~/claude-buildへ配置して動くようにする。
    build_dir = os.path.expanduser("~/claude-build")
    target_agent = os.path.join(build_dir, "claude-agent.pl")
    target_models = os.path.join(build_dir, "models.txt")
    if os.path.isfile(target_agent) and os.path.isfile(target_models):
        return True
    src = _bundled_resource_dir()
    if src is None:
        return False
    try:
        os.makedirs(build_dir, exist_ok=True)
        if not os.path.isfile(target_agent):
            shutil.copy(os.path.join(src, "claude-agent.pl"), target_agent)
        if not os.path.isfile(target_models):
            shutil.copy(os.path.join(src, "models.txt"), target_models)
        return True
    except Exception:
        return False


def build_backend_command_and_env():
    # ~/bin/advisor(setup.shが生成するラッパー)があればそれを使う。
    # 無ければ(=setup.shを実行していない)、同梱したエージェントを直接起動する。
    wrapper = os.path.expanduser("~/bin/advisor")
    if os.path.isfile(wrapper) and os.access(wrapper, os.X_OK):
        return [wrapper, "gui"], None
    if not ensure_backend_files():
        return None, None
    env = dict(os.environ)
    env.update(read_env_file())
    env.setdefault("CLAUDE_CURL", "curl")
    env["CLAUDE_MODELS_FILE"] = os.path.expanduser("~/claude-build/models.txt")
    agent = os.path.expanduser("~/claude-build/claude-agent.pl")
    return ["perl", agent, "--gui"], env


def validate_api_key(provider, api_key):
    # setup.shの「疎通確認」と同じチェックをその場で行う。
    if provider == "gemini":
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               "gemini-3.5-flash-lite:generateContent")
        headers = ["-H", "x-goog-api-key: %s" % api_key,
                   "-H", "content-type: application/json"]
        data = '{"contents":[{"parts":[{"text":"hi"}]}],"generationConfig":{"maxOutputTokens":8}}'
    else:
        url = "https://api.anthropic.com/v1/messages"
        headers = ["-H", "x-api-key: %s" % api_key,
                   "-H", "anthropic-version: 2023-06-01",
                   "-H", "content-type: application/json"]
        data = '{"model":"claude-sonnet-5","max_tokens":10,"messages":[{"role":"user","content":"hi"}]}'
    try:
        out = subprocess.run(
            ["curl", "-s", url] + headers + ["-d", data, "-w", "\n%{http_code}"],
            capture_output=True, text=True, timeout=20,
        )
    except Exception:
        return False, ""
    text = out.stdout
    _, _, code = text.rpartition("\n")
    return code.strip() == "200", code.strip()


def save_onboard_env(provider, api_key):
    lines = []
    try:
        with open(ENV_FILE_PATH, encoding="utf-8") as f:
            skip_prefixes = ("export CLAUDE_PROVIDER=", "export GEMINI_API_KEY=",
                              "export ANTHROPIC_API_KEY=", "export CLAUDE_MODEL=")
            lines = [l for l in f if not l.startswith(skip_prefixes)]
    except Exception:
        pass
    keyvar = "GEMINI_API_KEY" if provider == "gemini" else "ANTHROPIC_API_KEY"
    default_model = "gemini-3.5-flash-lite" if provider == "gemini" else "claude-sonnet-5"
    lines.append("export CLAUDE_PROVIDER=%s\n" % provider)
    lines.append("export %s=%s\n" % (keyvar, api_key))
    lines.append("export CLAUDE_MODEL=%s\n" % default_model)
    with open(ENV_FILE_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.chmod(ENV_FILE_PATH, 0o600)


def load_cfg():
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(cfg):
    try:
        os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except Exception:
        pass


class AdvisorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Advisor")
        self.root.geometry("560x800")          # A5 大学ノートの比率(縦長)
        # Dock/ウィンドウのアイコン(できれば)。tkinter だけだと Dock は
        # Python の絵のままのことがあるが、少なくとも試みる。
        try:
            png = os.path.expanduser("~/claude-build/advisor.png")
            if os.path.isfile(png):
                self._icon_img = tk.PhotoImage(file=png)
                self.root.iconphoto(True, self._icon_img)
        except Exception:
            pass

        self.events = queue.Queue()
        self.proc = None
        self.busy = False
        self.pane = "chat"                      # "chat" / "cmd"
        self.cwd = os.path.expanduser("~")      # コマンドパネルの現在地
        self.cmd_proc = None
        self.model_label_var = tk.StringVar(value="…")
        self.status_var = tk.StringVar(value=L("starting_status"))
        self.cmd_prompt_var = tk.StringVar(value="")
        self.theme_name = load_cfg().get("theme", "paper")
        if self.theme_name not in THEMES:
            self.theme_name = "paper"

        self._build_menubar()
        self.root.after(50, self._localize_native_app_menu)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        if has_valid_api_key():
            self._start_main_ui()
        else:
            self._build_onboarding()

    def _start_main_ui(self):
        self._build_ui()
        self._apply_theme(self.theme_name)
        self._write_show_marker()
        self._start_backend()
        self.root.after(80, self._pump)

    # ---------- 初回起動時、APIキー未登録なら出す案内画面 ----------
    def _build_onboarding(self):
        bg = "#fdf6e3"
        self._onboard_provider = tk.StringVar(value="gemini")
        frame = tk.Frame(self.root, bg=bg)
        frame.pack(fill=tk.BOTH, expand=True)
        self._onboard_frame = frame

        tk.Label(frame, text="Advisor", font=("Helvetica", 28, "bold"),
                 bg=bg, fg="#2b2b2b").pack(pady=(48, 6))
        tk.Label(frame, text=L("onboard_intro"), font=("Helvetica", 13),
                 bg=bg, fg="#2b2b2b", wraplength=440, justify=tk.LEFT).pack(
            pady=(0, 20), padx=40)

        provider_row = tk.Frame(frame, bg=bg)
        provider_row.pack(pady=(0, 6))
        tk.Radiobutton(provider_row, text=L("onboard_gemini"),
                        variable=self._onboard_provider, value="gemini", bg=bg,
                        command=self._onboard_update_link,
                        font=("Helvetica", 12)).pack(side=tk.LEFT, padx=8)
        tk.Radiobutton(provider_row, text=L("onboard_anthropic"),
                        variable=self._onboard_provider, value="anthropic", bg=bg,
                        command=self._onboard_update_link,
                        font=("Helvetica", 12)).pack(side=tk.LEFT, padx=8)

        self._onboard_link = tk.Label(frame, text="", fg="#1a5fb4", bg=bg,
                                       cursor="pointinghand",
                                       font=("Helvetica", 11, "underline"))
        self._onboard_link.pack(pady=(0, 18))
        self._onboard_link.bind("<Button-1>", lambda e: webbrowser.open(self._onboard_url))
        self._onboard_update_link()

        key_row = tk.Frame(frame, bg=bg)
        key_row.pack(pady=(0, 10))
        tk.Label(key_row, text=L("onboard_key_label"), bg=bg,
                 font=("Helvetica", 12)).pack(side=tk.LEFT, padx=(0, 6))
        self._onboard_key_entry = tk.Entry(key_row, width=40, show="•",
                                            font=("Helvetica", 12))
        self._onboard_key_entry.pack(side=tk.LEFT)
        self._onboard_key_entry.bind("<Return>", lambda e: self._onboard_start())
        self._onboard_key_entry.focus_set()

        self._onboard_btn = tk.Label(frame, text=L("onboard_start"),
                                      cursor="pointinghand",
                                      font=("Helvetica", 13, "bold"), bg=bg,
                                      fg="#2b2b2b", padx=14, pady=4,
                                      highlightthickness=1,
                                      highlightbackground="#2b2b2b")
        self._onboard_btn.pack(pady=(6, 10))
        self._onboard_btn.bind("<Button-1>", lambda e: self._onboard_start())

        self._onboard_status = tk.Label(frame, text="", bg=bg, fg="#a33",
                                         font=("Helvetica", 11), wraplength=440)
        self._onboard_status.pack(pady=(4, 20))

    def _onboard_update_link(self):
        if self._onboard_provider.get() == "gemini":
            self._onboard_url = "https://aistudio.google.com/apikey"
        else:
            self._onboard_url = "https://console.anthropic.com/"
        self._onboard_link.config(text=self._onboard_url)

    def _onboard_start(self):
        key = self._onboard_key_entry.get().strip()
        if not key:
            self._onboard_status.config(fg="#a33", text=L("onboard_err_empty"))
            return
        provider = self._onboard_provider.get()
        self._onboard_btn.config(state=tk.DISABLED)
        self._onboard_status.config(fg="#2b2b2b", text=L("onboard_checking"))
        threading.Thread(target=self._onboard_validate_thread,
                          args=(provider, key), daemon=True).start()

    def _onboard_validate_thread(self, provider, key):
        ok, code = validate_api_key(provider, key)
        self.root.after(0, lambda: self._onboard_validate_done(ok, code, provider, key))

    def _onboard_validate_done(self, ok, code, provider, key):
        self._onboard_btn.config(state=tk.NORMAL)
        if not ok:
            self._onboard_status.config(fg="#a33", text=L("onboard_err_api", code=code))
            return
        try:
            save_onboard_env(provider, key)
        except Exception as e:
            self._onboard_status.config(fg="#a33", text=L("internal_error", err=e))
            return
        self._onboard_frame.destroy()
        self._start_main_ui()

    # ---------- macOSメニューバー(画面最上部のOSメニュー。アプリ内
    # ヘッダーの[ 会話 ][ コマンド ]等とは別物) ----------
    def _build_menubar(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # 先頭のアプリケーションメニュー(About/隠す/サービス/終了)はTk自身が
        # バンドル名から自動で用意してくれるが、中身の文言はTk本体に
        # コンパイル済みで埋め込まれた固定の英語で、OS言語設定にもここでの
        # 翻訳にも反応しない(setAppleMenu:というCocoaの古いAPIでTkが自分で
        # 登録してしまうため)。自前で"apple"という名前のメニューを追加しても
        # マージされず、空の別メニューが並ぶだけだったので作らない。日本語化は
        # _localize_native_app_menu() でOSネイティブメニューを直接書き換えて
        # 行う。「終了」を選んだ時にきちんと後片付け(_on_close)されるように
        # だけここでフックする。
        self.root.createcommand("tk::mac::Quit", self._on_close)

        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=L("menu_edit"), menu=edit_menu)
        edit_menu.add_command(label=L("menu_cut"), accelerator="Cmd-X",
                               command=lambda: self._menu_gen_event("<<Cut>>"))
        edit_menu.add_command(label=L("menu_copy"), accelerator="Cmd-C",
                               command=lambda: self._menu_gen_event("<<Copy>>"))
        edit_menu.add_command(label=L("menu_paste"), accelerator="Cmd-V",
                               command=lambda: self._menu_gen_event("<<Paste>>"))
        edit_menu.add_separator()
        edit_menu.add_command(label=L("menu_select_all"), accelerator="Cmd-A",
                               command=self._menu_select_all)

        # name="window" にするとTkが項目を自動生成してくれるが、その中身
        # (Minimize/Zoom等)は英語固定で翻訳できない。自前の項目にする。
        window_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=L("menu_window"), menu=window_menu)
        window_menu.add_command(label=L("menu_minimize"), accelerator="Cmd-M",
                                 command=self.root.iconify)

        self.root.createcommand("tk::mac::ReopenApplication", lambda: self.root.deiconify())

    def _menu_gen_event(self, virtual):
        w = self.root.focus_get()
        if w is None:
            return
        try:
            w.event_generate(virtual)
        except Exception:
            pass

    def _menu_select_all(self):
        w = self.root.focus_get()
        if w is None:
            return
        try:
            if isinstance(w, tk.Text):
                w.tag_add("sel", "1.0", "end-1c")
            elif isinstance(w, tk.Entry):
                w.select_range(0, tk.END)
        except Exception:
            pass

    def _localize_native_app_menu(self):
        # Tkが自動生成するアプリケーションメニュー(About/隠す/サービス/終了)
        # の中身は英語固定でTkからは書き換えられない(_build_menubar内の説明
        # 参照)。pyobjc(py2appビルド時のみ同梱)が使える場合だけ、OSの
        # ネイティブメニューを直接書き換えて日本語化する。無い環境では何も
        # せず英語のまま(壊れはしない)。
        if LANG != "ja":
            return
        try:
            from AppKit import NSApplication
        except Exception:
            return
        try:
            main_menu = NSApplication.sharedApplication().mainMenu()
            app_menu = main_menu.itemAtIndex_(0).submenu() if main_menu else None
            if app_menu is None:
                return
            for item in app_menu.itemArray():
                title = str(item.title())
                if title.startswith("About "):
                    item.setTitle_("%s について" % title[len("About "):])
                elif title.startswith("Hide Others"):
                    item.setTitle_("ほかを隠す")
                elif title.startswith("Hide "):
                    item.setTitle_("%s を隠す" % title[len("Hide "):])
                elif title == "Show All":
                    item.setTitle_("すべてを表示")
                elif title == "Services":
                    item.setTitle_("サービス")
                elif title.startswith("Preferences"):
                    item.setTitle_("環境設定…")
                elif title.startswith("Quit "):
                    item.setTitle_("%s を終了" % title[len("Quit "):])
        except Exception:
            pass

    # ---------- 画面 ----------
    def _build_ui(self):
        self.bar = tk.Frame(self.root)
        self.bar.pack(fill=tk.X)

        # ヘッダーのボタン類は tk.Button/Menubutton だと macOS が独自の
        # 見た目(枠付きの部品)を勝手に描いてしまい、relief や色を変えても
        # 反映されない。tk.Label + クリックの組み合わせにすると、Tk自身が
        # 描画するので好きな見た目(会話タブと同じ手書き風)にできる。
        self.tab_chat = tk.Label(self.bar, text=L("tab_chat"), cursor="pointinghand", padx=3)
        self.tab_chat.bind("<Button-1>", lambda e: self._show_pane("chat"))
        # 左端の余白を赤線の始まり(padx=56)に合わせる(右端のボタン群を
        # 揃えたのと同じ考え方)。
        self.tab_chat.pack(side=tk.LEFT, padx=(56, 1), pady=2)
        self.tab_cmd = tk.Label(self.bar, text=L("tab_cmd"), cursor="pointinghand", padx=3)
        self.tab_cmd.bind("<Button-1>", lambda e: self._show_pane("cmd"))
        self.tab_cmd.pack(side=tk.LEFT, padx=1, pady=2)

        self.model_lbl = tk.Label(self.bar, textvariable=self.model_label_var)
        self.model_lbl.pack(side=tk.LEFT, padx=10, pady=6)

        # 見た目・AI切替・続きから、の3つも同じ理由で tk.Label + クリックに
        self.theme_btn = tk.Label(self.bar, cursor="pointinghand", padx=8, pady=2)
        self.theme_menu = tk.Menu(self.theme_btn, tearoff=0)
        self.theme_btn.bind("<Button-1>", lambda e: self._popup_menu(self.theme_menu, self.theme_btn))
        self._theme_choice = tk.StringVar(value=self.theme_name)
        for key, spec in THEMES.items():
            self.theme_menu.add_radiobutton(
                label=theme_label(spec), value=key, variable=self._theme_choice,
                command=lambda k=key: self._choose_theme(k))
        # 右端の余白を赤線の終わり(padx=56)に合わせる。ここが一番右端の
        # ボタンなので、右側だけ追加で余白を足す。
        self.theme_btn.pack(side=tk.RIGHT, padx=(6, 56), pady=3)

        # 幅は固定せず文字なりに(固定幅にすると文字が欠けて矢印と重なるため)
        self.switch_btn = tk.Label(self.bar, text=L("switch_btn"), cursor="pointinghand",
                                   padx=8, pady=2)
        self.switch_menu = tk.Menu(self.switch_btn, tearoff=0)
        self.switch_btn.bind("<Button-1>", lambda e: self._popup_menu(self.switch_menu, self.switch_btn))
        self.switch_btn.pack(side=tk.RIGHT, padx=6, pady=3)

        self.hist_btn = tk.Label(self.bar, text=L("hist_btn"), cursor="pointinghand",
                                 padx=8, pady=2)
        self.hist_btn.bind("<Button-1>", lambda e: self._write({"t": "list_history"}))
        self.hist_btn.pack(side=tk.RIGHT, padx=6, pady=3)

        # ヘッダー下の細い罫線(共通)。
        self.hdr_rule = tk.Frame(self.root, height=1)
        self.hdr_rule.pack(side=tk.TOP, fill=tk.X, padx=56)

        # 会話ペインとコマンドペインは同じ場所に重ねて置き、切り替えは
        # pack_forget/pack でなく tkraise で行う。pack_forget は中の
        # 罫線・穴のFrameを含めて全部いったんアンマップするようで、
        # 古いMacだと切り替えに何秒もかかっていた(tkraiseなら重ねた
        # まま前後を入れ替えるだけで済む)。
        self.pane_host = tk.Frame(self.root)
        self.pane_host.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # ================= 会話ペイン =================
        self.chat_pane = tk.Frame(self.pane_host)
        self.chat_pane.place(relx=0, rely=0, relwidth=1, relheight=1)

        # ステータスバー。最下段、常に2行ぶんの高さを確保する
        # (pack_propagate(False)で中身の量に関わらず高さを保つ)。
        self.status_frame = tk.Frame(self.chat_pane)
        self.status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_frame.pack_propagate(False)
        self.status_lbl = tk.Label(self.status_frame, textvariable=self.status_var,
                                   anchor=tk.NW, justify=tk.LEFT)
        # 左端を赤線(上のin_ruleと同じpadx=56)の始まりに合わせる。
        self.status_lbl.pack(fill=tk.BOTH, expand=True, padx=(56, 0))

        self.in_rule = tk.Frame(self.chat_pane, height=1)
        self.in_rule.pack(side=tk.BOTTOM, fill=tk.X, padx=56)

        # 書き込み欄。以前のような枠付きの箱+送信ボタンではなく、ノートの
        # 続きに見える4行ぶんの領域(罫線・穴もノート本文と共通)。
        # Enterで送信、Shift+Enterで改行。
        self.write_row = tk.Frame(self.chat_pane)
        self.write_row.pack(side=tk.BOTTOM, fill=tk.X)
        self.write_holes = tk.Canvas(self.write_row, width=36, highlightthickness=0)
        self.write_holes.pack(side=tk.LEFT, fill=tk.Y)
        self.write_holes.bind("<Configure>", lambda e: self._request_draw_holes())
        # 右端の手前(4文字ぶん)で折り返すための余白。固定サイズなので、
        # write_zone(expand=True)より先にpackして場所を確保しておく
        # (send_btnの件と同じ理由。順番を逆にすると場所が残らない)。
        self.write_pad_right = tk.Frame(self.write_row, width=1)
        self.write_pad_right.pack(side=tk.RIGHT, fill=tk.Y)
        self.write_zone = tk.Text(self.write_row, height=4, wrap=tk.CHAR,
                                  relief=tk.FLAT, highlightthickness=0, bd=0,
                                  padx=18, pady=0)
        self.write_zone.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.write_zone.bind("<Return>", self._on_return)
        # プレースホルダー(矢印)は <<Modified>> (中身が実際に変わった後の
        # 通知)で消す。<Key> で消すとIMEの変換前の生入力に割り込み、
        # 1文字目だけ英字のまま入ってしまう不具合が過去にあったため。
        self.write_zone.bind("<<Modified>>", self._write_on_modified)
        self.write_zone.bind("<Button-1>", self._write_click_clear)
        self.write_zone.bind("<FocusOut>", self._write_focus_out)
        self.write_zone.bind(
            "<Configure>", lambda e: self._request_draw_grid(self.write_zone, "_grid_write"))
        self._write_ph = False

        mid = tk.Frame(self.chat_pane)
        mid.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.holes = tk.Canvas(mid, width=34, highlightthickness=0)
        self.holes.pack(side=tk.LEFT, fill=tk.Y)
        self.holes.bind("<Configure>", lambda e: self._request_draw_holes())
        self.note = tk.Text(mid, wrap=tk.CHAR, state=tk.DISABLED, height=1,
                            padx=18, pady=14, relief=tk.FLAT,
                            highlightthickness=0, spacing2=2)
        sb = tk.Scrollbar(mid, command=self.note.yview)
        self.note.config(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.note.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.note.bind(
            "<Configure>",
            lambda e: (self._relayout(e), self._request_draw_grid(self.note, "_grid_note")))
        # トラックパッドの既定のスクロールは半端なpxで止まるため、罫線と
        # 文字がその瞬間だけズレて見える。1行(=pitch)単位でしか止まら
        # ないようにする。
        self.note.bind("<MouseWheel>", self._on_note_wheel)

        # ================= コマンドペイン =================
        # 背景は黒地(端末風)でテーマに関係なく固定。文字色だけ
        # _style_cmd_pane() でテーマに合わせて変える(ハッカーなら緑、
        # それ以外は既定の配色)。ここでは初期値としてCBだけ使う。
        self.CB = CB = "#0f1115"
        CF = CIN = CERR = CDIM = CSUCCESS = "#d6d6d6"  # 後で _style_cmd_pane が上書きする
        self.cmd_pane = tk.Frame(self.pane_host, bg=CB)
        self.cmd_pane.place(relx=0, rely=0, relwidth=1, relheight=1)
        # フォルダパスが深くなると長くなり、同じ行だと入力欄を圧迫して
        # いたため、パス表示は独立した1行(上)にして、入力欄(下)は常に
        # フル幅を使えるようにする。
        self.cmd_row = tk.Frame(self.cmd_pane, bg=CB)
        self.cmd_row.pack(side=tk.BOTTOM, fill=tk.X)
        self.cmd_prompt = tk.Label(self.cmd_pane, textvariable=self.cmd_prompt_var,
                                   anchor=tk.W, bg=CB, fg=CIN)
        self.cmd_prompt.pack(side=tk.BOTTOM, fill=tk.X, padx=(10, 8), pady=(0, 2))
        self.cmd_stop_btn = tk.Button(self.cmd_row, text=L("stop_btn"), width=5,
                                      state=tk.DISABLED, command=self._cmd_stop)
        self.cmd_stop_btn.pack(side=tk.RIGHT, padx=(2, 8), pady=6)
        # パス込みの長いコマンドが窮屈で見づらいとの指摘で、2行→3行に
        # (あくまで1コマンドの表示領域で、複数行のスクリプトを書く欄
        # ではないため、Returnは改行ではなく送信、Up/Downはカーソル移動
        # ではなく履歴呼び出しのまま)。
        self.cmd_entry = tk.Text(self.cmd_row, height=3, wrap=tk.CHAR, relief=tk.FLAT,
                                 bg="#1a1d22", fg=CF, insertbackground=CF,
                                 highlightthickness=0, padx=4, pady=2)
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 4), pady=6)
        self.cmd_entry.bind("<Return>", lambda e: (self._cmd_submit(), "break")[1])
        self.cmd_entry.bind("<Up>", self._cmd_hist_prev)
        self.cmd_entry.bind("<Down>", self._cmd_hist_next)
        self.cmd_entry.bind("<Control-c>", lambda e: (self._cmd_stop(), "break")[1])
        self.cmd_hist = []          # コマンド履歴(このセッション限り)
        self.cmd_hist_idx = None
        self.cmid = cmid = tk.Frame(self.cmd_pane, bg=CB)
        cmid.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.cmd_out = tk.Text(cmid, wrap=tk.CHAR, state=tk.DISABLED, bg=CB, fg=CF,
                               padx=10, pady=8, relief=tk.FLAT, highlightthickness=0)
        self.cmd_out.tag_config("cin", foreground=CIN)
        self.cmd_out.tag_config("cerr", foreground=CERR)
        self.cmd_out.tag_config("cdim", foreground=CDIM)
        self.cmd_out.tag_config("csuccess", foreground=CSUCCESS)
        csb = tk.Scrollbar(cmid, command=self.cmd_out.yview)
        self.cmd_out.config(yscrollcommand=csb.set)
        csb.pack(side=tk.RIGHT, fill=tk.Y)
        self.cmd_out.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._cmd_refresh_prompt()

        self.pane = "chat"
        self.chat_pane.tkraise()   # 起動直後は会話ペインを前面に

    def _show_pane(self, name):
        self.pane = name
        if name == "cmd":
            self.cmd_pane.tkraise()
            self._cmd_refresh_prompt()
            self.cmd_entry.focus_set()
        else:
            self.chat_pane.tkraise()
        self._style_tabs()

    def _style_tabs(self):
        """ヘッダーのボタン全部(会話/コマンド のタブ + 見た目/AI切替/
        続きから)を同じ調子にする。ノートモードは手書き風＋下線、
        コーディング/ハッカーは枠を使わず「[ 項目 ]」の無骨な見た目に
        統一する(以前の押しボタン風の枠は、ノートだけ枠が無いのが
        不揃いだと指摘された)。タブだけ選択中を太字にする。
        (全部 tk.Label なので activebackground 等 Button専用オプションは使えない)"""
        t = THEMES[self.theme_name]
        paper = self.theme_name == "paper"
        active = getattr(self, "pane", "chat")
        tabs = (("chat", self.tab_chat, L("tab_chat")), ("cmd", self.tab_cmd, L("tab_cmd")))
        utils = ((self.hist_btn, L("hist_btn")), (self.switch_btn, L("switch_btn")),
                 (self.theme_btn, theme_label(t) + " ▾"))
        # 左右端を赤線に揃えたのはノート(縦線・罫線がある)向けの調整。
        # コーディング/ハッカーは全面黒で赤線が無く、[ ]で幅も食うため、
        # 同じ余白だと「続きから」が完全に隠れるほど窮屈だった。
        # ノートのレイアウトは変えず、それ以外だけ余白を詰める。
        self.tab_chat.pack_configure(padx=(56 if paper else 4, 1))
        self.theme_btn.pack_configure(padx=(6, 56 if paper else 4))
        # ボタン間の隙間・ボタン自身の内側余白も、コーディング/ハッカーは
        # 詰める(フォントも1段階小さくする)。ノートは変えない。
        gap = 6 if paper else 2
        self.model_lbl.pack_configure(padx=(10 if paper else 4))
        self.tab_cmd.pack_configure(padx=(1 if paper else gap))
        self.switch_btn.pack_configure(padx=gap)
        self.hist_btn.pack_configure(padx=gap)
        # 非選択タブの色。dimは背景とのコントラストが低すぎて
        # (テーマにより約2.8〜4.2:1)背景に溶け込み、選択中と区別しづらい
        # との指摘があった。aiは各テーマで元々コントラストが高く
        # (7.7〜11.8:1)、選択中(fg)ともきちんと色が違うので、これに変える。
        off_color = t["ai"]

        def deco(label):
            return label if paper else "[ %s ]" % label

        for name, btn, label in tabs:
            on = (name == active) or (name == "chat" and active not in ("chat", "cmd"))
            if paper:
                f = self.font
                fs = max(9, f[1] - 1)   # 少し小さめにして幅を詰める
                fnt = (f[0], fs, "bold", "underline") if on \
                    else (f[0], fs, "underline")
                btn.config(text=deco(label), relief=tk.FLAT, bd=0, highlightthickness=0,
                           font=fnt, fg=(t["fg"] if on else off_color), bg=t["bg"])
            else:
                tf = t["font"]
                btn.config(text=deco(label), relief=tk.FLAT, bd=0, highlightthickness=0,
                           font=(tf[0], tf[1] - 2), fg=(t["fg"] if on else off_color),
                           bg=t["bg"], padx=1)
        for btn, label in utils:
            if paper:
                f = self.font
                fs = max(10, f[1])   # 手書き風は小さいと潰れるので本文サイズのまま
                btn.config(text=deco(label), relief=tk.FLAT, bd=0, highlightthickness=0,
                           font=(f[0], fs, "underline"), fg=t["dim"], bg=t["bg"])
            else:
                # 常時使うボタンなのでdimではなくfgにする(理由は上のtabsと同じ)。
                btn.config(text=deco(label), relief=tk.FLAT, bd=0, highlightthickness=0,
                           font=("Hiragino Sans", 10), fg=t["fg"], bg=t["bg"], padx=2)

    # ---------- コマンドパネル ----------
    def _cmd_env(self):
        env = dict(os.environ)
        env["PATH"] = (os.path.expanduser("~/bin") +
                       ":/usr/local/bin:/usr/local/sbin:/opt/homebrew/bin"
                       ":/opt/homebrew/sbin"
                       ":/Library/Frameworks/Python.framework/Versions/3.10/bin"
                       ":/usr/bin:/bin:/usr/sbin:/sbin")
        env["TERM"] = "dumb"
        return env

    def _cmd_refresh_prompt(self):
        home = os.path.expanduser("~")
        d = self.cwd
        if d == home:
            d = "~"
        elif d.startswith(home + os.sep):
            d = "~" + d[len(home):]
        self.cmd_prompt_var.set("watermark:%s$" % d)

    def _cmd_echo(self, text, tag=None):
        self.cmd_out.config(state=tk.NORMAL)
        self.cmd_out.insert(tk.END, text, (tag,) if tag else ())
        self.cmd_out.see(tk.END)
        self.cmd_out.config(state=tk.DISABLED)

    def _cmd_set_running(self, on):
        # 入力欄は無効化しない(無効化すると Ctrl-C や ↑↓ のキー入力を
        # 受け取れなくなるため)。二重実行は _cmd_submit のガードで防ぐ。
        self.cmd_stop_btn.config(state=tk.NORMAL if on else tk.DISABLED)
        self.cmd_entry.focus_set()

    def _cmd_submit(self):
        if self.cmd_proc is not None:
            self._cmd_echo(L("busy_running"), "cdim")
            return
        cmd = self.cmd_entry.get("1.0", "end-1c").strip()
        if not cmd:
            return
        self.cmd_entry.delete("1.0", tk.END)
        if not self.cmd_hist or self.cmd_hist[-1] != cmd:
            self.cmd_hist.append(cmd)
        self.cmd_hist_idx = None
        self._cmd_echo(self.cmd_prompt_var.get() + " " + cmd + "\n", "cin")

        if cmd in ("clear", "cls"):
            self.cmd_out.config(state=tk.NORMAL)
            self.cmd_out.delete("1.0", tk.END)
            self.cmd_out.config(state=tk.DISABLED)
            return
        if cmd == "cd" or cmd.startswith(("cd ", "cd\t")):
            target = os.path.expanduser(cmd[2:].strip() or "~")
            if not os.path.isabs(target):
                target = os.path.normpath(os.path.join(self.cwd, target))
            if os.path.isdir(target):
                self.cwd = target
                self._cmd_refresh_prompt()
                self._write({"t": "cwd", "path": self.cwd})   # AI のツールにも反映
            else:
                self._cmd_echo(L("no_such_folder", path=target), "cerr")
            return

        self._cmd_set_running(True)
        threading.Thread(target=self._cmd_run, args=(cmd,), daemon=True).start()

    def _cmd_run(self, cmd):
        try:
            # 独立したプロセスグループで起動する。中止のとき、シェルだけでなく
            # その子(ssh/scp 等)まで一括で止められるようにするため。
            p = subprocess.Popen(cmd, shell=True, cwd=self.cwd, env=self._cmd_env(),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, bufsize=1, encoding="utf-8",
                                 errors="replace", start_new_session=True)
        except Exception as e:
            self.events.put({"t": "cmd_out", "text": L("cannot_run", err=e)})
            self.events.put({"t": "cmd_done", "code": -1})
            return
        self.cmd_proc = p
        for line in p.stdout:
            self.events.put({"t": "cmd_out", "text": line})
        p.wait()
        self.events.put({"t": "cmd_done", "code": p.returncode})

    def _cmd_stop(self):
        p = self.cmd_proc
        if p is None:
            return
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)   # プロセスグループごと
        except Exception:
            try:
                p.terminate()
            except Exception:
                pass
        # まだ生きていたら少し待って強制終了
        self.root.after(1500, lambda: self._cmd_kill(p))

    def _cmd_kill(self, p):
        if p is not None and p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    def _cmd_hist_prev(self, _e=None):
        if not self.cmd_hist:
            return "break"
        if self.cmd_hist_idx is None:
            self.cmd_hist_idx = len(self.cmd_hist) - 1
        elif self.cmd_hist_idx > 0:
            self.cmd_hist_idx -= 1
        self.cmd_entry.delete("1.0", tk.END)
        self.cmd_entry.insert("1.0", self.cmd_hist[self.cmd_hist_idx])
        return "break"

    def _cmd_hist_next(self, _e=None):
        if self.cmd_hist_idx is None:
            return "break"
        self.cmd_hist_idx += 1
        self.cmd_entry.delete("1.0", tk.END)
        if self.cmd_hist_idx >= len(self.cmd_hist):
            self.cmd_hist_idx = None            # 最新より下 = 空に
        else:
            self.cmd_entry.insert("1.0", self.cmd_hist[self.cmd_hist_idx])
        return "break"

    def _request_draw_holes(self):
        """_draw_holes は穴を全部描き直す(delete して作り直す)ので、
        タブの切り替えなどで <Configure> が連続して何度も飛んでくると
        そのたびに全部作り直してしまい遅くなる。after_idle でまとめる。"""
        if getattr(self, "_holes_pending", False):
            return
        self._holes_pending = True

        def go():
            self._holes_pending = False
            self._draw_holes()
        self.root.after_idle(go)

    def _draw_holes(self):
        # ノート本文の左と、書き込み欄の左と、両方に同じ穴を敷く
        # (書き込み欄までルーズリーフの続きに見えるように)
        self._draw_holes_on(self.holes)
        self._draw_holes_on(self.write_holes)

    def _draw_holes_on(self, canvas):
        canvas.delete("all")
        t = THEMES[self.theme_name]
        if not t.get("holes"):
            canvas.config(width=1, bg=t["bg"])
            return
        canvas.config(width=36, bg=t["bg"])
        h = canvas.winfo_height() or 600
        hole = t.get("code_bg", "#e9e0c8")   # 紙より一段濃いグレー
        y = 36
        while y < h:
            # 穴本体(薄グレー) + 左下に濃いめの弧で影っぽく。
            # 小さめ・間隔を詰めて本物のルーズリーフに近づけた
            canvas.create_oval(12, y - 6, 24, y + 6, fill=hole, outline=t["dim"])
            canvas.create_arc(12, y - 6, 24, y + 6, start=120, extent=140,
                              style=tk.ARC, outline=t["dim"], width=2)
            y += 48
        # 大学ノートの赤い縦罫。ノート本文のすぐ左(この canvas の右端)に。
        vline = t.get("vline")
        if vline:
            canvas.create_line(35, 0, 35, h, fill=vline, width=1)

    def _request_draw_grid(self, widget, pool_attr):
        """_draw_grid を呼ぶ薄いラッパー。何度呼ばれても取りこぼさない
        よう after_idle 越しにまとめて1回呼ぶ。"""
        pending_attr = pool_attr + "_pending"
        if getattr(self, pending_attr, False):
            return
        setattr(self, pending_attr, True)

        def go():
            setattr(self, pending_attr, False)
            self._draw_grid(widget, pool_attr)
        self.root.after_idle(go)

    def _draw_grid(self, widget, pool_attr):
        """横罫線を、文字の位置を一切見ずに上から下まで固定ピッチで敷く
        (左の穴・縦の赤線と同じ考え方: 中身を一切見ないので中身とズレる
        余地が無い)。

        以前は見えている行を1つずつ実測して、その行の真下に線を置く
        方式(_draw_rules)だった。見出し・絵文字・漢字の多い行などで
        実際の文字の高さが微妙にばらつき、3日以上・何通りも式を変えて
        調整しても、文字と線が重なる/足りない/ズレるを解消できなかった。
        穴や縦の赤線が一度も壊れたことがないのは、そもそも中身を見て
        いないからだと気づき、横罫線もそれに合わせた。ウィジェットの
        高さだけを見て一定間隔(pitch、_apply_themeで計算)に線を置く。
        スクロールや挿入のたびに測り直す必要も無くなったので、以前より
        軽い(スクロールが鈍くなっていた原因もこれだったはず)。"""
        if not hasattr(self, pool_attr):
            setattr(self, pool_attr, [])
        pool = getattr(self, pool_attr)
        color = THEMES[self.theme_name].get("hline")
        pitch = getattr(self, "pitch", 24)
        h = widget.winfo_height()
        if not color or pitch <= 0 or h < pitch:
            for ln in pool:
                ln.place_forget()
            return
        n = int(h // pitch)
        # 行の切れ目ちょうど(pitch境界)ではなく、文字寄り(半分手前)に
        # 線を詰める。ピッチ自体はここでは変えないので、揃っている状態は
        # 崩れない。
        offset = getattr(self, "_line_gap", 0) // 2
        while len(pool) < n:
            pool.append(tk.Frame(widget, height=1, bd=0, highlightthickness=0))
        for i, ln in enumerate(pool):
            if i < n:
                ln.config(bg=color)
                ln.place(in_=widget, x=0, relwidth=1.0,
                         y=(i + 1) * pitch - offset, height=1)
            else:
                ln.place_forget()

    def _apply_theme(self, name):
        t = THEMES[name]
        self.theme_name = name
        f = pick_font(*t["font"]) if t.get("handwriting") else t["font"]
        self.font = f
        code_f = ("Menlo", f[1] - 1)

        self.root.config(bg=t["bg"])
        for w in (self.bar, self.write_row, self.status_frame):
            w.config(bg=t["bg"])                            # ヘッダーも本文と同色
        # コーディング/ハッカーはdimの文字が背景に沈んで見づらい
        # (コントラスト比 約3.9〜4.2:1、fgなら11〜15.6:1)ため、
        # ノート以外ではヘッダーはfgを使う。
        model_fg = t["dim"] if self.theme_name == "paper" else t["fg"]
        self.model_lbl.config(bg=t["bg"], fg=model_fg, font=(f[0], f[1] - 2))
        self.status_lbl.config(bg=t["bg"], fg=t["dim"], font=(f[0], 10))
        self._style_tabs()  # 見た目/AI切替/続きから の3つもここでまとめて設定
        self.cmd_out.config(font=code_f)
        self.cmd_entry.config(font=code_f)
        self.cmd_prompt.config(font=code_f)
        line = t.get("line", t["dim"])
        self.hdr_rule.config(bg=line)                       # ヘッダー下の罫線(赤)
        self.in_rule.config(bg=line)                        # 書き込み欄の上の罫線(赤)
        self.note.config(bg=t["bg"], fg=t["fg"], font=f, insertbackground=t["fg"])

        # 罫線を実測して合わせるのはもうやめる。逆に、罫線の間隔(pitch)を
        # 先に固定で決め、本文の行送り(spacing)をそのpitchに"ぴったり
        # 一致するよう計算で"合わせる。Tkのフォント指標(ascent/descent)
        # は整数px、GAPも整数なので、pitch = ascent+descent+GAP は端数の
        # 出ない厳密な整数になる。spacing2/spacing3にそのGAPをそのまま
        # 渡せば、Tkが実際に描く行の高さは(見出し・絵文字を含め全行とも
        # 同じ書体・同じサイズである限り)必ずascent+descent+GAPになり、
        # pitchと理論上ズレようがない(測って追いかける要素が無い)。
        try:
            fm = tkfont.Font(font=f)
            ascent = fm.metrics("ascent")
            descent = fm.metrics("descent")
        except Exception:
            ascent, descent = int(f[1] * 0.9), int(f[1] * 0.25)
        S = max(6, int(round(f[1] * 0.5)))    # 行間(整数px)
        self.pitch = ascent + descent + S
        self._line_gap = S   # _draw_grid が罫線を文字寄りに詰めるのに使う
        self.status_frame.config(height=self.pitch * 2)   # ステータスバーは常に2行ぶん
        self.note.config(spacing1=0, spacing2=S, spacing3=S)

        # 書き込み欄。ノート本文と地続きに見えるよう、同じ背景・書体・
        # 行間にする。点滅カーソルは止め(insertofftime=0)、代わりに
        # 空のときは矢印(WRITE_MARK)を書き始めの目印として出す。
        write_fg = t["dim"] if getattr(self, "_write_ph", False) else t["input_fg"]
        write_font_size = min(f[1], 13)
        self.write_zone.config(bg=t["bg"], fg=write_fg, font=(f[0], write_font_size),
                               insertbackground=t["input_fg"], insertofftime=0,
                               spacing1=0, spacing2=S, spacing3=S)
        # 右端の手前4文字ぶんで折り返すための余白(全角文字幅≒フォント
        # サイズとして概算)。
        self.write_pad_right.config(bg=t["bg"], width=write_font_size * 4)
        self._draw_holes()

        # 色・書体・寄せだけ。左右の余白(1/3)は _relayout が幅から計算する。
        # 自分の発言は「右側 2/3 のブロックに置く」が、文字は左そろえ。
        # (右寄せにすると2行目以降が右にばらけて読みにくい、との指摘)
        for tg, col in (("you", t["fg"]), ("ai", t["ai"]),
                        ("dim", t["dim"]), ("err", t["err"]), ("gap", t["bg"])):
            self.note.tag_config(tg, foreground=col, justify=tk.LEFT,
                                 spacing1=0, spacing2=S, spacing3=S,
                                 font=f)
        self.note.tag_config("prompt", foreground=t.get("prompt", t["fg"]),
                             justify=tk.LEFT, font=(f[0], f[1], "bold"))
        self.note.tag_config("rule", lmargin1=0, lmargin2=0, rmargin=0,
                             spacing1=0, spacing2=S, spacing3=S)
        self.note.tag_config("code", font=code_f, background=t.get("code_bg", t["bg"]),
                             lmargin1=f[1] * 3, lmargin2=f[1] * 3)
        hl = t.get("hl", {})
        for key, tag in HL_TAG.items():
            self.note.tag_config(tag, foreground=hl.get(key, t["ai"]), font=code_f,
                                 background=t.get("code_bg", t["bg"]))
        self._relayout()
        # テーマ切替は <Configure> を発生させない(ウィンドウサイズは
        # 変わらない)ので、色やpitchが変わる罫線はここで明示的に引き直す。
        self._request_draw_grid(self.note, "_grid_note")
        self._request_draw_grid(self.write_zone, "_grid_write")
        self._style_cmd_pane()

    def _style_cmd_pane(self):
        """コマンドパネルの配色。ハッカーの時は緑系(エラー/終了コードは
        赤のまま)、ノートの時は本文と同じ薄いベージュ地に濃紺の文字、
        それ以外(コーディング)は従来通りの端末風(黒地)のまま。"""
        if self.theme_name == "hacker":
            bg, cf, cin, cdim, csuccess, cerr, entry_bg = (
                "#000000", "#39ff5a", "#00ff66", "#2e7d4f", "#39ff5a",
                "#ff5555", "#0a0f0a")
        elif self.theme_name == "paper":
            bg, cf, cin, cdim, csuccess, cerr, entry_bg = (
                "#f6efdc", "#243b6b", "#5a4636", "#9a8f78", "#2e7d32",
                "#a5341f", "#f6efdc")
        else:
            bg, cf, cin, cdim, csuccess, cerr, entry_bg = (
                "#0f1115", "#d6d6d6", "#4d9fff", "#7a8088", "#4caf50",
                "#ff6b6b", "#1a1d22")
        for w in (self.cmd_pane, self.cmd_row, self.cmid, self.cmd_prompt):
            w.config(bg=bg)
        self.cmd_out.config(bg=bg, fg=cf)
        self.cmd_out.tag_config("cin", foreground=cin)
        self.cmd_out.tag_config("cerr", foreground=cerr)
        self.cmd_out.tag_config("cdim", foreground=cdim)
        self.cmd_out.tag_config("csuccess", foreground=csuccess)
        self.cmd_entry.config(bg=entry_bg, fg=cf, insertbackground=cf)
        self.cmd_prompt.config(fg=cin)

    def _relayout(self, event=None):
        """幅の 1/3 を左右の余白に。自分=左1/3空け右寄せ / 相手=右1/3空け左寄せ。"""
        w = self.note.winfo_width()
        if w < 80:
            self.root.after(60, self._relayout)
            return
        third = int(w / 3)
        near = EDGE                      # 書き出しは赤い縦罫のすぐ右から
        ch = max(1, self.font[1])        # ざっくり全角1文字ぶん
        # 質問ブロックを 4 文字ぶん左へ / 解答ブロックを 4 文字ぶん右へ広げる
        you_left = max(near + 2 * ch, third - 4 * ch)
        ai_right = max(2 * ch, third - 4 * ch)
        self.note.tag_config("you", lmargin1=you_left, lmargin2=you_left, rmargin=near)
        for tag in ("ai", "dim", "err"):
            self.note.tag_config(tag, lmargin1=near, lmargin2=near, rmargin=ai_right)

    def _popup_menu(self, menu, widget):
        """見た目/AI切替ボタン用。普通のButtonの真下にメニューを出す
        (Menubuttonをやめて見た目を他のボタンと揃えるための代わり)。"""
        x = widget.winfo_rootx()
        y = widget.winfo_rooty() + widget.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _choose_theme(self, key):
        if key not in THEMES:
            return
        self._theme_choice.set(key)
        self._apply_theme(key)
        save_cfg({"theme": key})

    def _block_sep(self):
        """発言の切れ目に空の1行。先頭では入れない。
        大学ノートの「1行あけて書く」感じ。行の縦リズムも崩さない。
        横罫線は全行に敷く方式(_draw_rules)に一本化したので、ここでは
        個別には挿入しない。"""
        if self.note.index("end-1c") != "1.0":
            self.note.insert(tk.END, "\n", "gap")

    def _append(self, text, tag, anchor=False):
        """1ブロックを一気に書く(自分の発言・お知らせ・エラー用)。"""
        self.note.config(state=tk.NORMAL)
        self._block_sep()
        start = self.note.index("end-1c")
        if tag == "you" and THEMES[self.theme_name].get("prompt_prefix"):
            self.note.insert(tk.END, "watermark> ", ("prompt", "you"))
        self.note.insert(tk.END, text.rstrip("\n") + "\n", tag)
        if anchor:
            # 自分の発言の先頭に印。返答が来たらここを画面の一番上に置く
            # ことで、Enter を押した瞬間に自分の文が消える問題を防ぐ。
            self.note.mark_set("q_anchor", start)
            self.note.mark_gravity("q_anchor", "left")
        self.note.config(state=tk.DISABLED)

    def _stream_append(self, text, tag):
        """AIの返答を少しずつ流し込む(一瞬で入れ替わって読めない問題の対策)。
        流し込み中は画面を下端に追従させず、直前の自分の発言を上に留める。"""
        self.note.config(state=tk.NORMAL)
        self._block_sep()
        self.note.config(state=tk.DISABLED)
        if self.note_has_anchor():
            self.note.yview("q_anchor")           # 自分の質問を画面最上部へ
        self._stream_step(list(text), tag)

    def _stream_step(self, chars, tag):
        if not chars:
            self.note.config(state=tk.NORMAL)
            self.note.insert(tk.END, "\n", tag)
            self.note.config(state=tk.DISABLED)
            self.note.see(tk.END)
            return
        chunk = "".join(chars[:24])
        del chars[:24]
        self.note.config(state=tk.NORMAL)
        self.note.insert(tk.END, chunk, tag)
        self.note.config(state=tk.DISABLED)
        # 返答が書き込み欄の下に隠れて続きに気づけない問題への対応。
        # 質問直後はq_anchorで質問が見える位置から始まるが、返答が伸びて
        # 画面の下端に達したら、書いている文字を追いかけて自然に下へ
        # 流す(短い返答ならここは実質何もしない=見える範囲のままで済む)。
        self.note.see(tk.END)
        # 40msでもまだ速いとの指摘でさらに遅く。
        self.root.after(70, lambda: self._stream_step(chars, tag))

    def note_has_anchor(self):
        try:
            self.note.index("q_anchor")
            return True
        except tk.TclError:
            return False

    def _on_note_wheel(self, event):
        """1行(表示上の1単位 = _apply_themeでpitchぴったりに揃えている)
        単位でしか止まらないようにする。event.deltaを貯めて、1行分
        たまるたびに yview_scroll(±1, "units") を1回だけ呼ぶ(標準の
        px単位スクロールは自前で止めるので、既定の処理はさせない
        = return "break")。THRESHはトラックパッドの感触を見ながらの
        調整値。"""
        self._wheel_accum = getattr(self, "_wheel_accum", 0) + event.delta
        THRESH = 3
        while self._wheel_accum >= THRESH:
            self.note.yview_scroll(-1, "units")
            self._wheel_accum -= THRESH
        while self._wheel_accum <= -THRESH:
            self.note.yview_scroll(1, "units")
            self._wheel_accum += THRESH
        return "break"

    def _render_reply(self, txt):
        """```コードブロック``` を含む返答を、地の文とコードに分けて描画する。
        コードは等幅・淡い背景 + ざっくりシンタックス着色。ストリーム表示は
        しない(構文の途中で色付けが崩れるため一気に出す)。"""
        self.note.config(state=tk.NORMAL)
        self._block_sep()
        pos = 0
        for m in FENCE_RE.finditer(txt):
            pre = txt[pos:m.start()].strip("\n")
            if pre:
                self.note.insert(tk.END, pre + "\n", "ai")
            code = m.group(2).rstrip("\n")
            c0 = self.note.index("end-1c")
            self.note.insert(tk.END, code + "\n", "code")
            self._highlight(c0, self.note.index("end-1c"))
            pos = m.end()
        tail = txt[pos:].strip("\n")
        if tail:
            self.note.insert(tk.END, tail + "\n", "ai")
        self.note.config(state=tk.DISABLED)
        # ストリーム表示(_stream_step)と同じく、末尾が見える位置まで
        # 下げる。q_anchorだけだと返答が長い時に続きが隠れて見えなかった。
        self.note.see(tk.END)

    def _highlight(self, a, b):
        try:
            src = self.note.get(a, b)
        except tk.TclError:
            return
        for m in CODE_RE.finditer(src):
            tag = HL_TAG.get(m.lastgroup)
            if tag:
                self.note.tag_add(tag, "%s+%dc" % (a, m.start()),
                                  "%s+%dc" % (a, m.end()))

    # ---------- バックエンド ----------
    def _start_backend(self):
        cmd, env = build_backend_command_and_env()
        if cmd is None:
            messagebox.showerror(L("cannot_start_title"),
                                  L("cannot_start_body", err="claude-agent.pl"))
            self.root.destroy()
            return
        try:
            self.proc = subprocess.Popen(
                cmd, env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=1,
                universal_newlines=True, encoding="utf-8",
            )
        except OSError as e:
            messagebox.showerror(L("cannot_start_title"), L("cannot_start_body", err=e))
            self.root.destroy()
            return
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                obj = {"t": "note", "text": line}
            self.events.put(obj)
        self.events.put({"t": "bye"})

    def _write(self, obj):
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            pass

    # ---------- イベント ----------
    def _pump(self):
        try:
            while True:
                obj = self.events.get_nowait()
                try:
                    self._handle(obj)
                except Exception as e:
                    self._append(L("internal_error", err=e), "err")
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def _handle(self, obj):
        t = obj.get("t")
        if t == "ready":
            # _set_model がモデル名の短縮表示に models リストのラベルを
            # 使うため、先に _fill_menu でキャッシュしておく。
            self._fill_menu(obj.get("models", []))
            self._set_model(obj.get("provider", ""), obj.get("model", ""))
            hist = L("history_encrypted") if obj.get("history") else L("history_off")
            self.status_var.set(L("ready_status", hist=hist))
            self._set_busy(False)
        elif t == "text":
            txt = str(obj.get("text", ""))
            if "```" in txt:
                self._render_reply(txt)          # コード入り = 一気に着色描画
            else:
                self._stream_append(txt, "ai")   # 地の文だけ = 流し込み
        elif t == "note":
            self._append(str(obj.get("text", "")), "dim")
        elif t == "error":
            self._append(str(obj.get("text", "")), "err")
        elif t == "tool":
            self._append(L("using_tool", name=obj.get("name", "")), "dim")
        elif t == "status":
            self.status_var.set(obj.get("text", "") or "")
        elif t == "model":
            self._set_model(obj.get("provider", ""), obj.get("model", ""))
            # 切替後の「← 使用中」を反映するため、メニュー項目を作り直す。
            self._fill_menu([{"id": k, "label": v} for k, v in
                             getattr(self, "_model_labels", {}).items()])
        elif t == "confirm":
            ok = messagebox.askyesno(
                L("confirm_title"),
                L("confirm_body", prompt=obj.get("prompt", "")))
            self._write({"t": "reply", "value": "y" if ok else "n"})
        elif t == "need_passphrase":
            self._ask_passphrase(obj.get("prompt", L("passphrase_default")),
                                 recover=bool(obj.get("recover")))
        elif t == "need_recovery":
            self._ask_recovery(obj.get("mode", "new"), obj.get("question", ""))
        elif t == "history_list":
            self._show_history_dialog(obj.get("items", []))
        elif t == "history_loaded":
            self._render_history(obj.get("entries", []))
        elif t == "turn_done":
            self._set_busy(False)
            self.status_var.set("")
        elif t == "cmd_out":
            self._cmd_echo(str(obj.get("text", "")))
        elif t == "cmd_done":
            rc = obj.get("code", 0)
            self._cmd_echo(L("turn_end", code=rc), "cerr" if rc else "csuccess")
            self.cmd_proc = None
            self._cmd_set_running(False)
        elif t == "bye":
            self.status_var.set(L("bye_status"))
            self._set_busy(True)

    # ---------- 小物 ----------
    def _set_model(self, provider, model):
        # 生のモデルID(例: gemini-3.5-flash-lite)は長すぎてヘッダーを
        # 圧迫し、「AIを切替」ボタンの文字が切れる原因になっていた。
        # models.txtの説明(_fill_menuでキャッシュ済み)の em-dash 前の
        # 短い人間向け名前(例: "Gemini Flash-Lite")があればそちらを使う。
        self._current_model_id = model
        label = getattr(self, "_model_labels", {}).get(model)
        if label:
            short = re.split(r"\s*[—-]\s", label, maxsplit=1)[0].strip()
        else:
            short = model or provider
        self.model_label_var.set(short)

    def _fill_menu(self, models):
        self.switch_menu.delete(0, tk.END)
        self._model_labels = {m.get("id"): m.get("label", "") for m in models}
        current = getattr(self, "_current_model_id", None)
        for i, m in enumerate(models, start=1):
            label = f"{i}. {m.get('label', m.get('id', '?'))}"
            if m.get("id") == current:
                label += L("currently_using")
            self.switch_menu.add_command(
                label=label,
                command=lambda n=i: self._write({"t": "user", "text": str(n)}),
            )

    def _ask_passphrase(self, prompt, recover=False):
        # 確認欄はなし(1回だけ)。打ち間違い対策は「合言葉」で担保する。
        dlg = tk.Toplevel(self.root)
        dlg.title(L("passphrase_title"))
        dlg.transient(self.root)
        dlg.grab_set()
        tk.Label(dlg, text=prompt).pack(padx=16, pady=(14, 4))
        var = tk.StringVar()
        ent = tk.Entry(dlg, show="*", textvariable=var, width=32)
        ent.pack(padx=16, pady=6)
        ent.focus_set()

        def done(_=None):
            self._write({"t": "passphrase", "value": var.get()})
            dlg.destroy()

        ent.bind("<Return>", done)
        btns = tk.Frame(dlg)
        btns.pack(pady=(4, 14))
        tk.Button(btns, text=L("ok"), command=done).pack(side=tk.LEFT, padx=4)
        if recover:
            def use_recovery():
                self._write({"t": "passphrase", "recover": 1})
                dlg.destroy()
            tk.Button(btns, text=L("recover_with_answer"), command=use_recovery).pack(side=tk.LEFT, padx=4)
        dlg.protocol("WM_DELETE_WINDOW",
                     lambda: (self._write({"t": "passphrase", "value": ""}), dlg.destroy()))

    def _ask_recovery(self, mode, question):
        # 合言葉(秘密の質問)。mode="new"=初回設定(質問+答え)、
        # mode="unlock"=復旧(答えだけ)。答えは大文字小文字・前後空白を区別しない。
        dlg = tk.Toplevel(self.root)
        dlg.title(L("secret_title"))
        dlg.transient(self.root)
        dlg.grab_set()
        q_var = tk.StringVar(value=question)
        a_var = tk.StringVar()

        if mode == "new":
            tk.Label(dlg, justify=tk.LEFT,
                     text=L("secret_new_body")).pack(padx=16, pady=(14, 6))
            tk.Label(dlg, text=L("question_label")).pack(anchor="w", padx=16)
            q_ent = tk.Entry(dlg, textvariable=q_var, width=36)
            q_ent.pack(padx=16, pady=(0, 6))
            q_ent.focus_set()
        else:
            tk.Label(dlg, text=L("secret_unlock_body")).pack(padx=16, pady=(14, 6))
            tk.Label(dlg, text=L("question_prefix", q=(question or "?"))).pack(
                anchor="w", padx=16)

        tk.Label(dlg, text=L("answer_label")).pack(anchor="w", padx=16)
        a_ent = tk.Entry(dlg, textvariable=a_var, width=36)
        a_ent.pack(padx=16, pady=(0, 6))
        if mode != "new":
            a_ent.focus_set()

        def done(_=None):
            self._write({"t": "recovery",
                         "question": q_var.get(), "answer": a_var.get()})
            dlg.destroy()

        a_ent.bind("<Return>", done)
        tk.Button(dlg, text=L("ok"), command=done).pack(pady=(4, 14))
        dlg.protocol("WM_DELETE_WINDOW",
                     lambda: (self._write({"t": "recovery", "question": "", "answer": ""}),
                              dlg.destroy()))

    # ---------- 続きから(過去の会話) ----------
    def _show_history_dialog(self, items):
        if not items:
            messagebox.showinfo(L("resume_title"), L("no_saved_history"))
            return
        dlg = tk.Toplevel(self.root)
        dlg.title(L("resume_title"))
        dlg.transient(self.root)
        dlg.geometry("560x360")
        tk.Label(dlg, text=L("resume_pick")).pack(padx=10, pady=(10, 2))
        lb = tk.Listbox(dlg, font=("", 12), activestyle="dotbox")
        lb.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        for it in items:
            lb.insert(tk.END, "%s   %s" % (it.get("started", "?"), it.get("first", "")))
        lb.selection_set(0)
        lb.focus_set()

        def choose(_=None):
            sel = lb.curselection()
            if sel:
                idx = sel[0]
                # ノートらしく「○ページ目/全△ページ」を後で先頭に出すため覚えておく
                self._resume_page = (idx + 1, len(items))
                self._write({"t": "resume", "file": items[idx]["file"]})
            dlg.destroy()

        lb.bind("<Double-Button-1>", choose)
        lb.bind("<Return>", choose)
        btnf = tk.Frame(dlg)
        btnf.pack(fill=tk.X, padx=10, pady=(0, 10))
        tk.Button(btnf, text=L("open"), command=choose).pack(side=tk.RIGHT)
        tk.Button(btnf, text=L("cancel"), command=dlg.destroy).pack(side=tk.RIGHT, padx=(0, 6))

    def _render_history(self, entries):
        self.note.config(state=tk.NORMAL)
        self.note.delete("1.0", tk.END)
        self.note.config(state=tk.DISABLED)
        try:
            self.note.mark_unset("q_anchor")
        except Exception:
            pass
        page = getattr(self, "_resume_page", None)
        self._resume_page = None
        if page:
            self._append(L("resume_page", page=page[0], total=page[1]), "dim")
        for e in entries:
            role = e.get("role")
            txt = str(e.get("text", ""))
            if not txt.strip():
                continue
            if role == "you":
                self._append(txt, "you")
            elif role == "ai":
                if "```" in txt:
                    self._render_reply(txt)
                else:
                    self._append(txt, "ai")
            elif role == "tool":
                self._append("— " + txt + " —", "dim")
            # toolresult はうるさいので再表示しない
        self._append(L("resume_loaded"), "dim")
        self._show_pane("chat")
        self.note.see(tk.END)

    def _set_busy(self, busy):
        self.busy = busy
        self.write_zone.config(state=tk.DISABLED if busy else tk.NORMAL)

    def _write_show_marker(self):
        self.write_zone.delete("1.0", tk.END)
        self.write_zone.insert("1.0", WRITE_MARK)
        self._write_ph = True
        self._write_apply_ph_color()

    def _write_apply_ph_color(self):
        t = THEMES[self.theme_name]
        self.write_zone.config(fg=(t["dim"] if self._write_ph else t["input_fg"]))

    def _write_click_clear(self, _event=None):
        # クリックはIMEの変換に関係しないので、ここで消してしまって
        # 問題ない(<Key> で消すとIMEの変換を邪魔するので使わない)。
        if self._write_ph:
            self.write_zone.delete("1.0", tk.END)
            self._write_ph = False
            self._write_apply_ph_color()

    def _write_on_modified(self, _event=None):
        # <<Modified>> は自分の delete/insert(矢印の表示自体)でも飛んで
        # くるので、毎回まずフラグを下ろす(でないと二度と発火しなくなる)。
        self.write_zone.edit_modified(False)
        if not self._write_ph:
            return
        cur = self.write_zone.get("1.0", "end-1c")
        if cur == WRITE_MARK:
            return   # 矢印を表示しただけ(自分の変更)
        # 実際に何か入力された。「矢印+打った文字」のはずなのでそれを
        # 取り除く。
        if cur.startswith(WRITE_MARK):
            typed = cur[len(WRITE_MARK):]
        elif WRITE_MARK in cur:
            typed = cur.replace(WRITE_MARK, "")
        else:
            typed = cur
        if typed != cur:
            self.write_zone.delete("1.0", tk.END)
            if typed:
                self.write_zone.insert("1.0", typed)
        self._write_ph = False
        self._write_apply_ph_color()

    def _write_focus_out(self, _event=None):
        if not self.write_zone.get("1.0", "end-1c").strip():
            self._write_show_marker()

    def _on_return(self, event):
        if event.state & 0x0001:  # Shift+Enter は改行
            return
        self._send_current()
        return "break"

    def _send_current(self):
        if self.busy:
            return
        text = self.write_zone.get("1.0", tk.END).strip()
        # 矢印(WRITE_MARK)が本文の先頭に残ったまま送信されてしまう
        # 不具合があった(IMEの変換タイミングによっては_write_on_modified
        # の除去処理が効かないことがある)。_write_phの状態に関わらず、
        # 送信直前にここでも必ず取り除く(最後の砦)。
        mark = WRITE_MARK.strip()
        if text.startswith(mark):
            text = text[len(mark):].strip()
        if not text:
            return
        self._write_show_marker()            # 書き込み欄を矢印に戻す
        self._append(text, "you", anchor=True)
        self.note.yview("q_anchor")          # 送った自分の発言を画面の一番上へ
        self._set_busy(True)
        self.status_var.set(L("querying_status"))
        self._write({"t": "user", "text": text})

    def _on_close(self):
        try:
            self._write({"t": "quit"})
        except Exception:
            pass
        for p in (self.proc, self.cmd_proc):
            if p and p.poll() is None:
                try:
                    p.terminate()
                except Exception:
                    pass
        self.root.destroy()


def main():
    root = tk.Tk()
    AdvisorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
