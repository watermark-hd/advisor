#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
advisor_gui.py  ―  advisor の1画面GUIフロントエンド

裏で `advisor gui`(= perl claude-agent.pl --gui)を起動し、1行1件のJSONで
やり取りする。入力は下のテキスト欄(OSの日本語入力がそのまま普通に使える。
Terminal.app の2バイト文字バグを回避できる)、会話は上の"ノート"に交互に
書かれていく。

見た目は2つ:
  - ノート : 生成りの紙に書いていく感じ。相手の返答は2文字ぶん字下げ。
  - ハッカー: 黒地に緑文字。

必要なもの: Python 3.x + tkinter(標準同梱)のみ。外部ライブラリ不要。
"""

import json
import os
import queue
import re
import signal
import subprocess
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

# 本文の左インセット(px)。ノート左の赤い縦罫(大学ノートの余白線)の
# すぐ右から書き始める、という要望に合わせた小さめの値。
EDGE = 10

# 書き込み欄が空のときに薄字で出しておく案内。「どこに書けばいいか
# わからない」という声を受けて、クリックすると消えるプレースホルダーに。
ENTRY_PLACEHOLDER = "ここに書いてください（Enterで送信）"

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
        "label": "ノート", "handwriting": True, "holes": True,
        "bg": "#f6efdc", "fg": "#243b6b", "ai": "#5a4636",   # 青黒インク / 茶
        "dim": "#9a8f78", "err": "#a5341f", "rule": "#d7b7ab", "code_bg": "#efe6cf",
        "line": "#c96b63",                                    # 昔のルーズリーフの赤い罫
        "hline": "#9fb0c9",                                   # 横罫線(紺グレー)。大学ノート風
        "vline": "#c96b63",                                   # 左の縦罫(赤)。書き始めの目印
        "input_bg": "#f6efdc", "input_fg": "#243b6b",
        "hl": {"kw": "#7a3b8f", "str": "#8a5a2b", "com": "#9a8f78", "num": "#3a5a3a"},
        "font": ("Hiragino Maru Gothic ProN", 12),  # 少し小さめにして行数を稼ぐ
    },
    "coding": {
        "label": "コーディング", "prompt_prefix": True,
        "bg": "#1e1e1e", "fg": "#d4d4d4", "ai": "#cfcfcf", "prompt": "#c586c0",
        "dim": "#7a7a7a", "err": "#f48771", "rule": "#3a3a3a", "code_bg": "#252526",
        "line": "#3a3a3a", "input_bg": "#1e1e1e", "input_fg": "#d4d4d4",
        "hl": {"kw": "#569cd6", "str": "#ce9178", "com": "#6a9955", "num": "#b5cea8"},
        "font": ("Menlo", 13),
    },
    "hacker": {
        "label": "ハッカー", "prompt_prefix": True,
        "bg": "#000000", "fg": "#39ff5a", "ai": "#33dd88", "prompt": "#00e5ff",
        "dim": "#2e7d4f", "err": "#ff5555", "rule": "#2e9d55", "code_bg": "#041004",
        "line": "#2e9d55", "input_bg": "#000000", "input_fg": "#39ff5a",
        "hl": {"kw": "#00e5ff", "str": "#9dff9d", "com": "#2e7d4f", "num": "#7fffd4"},
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


def find_advisor():
    for c in (os.path.expanduser("~/bin/advisor"), "/usr/local/bin/advisor"):
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return "advisor"


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
        self.status_var = tk.StringVar(value="起動中…")
        self.cmd_prompt_var = tk.StringVar(value="")
        self.theme_name = load_cfg().get("theme", "paper")
        if self.theme_name not in THEMES:
            self.theme_name = "paper"

        self._build_ui()
        self._apply_theme(self.theme_name)
        self._entry_show_placeholder()
        self._start_backend()
        self.root.after(80, self._pump)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 画面 ----------
    def _build_ui(self):
        self.bar = tk.Frame(self.root)
        self.bar.pack(fill=tk.X)

        # ヘッダーのボタン類は tk.Button/Menubutton だと macOS が独自の
        # 見た目(枠付きの部品)を勝手に描いてしまい、relief や色を変えても
        # 反映されない。tk.Label + クリックの組み合わせにすると、Tk自身が
        # 描画するので好きな見た目(会話タブと同じ手書き風)にできる。
        self.tab_chat = tk.Label(self.bar, text="会話", cursor="pointinghand", padx=3)
        self.tab_chat.bind("<Button-1>", lambda e: self._show_pane("chat"))
        self.tab_chat.pack(side=tk.LEFT, padx=(8, 1), pady=2)
        self.tab_cmd = tk.Label(self.bar, text="コマンド", cursor="pointinghand", padx=3)
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
                label=spec["label"], value=key, variable=self._theme_choice,
                command=lambda k=key: self._choose_theme(k))
        self.theme_btn.pack(side=tk.RIGHT, padx=6, pady=3)

        # 幅は固定せず文字なりに(固定幅にすると文字が欠けて矢印と重なるため)
        self.switch_btn = tk.Label(self.bar, text="AIを切替 ▾", cursor="pointinghand",
                                   padx=8, pady=2)
        self.switch_menu = tk.Menu(self.switch_btn, tearoff=0)
        self.switch_btn.bind("<Button-1>", lambda e: self._popup_menu(self.switch_menu, self.switch_btn))
        self.switch_btn.pack(side=tk.RIGHT, padx=6, pady=3)

        self.hist_btn = tk.Label(self.bar, text="続きから", cursor="pointinghand",
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

        self.status_lbl = tk.Label(self.chat_pane, textvariable=self.status_var,
                                   anchor=tk.W)
        self.status_lbl.pack(side=tk.BOTTOM, fill=tk.X)
        self.inbar = tk.Frame(self.chat_pane)
        self.inbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.in_rule = tk.Frame(self.chat_pane, height=1)
        self.in_rule.pack(side=tk.BOTTOM, fill=tk.X, padx=56)
        # 書き込み欄の左にもルーズリーフの穴を続ける(ノートの続きに見えるように)
        self.entry_holes = tk.Canvas(self.inbar, width=36, highlightthickness=0)
        self.entry_holes.pack(side=tk.LEFT, fill=tk.Y)
        self.entry_holes.bind("<Configure>", lambda e: self._request_draw_holes())
        self.entry = tk.Text(self.inbar, height=2, wrap=tk.CHAR,
                             relief=tk.FLAT, highlightthickness=0, padx=8, pady=6)
        # 書き込み欄の書き出しを、下の赤ラインの左端・解答の左端あたりに揃える
        # (左の穴の分だけ、ここでの余白は小さくてよい)
        self.entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 4), pady=6)
        self.entry.bind("<Return>", self._on_return)
        # プレースホルダーは <<Modified>> (中身が実際に変わった後の通知)
        # で消す。<Key> で消していたときは、日本語入力(IME)が変換を
        # 始める前の生のキー入力に割り込む形になり、1文字目だけ英字の
        # まま入ってしまう不具合があった。<<Modified>> は挿入が確定
        # した後に飛ぶのでIMEの変換を邪魔しない。
        self.entry.bind("<<Modified>>", self._entry_on_modified)
        self.entry.bind("<FocusOut>", self._entry_focus_out)
        self._entry_ph = False
        self.send_btn = tk.Button(self.inbar, text="送信", width=6,
                                  command=self._send_current)
        self.send_btn.pack(side=tk.LEFT, padx=(0, 8), pady=6)

        mid = tk.Frame(self.chat_pane)
        mid.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.holes = tk.Canvas(mid, width=34, highlightthickness=0)
        self.holes.pack(side=tk.LEFT, fill=tk.Y)
        self.holes.bind("<Configure>", lambda e: self._request_draw_holes())
        self.note = tk.Text(mid, wrap=tk.CHAR, state=tk.DISABLED, height=1,
                            padx=18, pady=14, relief=tk.FLAT,
                            highlightthickness=0, spacing2=2)
        sb = tk.Scrollbar(mid, command=self.note.yview)

        def _note_scrolled(*args):
            # 表示範囲が変わるたび(挿入・スクロールバー・マウスホイール
            # すべてここを通る)に横罫線を引き直す。ズレを溜めない。
            sb.set(*args)
            self._request_draw_rules()
        self.note.config(yscrollcommand=_note_scrolled)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.note.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.note.bind("<Configure>", self._relayout)

        # ================= コマンドペイン =================
        # 見た目はテーマに関係なく端末風(黒地)で固定。scp/ssh 用。
        CB, CF, CIN, CERR, CDIM = "#0f1115", "#d6d6d6", "#4ec9e6", "#ff6b6b", "#7a8088"
        self.cmd_pane = tk.Frame(self.pane_host, bg=CB)
        self.cmd_pane.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.cmd_row = tk.Frame(self.cmd_pane, bg=CB)
        self.cmd_row.pack(side=tk.BOTTOM, fill=tk.X)
        self.cmd_prompt = tk.Label(self.cmd_row, textvariable=self.cmd_prompt_var,
                                   anchor=tk.W, bg=CB, fg=CIN)
        self.cmd_prompt.pack(side=tk.LEFT, padx=(10, 2), pady=6)
        self.cmd_stop_btn = tk.Button(self.cmd_row, text="中止", width=5,
                                      state=tk.DISABLED, command=self._cmd_stop)
        self.cmd_stop_btn.pack(side=tk.RIGHT, padx=(2, 8), pady=6)
        self.cmd_entry = tk.Entry(self.cmd_row, relief=tk.FLAT, bg="#1a1d22",
                                  fg=CF, insertbackground=CF)
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4), pady=6)
        self.cmd_entry.bind("<Return>", lambda e: self._cmd_submit())
        self.cmd_entry.bind("<Up>", self._cmd_hist_prev)
        self.cmd_entry.bind("<Down>", self._cmd_hist_next)
        self.cmd_entry.bind("<Control-c>", lambda e: (self._cmd_stop(), "break")[1])
        self.cmd_hist = []          # コマンド履歴(このセッション限り)
        self.cmd_hist_idx = None
        cmid = tk.Frame(self.cmd_pane, bg=CB)
        cmid.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.cmd_out = tk.Text(cmid, wrap=tk.CHAR, state=tk.DISABLED, bg=CB, fg=CF,
                               padx=10, pady=8, relief=tk.FLAT, highlightthickness=0)
        self.cmd_out.tag_config("cin", foreground=CIN)
        self.cmd_out.tag_config("cerr", foreground=CERR)
        self.cmd_out.tag_config("cdim", foreground=CDIM)
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
        他モードは押しボタン風の枠。タブだけ選択中を太字にする。
        (全部 tk.Label なので activebackground 等 Button専用オプションは使えない)"""
        t = THEMES[self.theme_name]
        active = getattr(self, "pane", "chat")
        tabs = (("chat", self.tab_chat), ("cmd", self.tab_cmd))
        utils = (self.theme_btn, self.switch_btn, self.hist_btn)
        for name, btn in tabs:
            on = (name == active) or (name == "chat" and active not in ("chat", "cmd"))
            if self.theme_name == "paper":
                f = self.font
                fs = max(9, f[1] - 1)   # 少し小さめにして幅を詰める
                fnt = (f[0], fs, "bold", "underline") if on \
                    else (f[0], fs, "underline")
                btn.config(relief=tk.FLAT, bd=0, highlightthickness=0, font=fnt,
                           fg=(t["fg"] if on else t["dim"]), bg=t["bg"])
            else:
                tf = t["font"]
                btn.config(relief=(tk.SUNKEN if on else tk.RAISED), bd=2,
                           highlightthickness=0, font=(tf[0], tf[1]),
                           fg=t["dim"], bg=t["bg"])
        for btn in utils:
            if self.theme_name == "paper":
                f = self.font
                fs = max(10, f[1])   # 手書き風は小さいと潰れるので本文サイズのまま
                btn.config(relief=tk.FLAT, bd=0, highlightthickness=0,
                           font=(f[0], fs, "underline"), fg=t["dim"], bg=t["bg"])
            else:
                btn.config(relief=tk.RAISED, bd=1, highlightthickness=0,
                           font=("Hiragino Sans", 11), fg=t["dim"], bg=t["bg"])

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
            self._cmd_echo("(実行中です。中止 ボタンか Ctrl-C で止めてください)\n", "cdim")
            return
        cmd = self.cmd_entry.get().strip()
        if not cmd:
            return
        self.cmd_entry.delete(0, tk.END)
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
                self._cmd_echo("cd: そのフォルダはありません: %s\n" % target, "cerr")
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
            self.events.put({"t": "cmd_out", "text": "実行できません: %s\n" % e})
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
        self.cmd_entry.delete(0, tk.END)
        self.cmd_entry.insert(0, self.cmd_hist[self.cmd_hist_idx])
        return "break"

    def _cmd_hist_next(self, _e=None):
        if self.cmd_hist_idx is None:
            return "break"
        self.cmd_hist_idx += 1
        self.cmd_entry.delete(0, tk.END)
        if self.cmd_hist_idx >= len(self.cmd_hist):
            self.cmd_hist_idx = None            # 最新より下 = 空に
        else:
            self.cmd_entry.insert(0, self.cmd_hist[self.cmd_hist_idx])
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
        self._draw_holes_on(self.entry_holes)

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

    def _request_draw_rules(self):
        """_draw_rules を呼ぶ薄いラッパー。何度呼ばれても取りこぼさない
        よう after_idle 越しにまとめて1回呼ぶ。"""
        if getattr(self, "_rules_pending", False):
            return
        self._rules_pending = True

        def go():
            self._rules_pending = False
            self._draw_rules()
        self.root.after_idle(go)

    def _draw_rules(self, _event=None):
        """ノートモードだけ、本文の上に薄い横罫線を敷く(大学ノート風)。
        以前は「今Tkが実際に描いた行はどこか」を後から聞いて線を合わせて
        いたが、聞くタイミングによって微妙にズレることがあった。
        発想を逆にして、罫線を先に固定ピッチで敷き、本文の行送り
        (spacing1/2/3、_apply_theme で設定)をそのピッチにぴったり
        合わせる。行送りは自分で決めた値なので、ズレる余地がない。"""
        if not hasattr(self, "_rule_lines"):
            self._rule_lines = []
        color = THEMES[self.theme_name].get("hline")
        if not color:
            for ln in self._rule_lines:
                ln.place_forget()
            return
        h = self.note.winfo_height()
        if h < 20:
            for ln in self._rule_lines:
                ln.place_forget()
            return

        pitch = getattr(self, "pitch", self.font[1] + 14)
        ascent = getattr(self, "_font_ascent", int(self.font[1] * 0.9))
        descent = getattr(self, "_font_descent", int(self.font[1] * 0.25))

        # 罫線の基準位置は「今画面のいちばん上に見えている行」を実測して
        # 決める。dlineinfo の ly はスクロール後の実際の画面Y座標を返す
        # ので、pad(先頭行の上の余白)を足すのは間違いだった―スクロール
        # した後は先頭行が画面上端に来るわけではないので、そのぶんズレて
        # いた。ly をそのまま使えばスクロール位置に関係なく合う。
        gap = max(1, pitch - ascent - descent)
        # 文字は下の線のすぐ下に来るよう、すき間の頭のほうに小さく置く
        # (clearance が大きいと線が次の行に寄って「文字が上寄り」に見える)。
        clearance = max(3, min(gap - 2, int(round(descent * 0.8)) + 2))
        first = None
        try:
            top_idx = self.note.index("@0,0")
            info = self.note.dlineinfo(top_idx)
            if info:
                _x, ly, _w, _lh, baseline = info
                if baseline > 0:
                    first = ly + baseline + clearance
        except tk.TclError:
            pass
        if first is None:
            try:
                pad = int(str(self.note.cget("pady")) or 0)
            except ValueError:
                pad = 14
            first = pad + ascent + descent + clearance
        need = max(0, int((h - first) // pitch) + 1)

        while len(self._rule_lines) < need:
            self._rule_lines.append(
                tk.Frame(self.note, height=1, bd=0, highlightthickness=0))
        for i, ln in enumerate(self._rule_lines):
            if i < need:
                ln.config(bg=color)
                ln.place(in_=self.note, x=0, relwidth=1.0,
                         y=int(first + i * pitch), height=1)
            else:
                ln.place_forget()

    def _apply_theme(self, name):
        t = THEMES[name]
        self.theme_name = name
        f = pick_font(*t["font"]) if t.get("handwriting") else t["font"]
        self.font = f
        code_f = ("Menlo", f[1] - 1)

        self.root.config(bg=t["bg"])
        for w in (self.bar, self.inbar):
            w.config(bg=t["bg"])                            # ヘッダーも本文と同色
        self.model_lbl.config(bg=t["bg"], fg=t["dim"], font=(f[0], f[1] - 2))
        self.status_lbl.config(bg=t["bg"], fg=t["dim"], font=(f[0], 10))
        self._style_tabs()  # 見た目/AI切替/続きから の3つもここでまとめて設定
        self.cmd_out.config(font=code_f)
        self.cmd_entry.config(font=code_f)
        self.cmd_prompt.config(font=code_f)
        line = t.get("line", t["dim"])
        self.hdr_rule.config(bg=line)                       # ヘッダー下の罫線
        self.in_rule.config(bg=line)                        # 入力欄の上の罫線
        self.note.config(bg=t["bg"], fg=t["fg"], font=f, insertbackground=t["fg"])
        # 入力欄はモード間で高さを揃えるためフォントサイズを 13 で頭打ちに。
        entry_fg = t["dim"] if getattr(self, "_entry_ph", False) else t["input_fg"]
        self.entry.config(bg=t["bg"], fg=entry_fg, font=(f[0], min(f[1], 13)),
                          insertbackground=t["input_fg"])

        # 罫線の考え方を変えた: 今までは「今Tkが実際に描いた行はどこか」を
        # 後から聞いて線を合わせようとしていたが、タイミングによってズレる
        # ことがあった。今回は逆に「罫線の間隔(ピッチ)を先に決めて、本文の
        # 行送りをそのピッチにぴったり合わせる」方式にする。行送りは
        # spacing1=0 / spacing2=spacing3=S で自分で決めた値そのものなので、
        # フォントの ascent+descent(実測)+ S が必ずピッチになる。
        try:
            fm = tkfont.Font(font=f)
            ascent = fm.metrics("ascent")
            descent = fm.metrics("descent")
        except Exception:
            ascent, descent = int(f[1] * 0.9), int(f[1] * 0.25)
        S = max(14, int(round(f[1] * 1.1)))   # 罫線ぶんのすき間(狭すぎて文字と
                                               # くっついて見えるとの指摘で拡大)
        self._font_ascent = ascent
        self._font_descent = descent
        self.pitch = ascent + descent + S
        self.note.config(spacing1=0, spacing2=S, spacing3=S)
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
        self.note.tag_config("rule", foreground=t.get("rule", t["dim"]),
                             justify=tk.CENTER, lmargin1=0, lmargin2=0, rmargin=0,
                             font=f, spacing1=0, spacing2=S, spacing3=S)
        self.note.tag_config("code", font=code_f, background=t.get("code_bg", t["bg"]),
                             lmargin1=f[1] * 3, lmargin2=f[1] * 3)
        hl = t.get("hl", {})
        for key, tag in HL_TAG.items():
            self.note.tag_config(tag, foreground=hl.get(key, t["ai"]), font=code_f,
                                 background=t.get("code_bg", t["bg"]))
        self.theme_btn.config(text=t["label"] + " ▾")  # 「見た目: 」は省いて幅を詰める
        self._relayout()

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
        self._request_draw_rules()

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
        """発言の切れ目に空の1行(罫線1本ぶん)。先頭では入れない。
        大学ノートの「1行あけて書く」感じ。行の縦リズムも崩さない。"""
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
            return
        chunk = "".join(chars[:24])
        del chars[:24]
        self.note.config(state=tk.NORMAL)
        self.note.insert(tk.END, chunk, tag)
        self.note.config(state=tk.DISABLED)
        self.root.after(18, lambda: self._stream_step(chars, tag))

    def note_has_anchor(self):
        try:
            self.note.index("q_anchor")
            return True
        except tk.TclError:
            return False

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
        if self.note_has_anchor():
            self.note.yview("q_anchor")

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
        try:
            self.proc = subprocess.Popen(
                [find_advisor(), "gui"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=1,
                universal_newlines=True, encoding="utf-8",
            )
        except OSError as e:
            messagebox.showerror("起動できません", f"advisor を起動できませんでした:\n{e}")
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
                    self._append(f"(内部エラー: {e})", "err")
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def _handle(self, obj):
        t = obj.get("t")
        if t == "ready":
            self._set_model(obj.get("provider", ""), obj.get("model", ""))
            self._fill_menu(obj.get("models", []))
            hist = "暗号化保存" if obj.get("history") else "保存しない"
            self.status_var.set(f"準備完了（履歴: {hist}）")
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
            self._append(f"— {obj.get('name', '')} を使います —", "dim")
        elif t == "status":
            self.status_var.set(obj.get("text", "") or "")
        elif t == "model":
            self._set_model(obj.get("provider", ""), obj.get("model", ""))
        elif t == "confirm":
            ok = messagebox.askyesno(
                "確認",
                f"AIが次のことをしようとしています:\n\n{obj.get('prompt', '')}\n\n許可しますか？")
            self._write({"t": "reply", "value": "y" if ok else "n"})
        elif t == "need_passphrase":
            self._ask_passphrase(obj.get("prompt", "パスフレーズ"),
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
            self._cmd_echo("[終了 %s]\n" % rc, "cerr" if rc else "cdim")
            self.cmd_proc = None
            self._cmd_set_running(False)
        elif t == "bye":
            self.status_var.set("advisor を終了しました")
            self._set_busy(True)

    # ---------- 小物 ----------
    def _set_model(self, provider, model):
        # 「provider / model」は長すぎてヘッダーを圧迫するので、モデル名だけ表示。
        self.model_label_var.set(model or provider)

    def _fill_menu(self, models):
        self.switch_menu.delete(0, tk.END)
        for i, m in enumerate(models, start=1):
            self.switch_menu.add_command(
                label=f"{i}. {m.get('label', m.get('id', '?'))}",
                command=lambda n=i: self._write({"t": "user", "text": str(n)}),
            )

    def _ask_passphrase(self, prompt, recover=False):
        # 確認欄はなし(1回だけ)。打ち間違い対策は「合言葉」で担保する。
        dlg = tk.Toplevel(self.root)
        dlg.title("パスフレーズ")
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
        tk.Button(btns, text="OK", command=done).pack(side=tk.LEFT, padx=4)
        if recover:
            def use_recovery():
                self._write({"t": "passphrase", "recover": 1})
                dlg.destroy()
            tk.Button(btns, text="合言葉で復旧", command=use_recovery).pack(side=tk.LEFT, padx=4)
        dlg.protocol("WM_DELETE_WINDOW",
                     lambda: (self._write({"t": "passphrase", "value": ""}), dlg.destroy()))

    def _ask_recovery(self, mode, question):
        # 合言葉(秘密の質問)。mode="new"=初回設定(質問+答え)、
        # mode="unlock"=復旧(答えだけ)。答えは大文字小文字・前後空白を区別しない。
        dlg = tk.Toplevel(self.root)
        dlg.title("合言葉")
        dlg.transient(self.root)
        dlg.grab_set()
        q_var = tk.StringVar(value=question)
        a_var = tk.StringVar()

        if mode == "new":
            tk.Label(dlg, justify=tk.LEFT, text=(
                "パスフレーズを忘れたときの復旧用です(必須)。\n"
                "あなたにしか答えられない質問にしてください。\n"
                "例: 初めて買った車の名前は？").rstrip()).pack(padx=16, pady=(14, 6))
            tk.Label(dlg, text="質問").pack(anchor="w", padx=16)
            q_ent = tk.Entry(dlg, textvariable=q_var, width=36)
            q_ent.pack(padx=16, pady=(0, 6))
            q_ent.focus_set()
        else:
            tk.Label(dlg, text="合言葉で履歴を復旧します。").pack(padx=16, pady=(14, 6))
            tk.Label(dlg, text=("質問: " + (question or "?"))).pack(anchor="w", padx=16)

        tk.Label(dlg, text="答え").pack(anchor="w", padx=16)
        a_ent = tk.Entry(dlg, textvariable=a_var, width=36)
        a_ent.pack(padx=16, pady=(0, 6))
        if mode != "new":
            a_ent.focus_set()

        def done(_=None):
            self._write({"t": "recovery",
                         "question": q_var.get(), "answer": a_var.get()})
            dlg.destroy()

        a_ent.bind("<Return>", done)
        tk.Button(dlg, text="OK", command=done).pack(pady=(4, 14))
        dlg.protocol("WM_DELETE_WINDOW",
                     lambda: (self._write({"t": "recovery", "question": "", "answer": ""}),
                              dlg.destroy()))

    # ---------- 続きから(過去の会話) ----------
    def _show_history_dialog(self, items):
        if not items:
            messagebox.showinfo("続きから", "保存された会話がありません。")
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("続きから")
        dlg.transient(self.root)
        dlg.geometry("560x360")
        tk.Label(dlg, text="続きから始める会話を選んでください").pack(padx=10, pady=(10, 2))
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
        tk.Button(btnf, text="開く", command=choose).pack(side=tk.RIGHT)
        tk.Button(btnf, text="やめる", command=dlg.destroy).pack(side=tk.RIGHT, padx=(0, 6))

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
            self._append(f"（{page[0]}ページ目 / 全{page[1]}ページ）", "dim")
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
        self._append("（ここまで読み込みました。続きをどうぞ）", "dim")
        self._show_pane("chat")
        self.note.see(tk.END)

    def _set_busy(self, busy):
        self.busy = busy
        self.send_btn.config(state=tk.DISABLED if busy else tk.NORMAL)

    def _entry_show_placeholder(self):
        self.entry.delete("1.0", tk.END)
        self.entry.insert("1.0", ENTRY_PLACEHOLDER)
        self._entry_ph = True
        self._entry_apply_ph_color()

    def _entry_apply_ph_color(self):
        t = THEMES[self.theme_name]
        self.entry.config(fg=(t["dim"] if self._entry_ph else t["input_fg"]))

    def _entry_on_modified(self, _event=None):
        # <<Modified>> は自分の delete/insert(プレースホルダーの表示自体)
        # でも飛んでくるので、毎回まずフラグを下ろす(でないと二度と
        # 発火しなくなる)。
        self.entry.edit_modified(False)
        if not self._entry_ph:
            return
        cur = self.entry.get("1.0", "end-1c")
        if cur == ENTRY_PLACEHOLDER:
            return   # プレースホルダーを表示しただけ(自分の変更)
        # 実際に何か入力された。カーソルは表示時にプレースホルダーの
        # 末尾にあるはずなので、普通は「プレースホルダー+打った文字」に
        # なっている。プレースホルダー部分だけ取り除いて、打った分を残す。
        if cur.startswith(ENTRY_PLACEHOLDER):
            typed = cur[len(ENTRY_PLACEHOLDER):]
            self.entry.delete("1.0", tk.END)
            if typed:
                self.entry.insert("1.0", typed)
        self._entry_ph = False
        self._entry_apply_ph_color()

    def _entry_focus_out(self, _event=None):
        if not self.entry.get("1.0", "end-1c").strip():
            self._entry_show_placeholder()

    def _on_return(self, event):
        if event.state & 0x0001:  # Shift+Enter は改行
            return
        self._send_current()
        return "break"

    def _send_current(self):
        if self.busy or self._entry_ph:
            return
        text = self.entry.get("1.0", tk.END).strip()
        if not text:
            return
        self.entry.delete("1.0", tk.END)
        self._append(text, "you", anchor=True)
        self.note.yview("q_anchor")          # 送った自分の発言を画面の一番上へ
        self._set_busy(True)
        self.status_var.set("問い合わせ中…")
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
