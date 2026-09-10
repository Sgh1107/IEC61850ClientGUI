# -*- coding: utf-8 -*-
"""
点表映射标签页：模型快照浏览 + 语义编辑 + 规则管理 + SCD 导入
布局：
    ┌────────────── 工具栏：刷新 / 应用规则 / SCD 导入 ──────────────┐
    │ ┌──── 点表列表（可搜索）────┐ ┌──── 选中点语义编辑 ────┐      │
    │ │ ref 别名 分类 来源 状态    │ │ 别名/描述/分类/单位... │      │
    │ └──────────────────────────┘ └───────────────────────┘      │
    │ ┌──────────────── 映射规则管理（启停/增删/应用）──────────┐    │
    └──────────────────────────────────────────────────────────────┘

所有写库操作（保存语义、删语义、应用规则、SCD 导入、删规则）
都会先弹窗向用户展示将要做的事，点"是"才执行——人工确认优先。
"""
import os
import tkinter as tk
from tkinter import filedialog, messagebox

import ttkbootstrap as tb
from ttkbootstrap.constants import PRIMARY, SUCCESS, SECONDARY, DANGER, INFO

from core.scd_import import import_scd, parse_scd

_CATEGORIES = ["开关量", "遥信", "遥测", "遥控", "保护", "信息", "通用", "其他"]
_ORIGIN_NAMES = {"manual": "人工", "imported": "SCD", "rule": "规则", "ai_suggest": "AI"}


class MappingTab(tb.Frame):
    def __init__(self, app):
        super().__init__(app, padding=(10, 8))
        self.app = app
        self._current_ref = ""
        self._build()
        self.refresh_points()

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build(self):
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(1, weight=3)
        self.rowconfigure(2, weight=2)

        # ---------- 工具栏 ----------
        bar = tb.Frame(self)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        tb.Button(bar, text="⟳ 刷新点表", bootstyle=SECONDARY + "-outline",
                  command=self.refresh_points).pack(side="left")
        self.overwrite_var = tk.BooleanVar(value=False)
        tb.Checkbutton(bar, text="覆盖已有语义", variable=self.overwrite_var,
                       bootstyle="round-toggle").pack(side="left", padx=(10, 0))
        tb.Button(bar, text="⚙ 应用规则", bootstyle=INFO,
                  command=self.on_apply_rules).pack(side="left", padx=(10, 0))
        tb.Button(bar, text="📄 导入 SCD desc", bootstyle=PRIMARY,
                  command=self.on_import_scd).pack(side="left", padx=(10, 0))
        self.stat_var = tk.StringVar(value="")
        tb.Label(bar, textvariable=self.stat_var,
                 bootstyle=SECONDARY).pack(side="right")

        # ---------- 左：点表列表 ----------
        left = tb.Labelframe(self, text=" 📋 点表（点击选中后右侧编辑） ",
                             padding=6)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        srow = tb.Frame(left)
        srow.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        tb.Label(srow, text="搜索:").pack(side="left")
        self.search_var = tk.StringVar()
        ent = tb.Entry(srow, textvariable=self.search_var)
        ent.pack(side="left", fill="x", expand=True, padx=6)
        ent.bind("<KeyRelease>", lambda _e: self.refresh_points())
        self.stale_var = tk.BooleanVar(value=False)
        tb.Checkbutton(srow, text="只看失效点", variable=self.stale_var,
                       bootstyle="round-toggle",
                       command=self.refresh_points).pack(side="left")

        cols = ("alias", "category", "origin", "stale", "ref")
        self.table = tb.Treeview(left, columns=cols, show="headings",
                                 bootstyle=PRIMARY)
        for cid, text, width, stretch in (
                ("alias", "别名", 130, True), ("category", "分类", 70, False),
                ("origin", "来源", 55, False), ("stale", "状态", 45, False),
                ("ref", "引用 (LD/LN.DO)", 320, True)):
            self.table.heading(cid, text=text, anchor="w")
            self.table.column(cid, width=width, anchor="w", stretch=stretch)
        vsb = tb.Scrollbar(left, orient="vertical", command=self.table.yview,
                           bootstyle="round")
        self.table.configure(yscrollcommand=vsb.set)
        self.table.grid(row=1, column=0, sticky="nsew")
        vsb.grid(row=1, column=1, sticky="ns")
        self.table.bind("<<TreeviewSelect>>", self._on_select)

        # ---------- 右：选中点语义编辑 ----------
        edit = tb.Labelframe(self, text=" ✏ 语义映射（人工确认后保存） ",
                             padding=8)
        edit.grid(row=1, column=1, sticky="nsew")
        edit.columnconfigure(1, weight=1)

        self.node_var = tk.StringVar(value="（在左侧选择一个点）")
        tb.Label(edit, textvariable=self.node_var, font=("Consolas", 10, "bold"),
                 bootstyle=PRIMARY, wraplength=330,
                 anchor="w").grid(row=0, column=0, columnspan=2, sticky="ew")
        self.meta_var = tk.StringVar(value="")
        tb.Label(edit, textvariable=self.meta_var,
                 bootstyle=SECONDARY, wraplength=330,
                 anchor="w").grid(row=1, column=0, columnspan=2, sticky="ew",
                                  pady=(2, 6))

        def field(row, label, wide=False):
            tb.Label(edit, text=label).grid(row=row, column=0, sticky="ne",
                                            pady=(4 if wide else 3, 0))
            frame = tb.Frame(edit)
            frame.grid(row=row, column=1, sticky="ew", padx=(8, 0),
                       pady=(4 if wide else 3, 0))
            frame.columnconfigure(0, weight=1)
            return frame

        f = field(2, "别名:")
        self.alias_var = tk.StringVar()
        tb.Entry(f, textvariable=self.alias_var).grid(row=0, column=0,
                                                      sticky="ew")
        f = field(3, "描述:", wide=True)
        self.desc_var = tk.StringVar()
        tb.Entry(f, textvariable=self.desc_var).grid(row=0, column=0,
                                                     sticky="ew")
        f = field(4, "分类:")
        self.cat_var = tk.StringVar()
        tb.Combobox(f, textvariable=self.cat_var, values=_CATEGORIES).grid(
            row=0, column=0, sticky="ew")
        f = field(5, "单位 / 系数:")
        self.unit_var = tk.StringVar()
        self.scale_var = tk.StringVar()
        tb.Entry(f, textvariable=self.unit_var, width=9).grid(row=0, column=0,
                                                              sticky="w")
        tb.Entry(f, textvariable=self.scale_var, width=9).grid(row=0, column=1,
                                                               sticky="w")
        f = field(6, "标签 / 告警级:")
        self.tags_var = tk.StringVar()
        self.alarm_var = tk.StringVar()
        tb.Entry(f, textvariable=self.tags_var, width=9).grid(row=0, column=0,
                                                              sticky="w")
        tb.Entry(f, textvariable=self.alarm_var, width=9).grid(row=0, column=1,
                                                               sticky="w")

        brow = tb.Frame(edit)
        brow.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        tb.Button(brow, text="💾 保存（人工确认）", bootstyle=SUCCESS,
                  command=self.on_save).pack(side="left")
        tb.Button(brow, text="🗑 清除该点语义", bootstyle=DANGER + "-outline",
                  command=self.on_delete_semantics).pack(side="left", padx=(8, 0))
        self.origin_var = tk.StringVar(value="")
        tb.Label(brow, textvariable=self.origin_var,
                 bootstyle=INFO).pack(side="right")

        # ---------- 底：规则管理 ----------
        rules = tb.Labelframe(self, text=" ⚙ 映射规则（按优先级批量生成默认语义） ",
                              padding=6)
        rules.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        rules.columnconfigure(0, weight=1)
        rules.rowconfigure(0, weight=1)

        rcols = ("rid", "pattern", "match_on", "alias", "category",
                 "priority", "enabled", "built_in")
        self.rules = tb.Treeview(rules, columns=rcols, show="headings",
                                 bootstyle=PRIMARY, height=6)
        for cid, text, width, stretch in (
                ("rid", "ID", 40, False), ("pattern", "模式", 110, True),
                ("match_on", "匹配方式", 75, False),
                ("alias", "别名模板", 110, True),
                ("category", "分类", 70, False),
                ("priority", "优先级", 60, False),
                ("enabled", "启用", 45, False),
                ("built_in", "内置", 45, False)):
            self.rules.heading(cid, text=text, anchor="w")
            self.rules.column(cid, width=width, anchor="w", stretch=stretch)
        rvsb = tb.Scrollbar(rules, orient="vertical", command=self.rules.yview,
                            bootstyle="round")
        self.rules.configure(yscrollcommand=rvsb.set)
        self.rules.grid(row=0, column=0, sticky="nsew")
        rvsb.grid(row=0, column=1, sticky="ns")

        rbar = tb.Frame(rules)
        rbar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        tb.Button(rbar, text="⟳ 刷新规则", bootstyle=SECONDARY + "-outline",
                  command=self.refresh_rules).pack(side="left")
        tb.Button(rbar, text="⏯ 启用/停用选中规则",
                  bootstyle=INFO + "-outline",
                  command=self.on_toggle_rule).pack(side="left", padx=(8, 0))
        tb.Button(rbar, text="🗑 删除选中规则（需确认）",
                  bootstyle=DANGER + "-outline",
                  command=self.on_delete_rule).pack(side="left", padx=(8, 0))

        add = tb.Frame(rules)
        add.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        tb.Label(add, text="新增规则:").pack(side="left")
        self.np_var = tk.StringVar()
        self.nm_var = tk.StringVar(value="ref")
        self.na_var = tk.StringVar()
        self.nc_var = tk.StringVar()
        tb.Entry(add, textvariable=self.np_var, width=14).pack(side="left",
                                                               padx=(6, 2))
        tb.Combobox(add, textvariable=self.nm_var, width=9, state="readonly",
                    values=("ref", "do_type", "ln_class")).pack(side="left",
                                                                padx=2)
        tb.Entry(add, textvariable=self.na_var, width=14).pack(side="left",
                                                               padx=2)
        tb.Combobox(add, textvariable=self.nc_var, width=9,
                    values=_CATEGORIES).pack(side="left", padx=2)
        tb.Button(add, text="＋ 添加", bootstyle=SUCCESS + "-outline",
                  command=self.on_add_rule).pack(side="left", padx=(8, 0))

        self.refresh_rules()

    # ------------------------------------------------------------------
    # 点表列表
    # ------------------------------------------------------------------
    def refresh_points(self):
        store = self.app.model_store
        kw = self.search_var.get().strip()
        nodes = store.get_nodes()          # 全部 server 的快照
        sema = {s["ref"].lower(): s for s in store.list_semantics()}
        self.table.delete(*self.table.get_children(""))
        for n in nodes:
            s = sema.get(n["ref"].lower())
            alias = (s or {}).get("alias") or ""
            cat = (s or {}).get("category") or ""
            origin = _ORIGIN_NAMES.get((s or {}).get("origin") or "", "")
            stale = "失效" if n["stale"] else "正常"
            if self.stale_var.get() and not n["stale"]:
                continue
            if kw and kw.lower() not in n["ref"].lower() \
                    and kw not in alias and kw not in cat:
                continue
            self.table.insert("", "end",
                              values=(alias, cat, origin, stale, n["ref"]))
        nn, ns, nr = store.stats()
        self.stat_var.set("快照 %d 点 ｜ 语义 %d 条 ｜ 规则 %d 条" % (nn, ns, nr))

    def _on_select(self, _e=None):
        sel = self.table.selection()
        if not sel:
            return
        ref = self.table.item(sel[0], "values")[-1]
        self._current_ref = ref
        self.node_var.set(ref)
        node = self.app.model_store.find_node(ref)
        self.meta_var.set("LN类: %s ｜ DO: %s ｜ CDC: %s ｜ FC: %s" % (
            node.get("ln_class") or "-", node.get("do_name") or "-",
            node.get("do_type") or "未知", node.get("fcs") or "-"))
        s = self.app.model_store.get_semantics(ref) or {}
        self.alias_var.set(s.get("alias") or "")
        self.desc_var.set(s.get("description") or "")
        self.cat_var.set(s.get("category") or "")
        self.unit_var.set(s.get("unit") or "")
        self.tags_var.set(s.get("tags") or "")
        self.scale_var.set("" if s.get("scale") is None else str(s["scale"]))
        self.alarm_var.set("" if s.get("alarm_level") is None
                           else str(s["alarm_level"]))
        origin = s.get("origin")
        self.origin_var.set("当前来源: " + _ORIGIN_NAMES.get(origin, "未映射")
                            if origin else "当前来源: 未映射")

    # ------------------------------------------------------------------
    # 语义编辑（全部需人工确认）
    # ------------------------------------------------------------------
    def on_save(self):
        ref = self._current_ref
        if not ref:
            messagebox.showinfo("提示", "请先在左侧点表中选择一个点", parent=self)
            return
        scale = None
        if self.scale_var.get().strip():
            try:
                scale = float(self.scale_var.get().strip())
            except ValueError:
                messagebox.showerror("错误", "系数必须是数字", parent=self)
                return
        alarm = None
        if self.alarm_var.get().strip():
            try:
                alarm = int(self.alarm_var.get().strip())
            except ValueError:
                messagebox.showerror("错误", "告警等级必须是整数", parent=self)
                return
        old = self.app.model_store.get_semantics(ref) or {}
        summary = ("确认保存以下人工语义？\n\n引用: %s\n\n"
                   "别名: %s%s\n描述: %s\n分类: %s\n单位: %s ｜ 系数: %s\n"
                   "标签: %s ｜ 告警级: %s\n\n保存后来源标记为「人工」，"
                   "规则和 SCD 导入都不会覆盖它。") % (
            ref,
            self.alias_var.get().strip() or "(空)",
            ("（原: %s）" % old["alias"]) if old.get("alias") else "",
            self.desc_var.get().strip() or "(空)",
            self.cat_var.get().strip() or "(空)",
            self.unit_var.get().strip() or "(空)",
            scale if scale is not None else "(空)",
            self.tags_var.get().strip() or "(空)",
            alarm if alarm is not None else "(空)")
        if not messagebox.askyesno("人工确认 — 保存语义", summary, parent=self):
            self.app.set_status("已取消保存语义")
            return
        try:
            self.app.model_store.set_semantics(
                ref, server_id=self.app._server_id(),
                alias=self.alias_var.get().strip() or None,
                description=self.desc_var.get().strip() or None,
                category=self.cat_var.get().strip() or None,
                tags=self.tags_var.get().strip() or None,
                unit=self.unit_var.get().strip() or None,
                scale=scale, alarm_level=alarm, origin="manual")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("错误", "保存失败：%s" % e, parent=self)
            return
        self.app.set_status("已保存人工语义：%s" % ref)
        self.refresh_points()
        self._on_select()

    def on_delete_semantics(self):
        ref = self._current_ref
        if not ref:
            messagebox.showinfo("提示", "请先在左侧点表中选择一个点", parent=self)
            return
        s = self.app.model_store.get_semantics(ref)
        if not s:
            messagebox.showinfo("提示", "该点当前没有语义映射", parent=self)
            return
        if not messagebox.askyesno(
                "人工确认 — 清除语义",
                "确认清除该点的语义映射？\n\n引用: %s\n别名: %s\n来源: %s"
                % (ref, s.get("alias") or "(无)",
                   _ORIGIN_NAMES.get(s.get("origin") or "", "?")),
                parent=self):
            self.app.set_status("已取消清除语义")
            return
        try:
            self.app.model_store.delete_semantics(ref)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("错误", "清除失败：%s" % e, parent=self)
            return
        self.app.set_status("已清除语义：%s" % ref)
        self.refresh_points()
        self._on_select()

    def on_apply_rules(self):
        store = self.app.model_store
        overwrite = self.overwrite_var.get()
        n = len(store.get_nodes(stale=False))
        if n == 0:
            messagebox.showinfo("提示",
                                "点表为空：请先连接服务器扫描模型，或检查数据库",
                                parent=self)
            return
        msg = ("将把启用的映射规则批量应用到 %d 个活跃快照点上。\n\n"
               "模式: %s\n\n规则只补空缺语义；人工确认过的语义不会被覆盖。"
               % (n, "覆盖已有规则来源的语义" if overwrite else "只补空缺"))
        if not messagebox.askyesno("人工确认 — 应用规则", msg, parent=self):
            self.app.set_status("已取消应用规则")
            return
        try:
            cnt = store.apply_rules(server_id=self.app._server_id(),
                                    overwrite=overwrite)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("错误", "应用规则失败：%s" % e, parent=self)
            return
        self.app.set_status("应用规则完成：本次写入/更新 %d 条语义" % cnt)
        self.refresh_points()

    def on_import_scd(self):
        path = filedialog.askopenfilename(
            title="选择 SCD/CID/ICD 文件",
            filetypes=[("SCL 工程文件", "*.scd *.cid *.icd"),
                       ("所有文件", "*.*")], parent=self)
        if not path:
            return
        store = self.app.model_store
        try:
            entries = parse_scd(path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("错误", "SCD 解析失败：%s" % e, parent=self)
            return
        if not entries:
            messagebox.showinfo("提示",
                                "文件中没有找到带 desc 的数据对象", parent=self)
            return
        preview = "\n".join("  %s → %s" % (r, d) for r, d in entries[:8])
        more = "\n  …（共 %d 条）" % len(entries) if len(entries) > 8 else ""
        if not messagebox.askyesno(
                "人工确认 — 导入 SCD desc",
                "从 %s 解析到 %d 条描述，将导入语义表（来源=SCD）：\n\n%s%s\n\n"
                "人工语义不会被覆盖。是否继续？"
                % (os.path.basename(path), len(entries), preview, more),
                parent=self):
            self.app.set_status("已取消 SCD 导入")
            return
        try:
            imported, skipped = import_scd(
                store, path, server_id=self.app._server_id(),
                overwrite=self.overwrite_var.get())
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("错误", "导入失败：%s" % e, parent=self)
            return
        self.app.set_status("SCD 导入完成：新增/更新 %d 条，跳过 %d 条"
                            % (imported, skipped))
        self.refresh_points()

    # ------------------------------------------------------------------
    # 规则管理
    # ------------------------------------------------------------------
    def refresh_rules(self):
        self.rules.delete(*self.rules.get_children(""))
        for r in self.app.model_store.list_rules():
            self.rules.insert("", "end", values=(
                r["rule_id"], r["pattern"], r["match_on"],
                r["alias_tpl"] or "", r["category"] or "", r["priority"],
                "是" if r["enabled"] else "否",
                "是" if r["built_in"] else "否"))

    def _selected_rule(self):
        sel = self.rules.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在规则列表中选择一条规则",
                                parent=self)
            return None
        vals = self.rules.item(sel[0], "values")
        return int(vals[0]), vals

    def on_toggle_rule(self):
        item = self._selected_rule()
        if not item:
            return
        rid, vals = item
        enabled = vals[6] == "是"
        try:
            self.app.model_store.set_rule_enabled(rid, not enabled)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("错误", "操作失败：%s" % e, parent=self)
            return
        self.app.set_status("规则 #%d 已%s" % (rid, "启用" if not enabled
                                              else "停用"))
        self.refresh_rules()

    def on_delete_rule(self):
        item = self._selected_rule()
        if not item:
            return
        rid, vals = item
        if vals[7] == "是":
            messagebox.showwarning(
                "不可删除", "内置规则（ID=%d）不能删除，只能启用/停用。" % rid,
                parent=self)
            return
        if not messagebox.askyesno(
                "人工确认 — 删除规则",
                "确认删除规则 #%d ？\n\n模式: %s（%s）\n别名模板: %s\n\n"
                "已生成的语义不会被删除。" % (rid, vals[1], vals[2], vals[3]),
                parent=self):
            self.app.set_status("已取消删除规则")
            return
        try:
            self.app.model_store.delete_rule(rid)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("错误", "删除失败：%s" % e, parent=self)
            return
        self.app.set_status("已删除规则 #%d" % rid)
        self.refresh_rules()

    def on_add_rule(self):
        pattern = self.np_var.get().strip()
        if not pattern:
            messagebox.showinfo("提示", "请输入规则匹配模式", parent=self)
            return
        alias = self.na_var.get().strip()
        if not alias:
            messagebox.showinfo("提示", "请输入别名模板（命中后显示的名字）",
                                parent=self)
            return
        if not messagebox.askyesno(
                "人工确认 — 新增规则",
                "确认新增规则？\n\n模式: %s（按 %s 匹配）\n别名模板: %s\n"
                "分类: %s\n优先级: 0" % (pattern, self.nm_var.get(), alias,
                                        self.nc_var.get().strip() or "(空)"),
                parent=self):
            self.app.set_status("已取消新增规则")
            return
        try:
            rid = self.app.model_store.add_rule(
                pattern, match_on=self.nm_var.get(), alias_tpl=alias,
                category=self.nc_var.get().strip() or None, priority=0)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("错误", "添加失败：%s" % e, parent=self)
            return
        self.app.set_status("已添加规则 #%d：%s" % (rid, pattern))
        for var in (self.np_var, self.na_var, self.nc_var):
            var.set("")
        self.refresh_rules()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def on_state_change(self):
        pass   # 数据库操作不依赖连接状态，随时可用

    def on_disconnecting(self):
        pass
