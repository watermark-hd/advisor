#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
advisor_gui.py  ―  advisor の1画面GUIフロントエンド(骨組み)

裏で `advisor gui`(= perl claude-agent.pl --gui)を起動し、1行1件のJSONで
やり取りする。入力は下のテキスト欄(OSの日本語入力がそのまま普通に使える)、
会話は上のログに出る。ターミナルを見せずに1つのアプリとして使うためのもの。

必要なもの: Python 3.x + tkinter(標準同梱)のみ。外部ライブラリ不要。
"""

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext


def find_advisor():
    """advisor コマンド(ラッパー)を探す。"""
    cand = [
        os.path.expanduser("~/bin/advisor"),
        "/usr/local/bin/advisor",
    ]
    for c in cand:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return "advisor"  # PATH 頼み


class AdvisorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Advisor")
        self.root.geometry("720x560")

        self.events = queue.Queue()      # 読み取りスレッド → メインスレッド
        self.proc = None
        self.busy = False                # 応答待ち中は送信を止める
        self.model_label_var = tk.StringVar(value="…")

        self._build_ui()
        self._start_backend()
        self.root.after(80, self._pump)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- UI ----------
    def _build_ui(self):
        top = tk.Frame(self.root, padx=8, pady=6)
        top.pack(fill=tk.X)
        tk.Label(top, textvariable=self.model_label_var, fg="#555").pack(side=tk.LEFT)
        self.switch_btn = tk.Menubutton(top, text="AIを切替", relief=tk.RAISED)
        self.switch_menu = tk.Menu(self.switch_btn, tearoff=0)
        self.switch_btn.config(menu=self.switch_menu)
        self.switch_btn.pack(side=tk.RIGHT)

        self.log = scrolledtext.ScrolledText(
            self.root, wrap=tk.WORD, font=("", 14), state=tk.DISABLED,
            padx=8, pady=8, bg="#fbfbfb",
        )
        self.log.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))
        self.log.tag_config("you", foreground="#0a5", font=("", 14, "bold"))
        self.log.tag_config("ai", foreground="#036")
        self.log.tag_config("note", foreground="#777")
        self.log.tag_config("err", foreground="#c00")
        self.log.tag_config("tool", foreground="#960")

        bottom = tk.Frame(self.root, padx=8, pady=6)
        bottom.pack(fill=tk.X)
        self.entry = tk.Text(bottom, height=3, wrap=tk.WORD, font=("", 14))
        self.entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.entry.bind("<Return>", self._on_return)
        self.entry.bind("<Shift-Return>", lambda e: None)  # 改行はそのまま
        self.send_btn = tk.Button(bottom, text="送信", width=6, command=self._send_current)
        self.send_btn.pack(side=tk.LEFT, padx=(6, 0))

        self.status_var = tk.StringVar(value="起動中…")
        tk.Label(self.root, textvariable=self.status_var, anchor=tk.W, fg="#666").pack(fill=tk.X, padx=10, pady=(0, 4))

    def _append(self, text, tag=None):
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, text, tag or ())
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)

    # ---------- バックエンド ----------
    def _start_backend(self):
        cmd = [find_advisor(), "gui"]
        try:
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
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

    # ---------- イベント処理(メインスレッド) ----------
    def _pump(self):
        try:
            while True:
                obj = self.events.get_nowait()
                self._handle(obj)
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def _handle(self, obj):
        t = obj.get("t")
        if t == "ready":
            self._set_model(obj.get("provider", ""), obj.get("model", ""))
            self._fill_menu(obj.get("models", []))
            hist = "暗号化して保存" if obj.get("history") else "保存しない"
            self.status_var.set(f"準備完了（履歴: {hist}）")
            self._set_busy(False)
        elif t == "text":
            self._append("\nAI: ", "ai")
            self._append(obj.get("text", "") + "\n", "ai")
        elif t == "note":
            self._append("\n" + obj.get("text", "") + "\n", "note")
        elif t == "error":
            self._append("\n" + obj.get("text", "") + "\n", "err")
        elif t == "tool":
            self._append(f"\n[道具] {obj.get('name','')}\n", "tool")
        elif t == "status":
            self.status_var.set(obj.get("text", "") or "")
        elif t == "model":
            self._set_model(obj.get("provider", ""), obj.get("model", ""))
        elif t == "confirm":
            ok = messagebox.askyesno("確認", f"AIが次のことをしようとしています:\n\n{obj.get('prompt','')}\n\n許可しますか？")
            self._write({"t": "reply", "value": "y" if ok else "n"})
        elif t == "need_passphrase":
            self._ask_passphrase(obj.get("prompt", "パスフレーズ"))
        elif t == "turn_done":
            self._set_busy(False)
            self.status_var.set("")
        elif t == "bye":
            self.status_var.set("終了しました")
            self._set_busy(True)

    # ---------- 小物 ----------
    def _set_model(self, provider, model):
        self.model_label_var.set(f"{provider} / {model}" if provider else model)

    def _fill_menu(self, models):
        self.switch_menu.delete(0, tk.END)
        for i, m in enumerate(models, start=1):
            label = m.get("label", m.get("id", "?"))
            self.switch_menu.add_command(
                label=f"{i}. {label}",
                command=lambda n=i: self._switch_to(n),
            )

    def _switch_to(self, n):
        # 番号だけの発言 = そのAIに切替(agent 側で解釈)
        self._write({"t": "user", "text": str(n)})

    def _ask_passphrase(self, prompt):
        dlg = tk.Toplevel(self.root)
        dlg.title("パスフレーズ")
        dlg.transient(self.root)
        dlg.grab_set()
        tk.Label(dlg, text=prompt, padx=16, pady=(14, 4)).pack()
        var = tk.StringVar()
        ent = tk.Entry(dlg, show="●", textvariable=var, width=32)
        ent.pack(padx=16, pady=6)
        ent.focus_set()

        def done(_=None):
            self._write({"t": "passphrase", "value": var.get()})
            dlg.destroy()

        ent.bind("<Return>", done)
        tk.Button(dlg, text="OK", command=done).pack(pady=(4, 14))
        dlg.protocol("WM_DELETE_WINDOW", lambda: (self._write({"t": "passphrase", "value": ""}), dlg.destroy()))

    def _set_busy(self, busy):
        self.busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self.send_btn.config(state=state)

    def _on_return(self, event):
        if event.state & 0x0001:  # Shift 押下 → 改行
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
        self._append(f"\nあなた: {text}\n", "you")
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
