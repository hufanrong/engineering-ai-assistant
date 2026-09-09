# -*- coding: utf-8 -*-
"""tkinter 图形界面：添加文件/文件夹、选择输出目录、调整规则、开始处理、查看日志。"""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from dwg_cleaner import core, rules


class CleanerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DWG 竣工图清稿工具 v1.0")
        self.geometry("880x660")
        self.minsize(760, 560)

        self.cfg = rules.load_config()
        self.files = []
        self.msg_q = queue.Queue()
        self.stop_event = threading.Event()
        self._worker = None
        self._processing = False

        self._build_ui()
        self.after(120, self._poll_queue)

    # ---------- 界面 ----------

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # 输入文件
        frm_in = ttk.LabelFrame(self, text="① 输入文件（可多选 / 整个文件夹）")
        frm_in.pack(fill="x", **pad)
        row1 = ttk.Frame(frm_in)
        row1.pack(fill="x", padx=6, pady=4)
        ttk.Button(row1, text="添加 DWG 文件", command=self.add_files).pack(side="left", padx=(0, 6))
        ttk.Button(row1, text="添加文件夹", command=self.add_folder).pack(side="left", padx=(0, 6))
        self.recursive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row1, text="包含子目录", variable=self.recursive_var).pack(side="left", padx=(0, 6))
        ttk.Button(row1, text="移除选中", command=self.remove_selected).pack(side="left", padx=(0, 6))
        ttk.Button(row1, text="清空列表", command=self.clear_files).pack(side="left")
        self.file_list = tk.Listbox(frm_in, height=6, selectmode=tk.EXTENDED)
        self.file_list.pack(fill="x", padx=6, pady=(0, 6))

        # 输出目录
        frm_out = ttk.LabelFrame(self, text="② 输出文件夹")
        frm_out.pack(fill="x", **pad)
        row2 = ttk.Frame(frm_out)
        row2.pack(fill="x", padx=6, pady=4)
        self.out_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.out_var).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(row2, text="浏览…", command=self.choose_out).pack(side="left")
        ttk.Button(row2, text="打开输出文件夹", command=self.open_out).pack(side="left", padx=(6, 0))

        # 规则
        frm_cfg = ttk.LabelFrame(self, text="③ 清理规则（改后对本次处理生效，可随时改回）")
        frm_cfg.pack(fill="x", **pad)
        row3 = ttk.Frame(frm_cfg)
        row3.pack(fill="x", padx=6, pady=(4, 2))
        ttk.Label(row3, text="设计院关键词（逗号分隔）：").pack(side="left")
        self.inst_var = tk.StringVar(value=",".join(self.cfg["delete_keywords"]["institution"]))
        ttk.Entry(row3, textvariable=self.inst_var).pack(side="left", fill="x", expand=True, padx=6)
        row4 = ttk.Frame(frm_cfg)
        row4.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(row4, text="“施工图”字样：").pack(side="left")
        self.mode_var = tk.StringVar(value="replace")
        cb_mode = ttk.Combobox(row4, textvariable=self.mode_var, values=["replace", "delete"],
                               state="readonly", width=12)
        cb_mode.pack(side="left", padx=(4, 16))
        ttk.Label(row4, text="打印样式：").pack(side="left")
        self.style_var = tk.StringVar(value="mono")
        cb_style = ttk.Combobox(row4, textvariable=self.style_var, values=["mono", "color"],
                                state="readonly", width=8)
        cb_style.pack(side="left", padx=(4, 0))
        ttk.Label(row4, text="  （mono=黑白出图，color=按原色出图）").pack(side="left", padx=6)
        ttk.Label(row4, text="  | 保留：建设单位/施工单位/车间名称/图号等自动不动").pack(side="left", padx=6)

        # 操作
        frm_ops = ttk.Frame(self)
        frm_ops.pack(fill="x", **pad)
        self.start_btn = ttk.Button(frm_ops, text="开始处理", command=self.start)
        self.start_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = ttk.Button(frm_ops, text="停止", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 6))
        self.progress = ttk.Progressbar(frm_ops, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.progress_label = ttk.Label(frm_ops, text="")
        self.progress_label.pack(side="left", padx=6)

        # 日志
        frm_log = ttk.LabelFrame(self, text="④ 处理日志（实时）")
        frm_log.pack(fill="both", expand=True, **pad)
        self.log_txt = scrolledtext.ScrolledText(frm_log, height=12, state="disabled", wrap="word")
        self.log_txt.pack(fill="both", expand=True, padx=6, pady=6)

    # ---------- 文件操作 ----------

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="选择 DWG 图纸",
            filetypes=[("AutoCAD 图纸", "*.dwg"), ("所有文件", "*.*")],
        )
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.file_list.insert(tk.END, p)

    def add_folder(self):
        d = filedialog.askdirectory(title="选择图纸文件夹")
        if not d:
            return
        added = 0
        for root, dirs, fnames in os.walk(d):
            for fn in sorted(fnames):
                if fn.lower().endswith(".dwg"):
                    p = os.path.join(root, fn)
                    if p not in self.files:
                        self.files.append(p)
                        self.file_list.insert(tk.END, p)
                        added += 1
            if not self.recursive_var.get():
                break
        if added == 0:
            messagebox.showinfo("提示", "该文件夹下没有找到 DWG 文件")

    def remove_selected(self):
        sel = list(self.file_list.curselection())
        for idx in reversed(sel):
            self.file_list.delete(idx)
            del self.files[idx]

    def clear_files(self):
        self.file_list.delete(0, tk.END)
        self.files.clear()

    def choose_out(self):
        d = filedialog.askdirectory(title="选择输出文件夹")
        if d:
            self.out_var.set(d)

    def open_out(self):
        out = self.out_var.get().strip()
        if not out or not os.path.isdir(out):
            messagebox.showwarning("提示", "输出文件夹不存在，请先选择")
            return
        try:
            os.startfile(out)  # noqa: F821  Windows only
        except Exception as e:
            messagebox.showerror("错误", "无法打开文件夹：%s" % e)

    # ---------- 处理 ----------

    def start(self):
        if self._processing:
            return
        if not self.files:
            messagebox.showwarning("提示", "请先添加 DWG 文件")
            return
        out = self.out_var.get().strip()
        if not out:
            messagebox.showwarning("提示", "请选择输出文件夹")
            return

        # 按界面输入更新配置
        self.cfg = rules.load_config()
        inst = [k.strip() for k in self.inst_var.get().split(",") if k.strip()]
        if inst:
            self.cfg["delete_keywords"]["institution"] = inst
        self.cfg["drawing_type_mode"] = self.mode_var.get()
        self.cfg["plot"]["style_sheet"] = "monochrome.ctb" if self.style_var.get() == "mono" else ""

        self.stop_event.clear()
        self._processing = True
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.progress["maximum"] = len(self.files)
        self.progress["value"] = 0
        self.progress_label.config(text="0 / %d" % len(self.files))
        self.log("开始处理，共 %d 个文件" % len(self.files))

        files = list(self.files)
        out_dir = out
        self._worker = threading.Thread(target=self._run_worker, args=(files, out_dir), daemon=True)
        self._worker.start()

    def stop(self):
        self.stop_event.set()
        self.log("正在停止（当前文件处理完即停）……")

    def _run_worker(self, files, out_dir):
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            self.msg_q.put(("log", "无法创建输出目录：%s" % e))
            self.msg_q.put(("done", None))
            return
        for i, f in enumerate(files):
            if self.stop_event.is_set():
                self.msg_q.put(("log", "已按用户要求停止"))
                break
            self.msg_q.put(("file", i, len(files)))
            self.msg_q.put(("log", "[开始] %s" % os.path.basename(f)))
            try:
                r = core.process_file(f, out_dir, self.cfg, lambda m: self.msg_q.put(("log", m)))
                if r["status"] == "success":
                    self.msg_q.put(("log", "[完成] %s -> PDF %d 页" % (os.path.basename(f), r["pdf_pages"])))
                else:
                    self.msg_q.put(("log", "[失败] %s：%s" % (os.path.basename(f), r["error"])))
            except Exception as e:
                self.msg_q.put(("log", "[异常] %s：%s" % (os.path.basename(f), e)))
        self.msg_q.put(("done", None))

    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_q.get_nowait()
                if msg[0] == "log":
                    self.log(msg[1])
                elif msg[0] == "file":
                    _, i, total = msg
                    self.progress["value"] = i + 1
                    self.progress_label.config(text="%d / %d" % (i + 1, total))
                elif msg[0] == "done":
                    self._processing = False
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    self.log("全部处理结束")
                    out = self.out_var.get().strip()
                    if out and os.path.isdir(out):
                        if messagebox.askyesno("完成", "处理结束。是否打开输出文件夹查看结果？"):
                            self.open_out()
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def log(self, text):
        self.log_txt.config(state="normal")
        self.log_txt.insert(tk.END, text + "\n")
        self.log_txt.see(tk.END)
        self.log_txt.config(state="disabled")
