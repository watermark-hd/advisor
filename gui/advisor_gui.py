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
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox

CFG_PATH = os.path.expanduser("~/.claude-agent/gui.json")

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
        "dim": "#9a8f78", "err": "#a5341f", "rule": "#c7b58a", "code_bg": "#efe6cf",
        "input_bg": "#fffdf3", "input_fg": "#243b6b",
        "font": ("Hiragino Maru Gothic ProN", 15),
    },
    "coding": {
        "label": "コーディング", "prompt_prefix": True,
        "bg": "#1e1e1e", "fg": "#d4d4d4", "ai": "#cfcfcf", "prompt": "#c586c0",
        "dim": "#7a7a7a", "err": "#f48771", "rule": "#3a3a3a", "code_bg": "#252526",
        "input_bg": "#252526", "input_fg": "#d4d4d4",
        "font": ("Menlo", 13),
    },
    "hacker": {
        "label": "ハッカー", "prompt_prefix": True,
        "bg": "#000000", "fg": "#39ff5a", "ai": "#33dd88", "prompt": "#00e5ff",
        "dim": "#2e7d4f", "err": "#ff5555", "rule": "#2e9d55", "code_bg": "#041004",
        "input_bg": "#040804", "input_fg": "#39ff5a",
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
        self.root.geometry("760x600")
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
        self.model_label_var = tk.StringVar(value="…")
        self.status_var = tk.StringVar(value="起動中…")
        self.theme_name = load_cfg().get("theme", "paper")
        if self.theme_name not in THEMES:
            self.theme_name = "paper"

        self._build_ui()
        self._apply_theme(self.theme_name)
        self._start_backend()
        self.root.after(80, self._pump)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 画面 ----------
    def _build_ui(self):
        self.bar = tk.Frame(self.root)
        self.bar.pack(fill=tk.X)
        self.model_lbl = tk.Label(self.bar, textvariable=self.model_label_var)
        self.model_lbl.pack(side=tk.LEFT, padx=10, pady=6)

        # 見た目: プルダウン(各テーマをラジオ選択)
        self.theme_btn = tk.Menubutton(self.bar, relief=tk.RAISED)
        self.theme_menu = tk.Menu(self.theme_btn, tearoff=0)
        self.theme_btn.config(menu=self.theme_menu)
        self._theme_choice = tk.StringVar(value=self.theme_name)
        for key, spec in THEMES.items():
            self.theme_menu.add_radiobutton(
                label=spec["label"], value=key, variable=self._theme_choice,
                command=lambda k=key: self._choose_theme(k))
        self.theme_btn.pack(side=tk.RIGHT, padx=6, pady=4)

        self.switch_btn = tk.Menubutton(self.bar, text="AIを切替", relief=tk.RAISED)
        self.switch_menu = tk.Menu(self.switch_btn, tearoff=0)
        self.switch_btn.config(menu=self.switch_menu)
        self.switch_btn.pack(side=tk.RIGHT, padx=6, pady=4)

        # ヘッダー(gemini / ノート 等)の下の太線。ノートのタイトル罫のように。
        self.hdr_rule = tk.Frame(self.root, height=3)
        self.hdr_rule.pack(side=tk.TOP, fill=tk.X)

        # 下から順に固定で確保する(こうしないと会話欄が伸びて入力欄が
        # 画面外に押し出される)。ステータス → 入力欄 → の順に BOTTOM 詰め。
        self.status_lbl = tk.Label(self.root, textvariable=self.status_var, anchor=tk.W)
        self.status_lbl.pack(side=tk.BOTTOM, fill=tk.X)

        self.inbar = tk.Frame(self.root)
        self.inbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.entry = tk.Text(self.inbar, height=4, wrap=tk.WORD,
                             relief=tk.FLAT, highlightthickness=1, padx=8, pady=6)
        self.entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 4), pady=6)
        self.entry.bind("<Return>", self._on_return)
        self.send_btn = tk.Button(self.inbar, text="送信", width=6,
                                  command=self._send_current)
        self.send_btn.pack(side=tk.LEFT, padx=(0, 8), pady=6)

        # 会話ノート(残りの領域いっぱい)
        mid = tk.Frame(self.root)
        mid.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        # 左: ルーズリーフの穴(ノートモードだけ表示)
        self.holes = tk.Canvas(mid, width=34, highlightthickness=0)
        self.holes.pack(side=tk.LEFT, fill=tk.Y)
        self.holes.bind("<Configure>", lambda e: self._draw_holes())
        self.note = tk.Text(mid, wrap=tk.WORD, state=tk.DISABLED, height=1,
                            padx=18, pady=14, relief=tk.FLAT,
                            highlightthickness=0, spacing2=2)
        sb = tk.Scrollbar(mid, command=self.note.yview)
        self.note.config(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.note.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.note.bind("<Configure>", self._relayout)   # 幅が変わったら余白を再計算

    def _draw_holes(self):
        self.holes.delete("all")
        t = THEMES[self.theme_name]
        if not t.get("holes"):
            self.holes.config(width=1, bg=t["bg"])
            return
        self.holes.config(width=36, bg=t["bg"])
        h = self.holes.winfo_height() or 600
        hole = t.get("code_bg", "#e9e0c8")   # 紙より一段濃いグレー
        y = 44
        while y < h:
            # 穴本体(薄グレー) + 左下に濃いめの弧で影っぽく
            self.holes.create_oval(10, y - 9, 28, y + 9, fill=hole, outline=t["dim"])
            self.holes.create_arc(10, y - 9, 28, y + 9, start=120, extent=140,
                                  style=tk.ARC, outline=t["dim"], width=2)
            y += 60

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
        for b in (self.theme_btn, self.switch_btn):
            b.config(bg=t["bg"], fg=t["dim"], activebackground=t["bg"],
                     highlightbackground=t["bg"])
        self.hdr_rule.config(bg=t["dim"])                   # ヘッダー下の太線
        self.note.config(bg=t["bg"], fg=t["fg"], font=f, insertbackground=t["fg"])
        self.entry.config(bg=t["input_bg"], fg=t["input_fg"], font=f,
                          insertbackground=t["input_fg"],
                          highlightbackground=t["bg"], highlightcolor=t["dim"])
        self._draw_holes()

        # 色・書体・寄せだけ。左右の余白(1/3)は _relayout が幅から計算する。
        self.note.tag_config("you", foreground=t["fg"], justify=tk.RIGHT,
                             spacing1=3, spacing3=3)
        self.note.tag_config("ai", foreground=t["ai"], justify=tk.LEFT,
                             spacing1=3, spacing3=3)
        self.note.tag_config("prompt", foreground=t.get("prompt", t["fg"]),
                             justify=tk.RIGHT, font=(f[0], f[1], "bold"))
        self.note.tag_config("dim", foreground=t["dim"], justify=tk.LEFT,
                             spacing1=3, font=(f[0], f[1] - 2))
        self.note.tag_config("err", foreground=t["err"], justify=tk.LEFT, spacing1=3)
        self.note.tag_config("rule", foreground=t.get("rule", t["dim"]),
                             justify=tk.CENTER, lmargin1=0, lmargin2=0, rmargin=0,
                             font=(f[0], max(10, f[1] - 1)), spacing1=8, spacing3=8)
        self.note.tag_config("code", font=code_f, background=t.get("code_bg", t["bg"]),
                             lmargin1=f[1] * 3, lmargin2=f[1] * 3)
        self.theme_btn.config(text="見た目: " + t["label"] + " ▾")
        self._relayout()

    def _relayout(self, event=None):
        """幅の 1/3 を左右の余白に。自分=左1/3空け右寄せ / 相手=右1/3空け左寄せ。"""
        w = self.note.winfo_width()
        if w < 80:
            self.root.after(60, self._relayout)
            return
        third = int(w / 3)
        near = self.font[1]
        self.note.tag_config("you", lmargin1=third, lmargin2=third, rmargin=near)
        for tag in ("ai", "dim", "err"):
            self.note.tag_config(tag, lmargin1=near, lmargin2=near, rmargin=third)

    def _choose_theme(self, key):
        if key not in THEMES:
            return
        self._theme_choice.set(key)
        self._apply_theme(key)
        save_cfg({"theme": key})

    def _block_sep(self):
        """発言の切れ目に薄いヨコ線(中央)。先頭では入れない。"""
        if self.note.index("end-1c") != "1.0":
            self.note.insert(tk.END, "\n" + "─" * 40 + "\n", "rule")

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
            self._stream_append(str(obj.get("text", "")), "ai")
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
            self._ask_passphrase(obj.get("prompt", "パスフレーズ"))
        elif t == "turn_done":
            self._set_busy(False)
            self.status_var.set("")
        elif t == "bye":
            self.status_var.set("advisor を終了しました")
            self._set_busy(True)

    # ---------- 小物 ----------
    def _set_model(self, provider, model):
        self.model_label_var.set(f"{provider} / {model}" if provider else model)

    def _fill_menu(self, models):
        self.switch_menu.delete(0, tk.END)
        for i, m in enumerate(models, start=1):
            self.switch_menu.add_command(
                label=f"{i}. {m.get('label', m.get('id', '?'))}",
                command=lambda n=i: self._write({"t": "user", "text": str(n)}),
            )

    def _ask_passphrase(self, prompt):
        is_new = "新し" in prompt
        dlg = tk.Toplevel(self.root)
        dlg.title("パスフレーズ")
        dlg.transient(self.root)
        dlg.grab_set()
        tk.Label(dlg, text=prompt).pack(padx=16, pady=(14, 4))
        var = tk.StringVar()
        ent = tk.Entry(dlg, show="*", textvariable=var, width=32)
        ent.pack(padx=16, pady=6)
        ent.focus_set()

        var2, ent2 = tk.StringVar(), None
        if is_new:
            tk.Label(dlg, text="もう一度（確認）").pack(padx=16)
            ent2 = tk.Entry(dlg, show="*", textvariable=var2, width=32)
            ent2.pack(padx=16, pady=6)
        msg = tk.Label(dlg, text="", fg="#c0392b")
        msg.pack()

        def done(_=None):
            if is_new and var.get() != var2.get():
                msg.config(text="一致しません")
                return
            self._write({"t": "passphrase", "value": var.get()})
            dlg.destroy()

        ent.bind("<Return>", (lambda e: ent2.focus_set()) if is_new else done)
        if ent2 is not None:
            ent2.bind("<Return>", done)
        tk.Button(dlg, text="OK", command=done).pack(pady=(4, 14))
        dlg.protocol("WM_DELETE_WINDOW",
                     lambda: (self._write({"t": "passphrase", "value": ""}), dlg.destroy()))

    def _set_busy(self, busy):
        self.busy = busy
        self.send_btn.config(state=tk.DISABLED if busy else tk.NORMAL)

    def _on_return(self, event):
        if event.state & 0x0001:  # Shift+Enter は改行
            return
        self._send_current()
        return "break"

    def _send_current(self):
        if self.busy:
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
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    AdvisorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
