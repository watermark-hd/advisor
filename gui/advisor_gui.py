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

# テーマ定義。fg=自分の字, ai=相手の字, dim=補足(道具/お知らせ), err=エラー。
THEMES = {
    "paper": {
        "label": "ノート",
        "bg": "#faf7ef", "fg": "#2b2b2b", "ai": "#1f3b57",
        "dim": "#8a8578", "err": "#a5341f",
        "input_bg": "#fffdf6", "input_fg": "#2b2b2b",
        "bar_bg": "#efe9db", "bar_fg": "#5a5343",
        "font": ("Hiragino Sans", 14), "mono": False,
    },
    "hacker": {
        "label": "ハッカー",
        "bg": "#000000", "fg": "#39ff5a", "ai": "#26c2a0",
        "dim": "#2e7d4f", "err": "#ff5555",
        "input_bg": "#050805", "input_fg": "#39ff5a",
        "bar_bg": "#0a0f0a", "bar_fg": "#2e7d4f",
        "font": ("Menlo", 13), "mono": True,
    },
}


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

        self.theme_btn = tk.Button(self.bar, text="見た目", relief=tk.FLAT,
                                   command=self._toggle_theme)
        self.theme_btn.pack(side=tk.RIGHT, padx=6, pady=4)
        self.switch_btn = tk.Menubutton(self.bar, text="AIを切替", relief=tk.RAISED)
        self.switch_menu = tk.Menu(self.switch_btn, tearoff=0)
        self.switch_btn.config(menu=self.switch_menu)
        self.switch_btn.pack(side=tk.RIGHT, padx=6, pady=4)

        # ノート本体
        mid = tk.Frame(self.root)
        mid.pack(fill=tk.BOTH, expand=True)
        self.note = tk.Text(mid, wrap=tk.WORD, state=tk.DISABLED,
                            padx=18, pady=14, relief=tk.FLAT,
                            highlightthickness=0, spacing2=2)
        sb = tk.Scrollbar(mid, command=self.note.yview)
        self.note.config(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.note.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 入力欄
        self.inbar = tk.Frame(self.root)
        self.inbar.pack(fill=tk.X)
        self.entry = tk.Text(self.inbar, height=3, wrap=tk.WORD,
                             relief=tk.FLAT, highlightthickness=1, padx=8, pady=6)
        self.entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 4), pady=6)
        self.entry.bind("<Return>", self._on_return)
        self.send_btn = tk.Button(self.inbar, text="送信", width=6,
                                  command=self._send_current)
        self.send_btn.pack(side=tk.LEFT, padx=(0, 8), pady=6)

        self.status_lbl = tk.Label(self.root, textvariable=self.status_var, anchor=tk.W)
        self.status_lbl.pack(fill=tk.X)

    def _apply_theme(self, name):
        t = THEMES[name]
        self.theme_name = name
        f = t["font"]
        self.root.config(bg=t["bg"])
        for w in (self.bar, self.inbar):
            w.config(bg=t["bar_bg"])
        self.model_lbl.config(bg=t["bar_bg"], fg=t["bar_fg"])
        self.status_lbl.config(bg=t["bar_bg"], fg=t["bar_fg"], font=(f[0], 10))
        for b in (self.theme_btn, self.switch_btn):
            b.config(bg=t["bar_bg"], fg=t["bar_fg"],
                     activebackground=t["bar_bg"], highlightbackground=t["bar_bg"])
        self.note.config(bg=t["bg"], fg=t["fg"], font=f,
                         insertbackground=t["fg"])
        self.entry.config(bg=t["input_bg"], fg=t["input_fg"], font=f,
                          insertbackground=t["input_fg"],
                          highlightbackground=t["bar_bg"],
                          highlightcolor=t["dim"])
        # タグ: 自分は左端、相手は2文字ぶん字下げ。名前ラベルは付けない。
        indent = f[1] * 2 + 8  # おおよそ全角2文字ぶん
        self.note.tag_config("you", foreground=t["fg"],
                             lmargin1=6, lmargin2=6, spacing1=10, spacing3=2)
        self.note.tag_config("ai", foreground=t["ai"],
                             lmargin1=indent, lmargin2=indent, spacing1=10, spacing3=2)
        self.note.tag_config("dim", foreground=t["dim"], lmargin1=indent,
                             lmargin2=indent, spacing1=6, font=(f[0], f[1] - 2))
        self.note.tag_config("err", foreground=t["err"], lmargin1=indent,
                             lmargin2=indent, spacing1=6)
        self.theme_btn.config(text="見た目: " + t["label"])

    def _toggle_theme(self):
        order = list(THEMES.keys())
        nxt = order[(order.index(self.theme_name) + 1) % len(order)]
        self._apply_theme(nxt)
        save_cfg({"theme": nxt})

    def _append(self, text, tag):
        self.note.config(state=tk.NORMAL)
        if self.note.index("end-1c") != "1.0":
            self.note.insert(tk.END, "\n")
        self.note.insert(tk.END, text.rstrip("\n"), tag)
        self.note.insert(tk.END, "\n")
        self.note.see(tk.END)
        self.note.config(state=tk.DISABLED)

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
            self._append(str(obj.get("text", "")), "ai")
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
        self._append(text, "you")
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
