# -*- coding: utf-8 -*-
"""
数据模型 -> 本地持久化的映射存储 sqlite

分三层：
1. model_nodes    —— 模型快照：连接服务器后自动扫描生成，可随时刷新
2. point_semantics—— 语义映射：人工 / AI 辅助 / 规则生成的别名与描述
3. mapping_rules  —— 映射规则：按 ref / DO 类型 / LN 类批量生成默认语义

设计要点：
- 语义表按 ref 关联快照表；模型刷新时语义不丢，消失的点只标记 stale
- origin 字段标记语义来源（manual / rule / ai_suggest / imported）可追溯单文件 SQLite
"""
import contextlib
import os
import re
import sqlite3
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.normpath(os.path.join(_HERE, "..", "data", "point_map.db"))

# 常见 LN 类（用于从 LN 名称中识别，避免误去掉 LLN0 的 0）
_COMMON_LN_CLASSES = {
    "LLN0", "LPHD", "GGIO", "GAPC", "MMXU", "MMXN", "MMTR", "MSQI", "MHAI",
    "CSWI", "XCBR", "XSWI", "CILO", "PTOC", "PTUV", "PDIS", "PDUP",
    "RBRF", "RSYN", "CBOP", "SIML", "ZSMI", "YPSH", "TTR", "LTMS", "LSVS",
}

# 内置默认规则：(模式, 匹配字段, 别名模板, 描述模板, 分类, 优先级)
#   匹配字段：ref      —— 数据对象引用包含模式（大小写不敏感）
#            do_type  —— 推断的 DO 类型（CDC）等于模式
#            ln_class —— LN 类等于模式
DEFAULT_RULES = [
    # ---- 按 ref / DO 名称特征 ----
    ("SPCSO",  "ref", "单点控制",   "遥控单点控制对象（SPC）",  "开关量", 100),
    ("DPCSO",  "ref", "双点控制",   "遥控双点控制对象（DPC）",  "开关量", 100),
    ("AnIn",   "ref", "模拟量输入", "遥测模拟量输入（MV）",     "遥测",   100),
    ("AnOut",  "ref", "模拟量输出", "遥测模拟量输出（MV）",     "遥测",   100),
    ("Beh",    "ref", "行为状态",   "LN 行为枚举状态（ENS）",   "遥信",   100),
    ("Health", "ref", "健康状态",   "装置健康状态（ENS）",      "遥信",   100),
    ("NamPlt", "ref", "铭牌信息",   "装置铭牌与版本信息（LPL）", "信息",   100),
    ("Loc",    "ref", "就地位置",   "就地/远方位置状态（SPS）", "遥信",   90),
    ("Pos",    "ref", "位置状态",   "开关位置状态（DPS）",      "开关量", 90),
    ("OpCnt",  "ref", "操作计数",   "操作次数统计（INS）",      "遥测",   90),
    # ---- 按 LN 类 ----
    ("GGIO",  "ln_class", "通用I/O",  "通用过程 I/O 逻辑节点",   "通用",   50),
    ("MMXU",  "ln_class", "测量单元", "三相测量逻辑节点（电压/电流/功率）", "遥测", 50),
    ("CSWI",  "ln_class", "开关控制", "开关控制逻辑节点",        "开关量", 50),
    ("XCBR",  "ln_class", "断路器",   "断路器逻辑节点",          "开关量", 50),
    ("XSWI",  "ln_class", "隔离开关", "隔离开关逻辑节点",        "开关量", 50),
    ("CILO",  "ln_class", "闭锁",     "联锁/闭锁逻辑节点",       "遥信",   50),
    ("PTOC",  "ln_class", "过流保护", "定时限/反时限过流保护",   "保护",   50),
    ("PTUV",  "ln_class", "低压保护", "欠压保护",                "保护",   50),
]

# DO 名称特征 -> 推断 CDC 类型（用于 do_type 字段，按列表顺序匹配）
_DO_TYPE_HINTS = [
    ("SPCSO", "SPC"), ("DPCSO", "DPC"), ("SPS", "SPS"), ("DPS", "DPS"),
    ("AnIn", "MV"), ("AnOut", "MV"),
    ("ENS", "ENS"), ("Beh", "ENS"), ("Health", "ENS"),
    ("OpCnt", "INS"), ("Pos", "DPS"),
    ("ASG", "ASG"), ("ISC", "ISC"), ("NamPlt", "LPL"),
]


def guess_do_type(do_name):
    """从 DO 名称推断 CDC 类型（尽力而为，推断不出返回 None）"""
    up = do_name.upper()
    for key, cdc in _DO_TYPE_HINTS:
        if key.upper() in up:
            return cdc
    return None


def split_ln_name(ln_name):
    """ 
    把 LN 名称拆为 (前缀, LN类, 实例号)
        如 'GGIO1' -> ('', 'GGIO', 1)；'Q01SB1.GGIO2' -> ('Q01SB1.', 'GGIO', 2)
        无法识别实例号时实例号记 0
    """
    prefix = ""
    name = ln_name
    if "." in ln_name:
        prefix, name = ln_name.rsplit(".", 1)
        prefix += "."
    if name.upper() in _COMMON_LN_CLASSES:
        inst = 0
        m = re.search(r"(\d+)$", name)
        if m:
            inst = int(m.group(1))
        return prefix, name.upper(), inst
    m = re.match(r"^([A-Za-z]+)(\d*)$", name)
    if not m:
        return prefix, name.upper(), 0
    cls, inst = m.group(1).upper(), m.group(2)
    return prefix, cls, int(inst) if inst else 0



class ModelStore(object):
    """IEC 61850 点表映射的本地存储（SQLite）"""

    def __init__(self, db_path=None):
        self.db_path = db_path or DEFAULT_DB
        d = os.path.dirname(self.db_path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        self._init_db()

    # ------------------------------------------------------------------
    # 数据库基础
    # ------------------------------------------------------------------
    def _conn(self):
        """返回一个上下文管理器退出时提交并关闭连接（Windows 下必须显式关闭，否则文件被占用无法删除/备份）"""
        @contextlib.contextmanager
        def _mgr():
            con = sqlite3.connect(self.db_path)
            con.row_factory = sqlite3.Row
            try:
                yield con
                con.commit()
            finally:
                con.close()
        return _mgr()

    def _init_db(self):
        with self._conn() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS model_nodes (
                    ref        TEXT PRIMARY KEY,   -- 完整引用 LD/LN.DO
                    server_id  TEXT NOT NULL,
                    ld_name    TEXT,
                    ln_name    TEXT,               -- LN 段（含前缀）
                    ln_class   TEXT,               -- LN 类，如 GGIO
                    do_name    TEXT,               -- DO 名称，如 SPCSO3
                    do_type    TEXT,               -- 推断的 CDC 类型
                    fcs        TEXT,               -- 功能约束集合，如 'ST,CO'
                    attrs      TEXT,               -- 带FC目录原文（$分隔）
                    scanned_at INTEGER,
                    stale      INTEGER DEFAULT 0
                )""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_nodes_srv "
                        "ON model_nodes(server_id)")
            con.execute("""
                CREATE TABLE IF NOT EXISTS point_semantics (
                    ref         TEXT PRIMARY KEY,
                    server_id   TEXT NOT NULL,
                    alias       TEXT,           -- 中文别名
                    description TEXT,           -- 语义描述
                    category    TEXT,           -- 分类：开关量/遥测/遥信...
                    tags        TEXT,           -- 自由标签，逗号分隔
                    unit        TEXT,           -- 工程量单位
                    scale       REAL,           -- 工程量系数
                    alarm_level INTEGER,        -- 告警等级
                    origin      TEXT DEFAULT 'manual',
                    updated_at  INTEGER,
                    stale       INTEGER DEFAULT 0
                )""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_sema_srv "
                        "ON point_semantics(server_id)")
            con.execute("""
                CREATE TABLE IF NOT EXISTS mapping_rules (
                    rule_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern    TEXT NOT NULL,   -- 匹配模式
                    match_on   TEXT NOT NULL,   -- ref / do_type / ln_class
                    alias_tpl  TEXT,
                    desc_tpl   TEXT,
                    category   TEXT,
                    priority   INTEGER DEFAULT 0,   -- 大者优先
                    enabled    INTEGER DEFAULT 1,
                    built_in   INTEGER DEFAULT 0
                )""")
            n = con.execute("SELECT COUNT(*) FROM mapping_rules").fetchone()[0]
            if n == 0:
                for pat, on, alias, desc, cat, pri in DEFAULT_RULES:
                    con.execute(
                        "INSERT INTO mapping_rules"
                        " (pattern, match_on, alias_tpl, desc_tpl, category,"
                        "  priority, enabled, built_in)"
                        " VALUES (?,?,?,?,?,?,1,1)",
                        (pat, on, alias, desc, cat, pri))

    # ------------------------------------------------------------------
    # 模型快照
    # ------------------------------------------------------------------
    def scan_model(self, client, server_id="default"):
        """
        扫描服务器全模型写入快照表
            :param client: core.connection.Client 实例（需已连接）
            :param server_id: 服务器标识，用于隔离多套模型
            :return: 扫描到的数据对象总数
        """
        now = time.time()  # 浮点时间戳，可区分同一秒内的多次扫描
        nodes = []
        for ln_ref in client.get_logical_node_refs():
            ld_name, ln_name = ln_ref.split("/", 1) if "/" in ln_ref \
                else ("", ln_ref)
            _, ln_class, _inst = split_ln_name(ln_name)
            for do_name in client.get_data_objects(ln_ref):
                do_ref = "%s.%s" % (ln_ref, do_name)
                fcs, attrs = set(), []
                try:
                    for entry in client.get_data_directory(do_ref, True):
                        attrs.append(entry)
                        if "$" in entry:
                            fcs.add(entry.rsplit("$", 1)[1].upper())
                        else:
                            fcs.add(entry.upper())
                except Exception:  # noqa: BLE001  单个 DO 目录失败不中断扫描
                    pass
                nodes.append((do_ref, server_id, ld_name, ln_name, ln_class,
                              do_name, guess_do_type(do_name),
                              ",".join(sorted(fcs)), "$".join(attrs), now))
        with self._conn() as con:
            con.executemany(
                "INSERT INTO model_nodes (ref, server_id, ld_name, ln_name,"
                " ln_class, do_name, do_type, fcs, attrs, scanned_at, stale)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,0)"
                " ON CONFLICT(ref) DO UPDATE SET server_id=excluded.server_id,"
                " ld_name=excluded.ld_name, ln_name=excluded.ln_name,"
                " ln_class=excluded.ln_class, do_name=excluded.do_name,"
                " do_type=excluded.do_type, fcs=excluded.fcs,"
                " attrs=excluded.attrs, scanned_at=excluded.scanned_at,"
                " stale=0", nodes)
            # 本 server 本次未扫到的点标记为 stale（不删除，语义保留）
            con.execute(
                "UPDATE model_nodes SET stale=1"
                " WHERE server_id=? AND scanned_at<>?",
                (server_id, now))
        return len(nodes)

    def get_nodes(self, server_id=None, stale=None, ln_class=None):
        """查询快照。stale=None 不过滤；True/False 按状态过滤"""
        sql, args = "SELECT * FROM model_nodes WHERE 1=1", []
        if server_id is not None:
            sql += " AND server_id=?"
            args.append(server_id)
        if stale is not None:
            sql += " AND stale=?"
            args.append(1 if stale else 0)
        if ln_class is not None:
            sql += " AND ln_class=?"
            args.append(ln_class.upper())
        sql += " ORDER BY ref"
        with self._conn() as con:
            return [dict(r) for r in con.execute(sql, args)]

    def find_node(self, ref):
        """按 ref 查快照，找不到返回 None（ref 大小写不敏感）"""
        with self._conn() as con:
            row = con.execute(
                "SELECT * FROM model_nodes WHERE ref=? COLLATE NOCASE",
                (ref,)).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # 语义映射 CRUD
    # ------------------------------------------------------------------
    def set_semantics(self, ref, server_id="default", alias=None,
                      description=None, category=None, tags=None, unit=None,
                      scale=None, alarm_level=None, origin="manual"):
        """新增/更新一条语义（None 字段保持原值）"""
        now = int(time.time())
        with self._conn() as con:
            old = con.execute("SELECT * FROM point_semantics WHERE ref=?"
                              " COLLATE NOCASE", (ref,)).fetchone()
            if old:
                vals = {"alias": alias, "description": description,
                        "category": category, "tags": tags, "unit": unit,
                        "scale": scale, "alarm_level": alarm_level}
                sets, args = ["origin=?", "updated_at=?", "stale=0"], [origin, now]
                for k, v in vals.items():
                    if v is not None:
                        sets.append("%s=?" % k)
                        args.append(v)
                args.append(ref)
                con.execute("UPDATE point_semantics SET %s WHERE ref=?"
                            % ", ".join(sets), args)
            else:
                con.execute(
                    "INSERT INTO point_semantics (ref, server_id, alias,"
                    " description, category, tags, unit, scale, alarm_level,"
                    " origin, updated_at, stale)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,0)",
                    (ref, server_id, alias, description, category, tags,
                     unit, scale, alarm_level, origin, now))

    def get_semantics(self, ref):
        """ 按 ref 查语义找不到返回 None """
        with self._conn() as con:
            row = con.execute("SELECT * FROM point_semantics WHERE ref=?"
                              " COLLATE NOCASE", (ref,)).fetchone()
        return dict(row) if row else None

    def list_semantics(self, server_id=None, category=None, stale=None):
        sql, args = "SELECT * FROM point_semantics WHERE 1=1", []
        if server_id is not None:
            sql += " AND server_id=?"
            args.append(server_id)
        if category is not None:
            sql += " AND category=?"
            args.append(category)
        if stale is not None:
            sql += " AND stale=?"
            args.append(1 if stale else 0)
        sql += " ORDER BY ref"
        with self._conn() as con:
            return [dict(r) for r in con.execute(sql, args)]

    def delete_semantics(self, ref):
        with self._conn() as con:
            con.execute("DELETE FROM point_semantics WHERE ref=?"
                        " COLLATE NOCASE", (ref,))

    def lookup(self, ref):
        """合并视图：快照 + 语义。返回 dict，node/semantics 可能为 None"""
        node = self.find_node(ref)
        sema = self.get_semantics(ref)
        out = {"ref": ref, "node": node, "semantics": sema}
        out["alias"] = (sema or {}).get("alias")
        out["description"] = (sema or {}).get("description")
        out["category"] = (sema or {}).get("category")
        return out

    # ------------------------------------------------------------------
    # 映射规则
    # ------------------------------------------------------------------
    def add_rule(self, pattern, match_on="ref", alias_tpl=None, desc_tpl=None,
                 category=None, priority=0):
        """新增自定义规则，返回 rule_id"""
        if match_on not in ("ref", "do_type", "ln_class"):
            raise ValueError("match_on 必须是 ref / do_type / ln_class")
        with self._conn() as con:
            cur = con.execute(
                "INSERT INTO mapping_rules (pattern, match_on, alias_tpl,"
                " desc_tpl, category, priority, enabled, built_in)"
                " VALUES (?,?,?,?,?,?,1,0)",
                (pattern, match_on, alias_tpl, desc_tpl, category, priority))
            return cur.lastrowid

    def list_rules(self, enabled_only=False):
        sql = "SELECT * FROM mapping_rules"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY priority DESC, rule_id"
        with self._conn() as con:
            return [dict(r) for r in con.execute(sql)]

    def set_rule_enabled(self, rule_id, enabled):
        with self._conn() as con:
            con.execute("UPDATE mapping_rules SET enabled=? WHERE rule_id=?",
                        (1 if enabled else 0, rule_id))

    def delete_rule(self, rule_id):
        """删除规则（内置规则不允许删除，只能停用）"""
        with self._conn() as con:
            row = con.execute("SELECT built_in FROM mapping_rules WHERE"
                              " rule_id=?", (rule_id,)).fetchone()
            if row and row["built_in"]:
                raise ValueError("内置规则不可删除，可 set_rule_enabled 停用")
            con.execute("DELETE FROM mapping_rules WHERE rule_id=?", (rule_id,))

    @staticmethod
    def _rule_hits(rule, node):
        """判断一条规则是否命中某快照节点"""
        on, pat = rule["match_on"], rule["pattern"]
        if on == "ref":
            return pat.upper() in (node["ref"] or "").upper()
        if on == "do_type":
            return (node["do_type"] or "").upper() == pat.upper()
        if on == "ln_class":
            return (node["ln_class"] or "").upper() == pat.upper()
        return False

    @staticmethod
    def _rule_sort_key(rule):
        """排序键：优先级大者优先；同级时 do_type > ln_class > ref（更具体者优先）"""
        order = {"do_type": 3, "ln_class": 2, "ref": 1}
        return (rule["priority"], order.get(rule["match_on"], 0))

    def _pick_rule(self, rules, node):
        """取命中节点且排序键最大的规则，未命中返回 None"""
        best = None
        for r in rules:
            if not self._rule_hits(r, node):
                continue
            if best is None or self._rule_sort_key(r) > self._rule_sort_key(best):
                best = r
        return best

    def apply_rules(self, server_id="default", overwrite=False, rule_id=None):
        """把规则批量应用到快照点上，生成 origin='rule' 的语义。

        :param overwrite: True 时覆盖已有规则来源的语义；False 只补空缺
        :param rule_id: 只应用指定规则；None 应用全部启用规则
        :return: 新写入/更新的语义条数
        """
        rules = [r for r in self.list_rules(enabled_only=True)
                 if rule_id is None or r["rule_id"] == rule_id]
        count = 0
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM model_nodes WHERE server_id=? AND stale=0",
                (server_id,)).fetchall()
            for row in rows:
                node = dict(row)
                rule = self._pick_rule(rules, node)
                if not rule:
                    continue
                old = con.execute(
                    "SELECT origin, alias FROM point_semantics WHERE ref=?"
                    " COLLATE NOCASE", (node["ref"],)).fetchone()
                # 已有人工语义的不被规则覆盖
                if old and old["origin"] == "manual" and old["alias"]:
                    continue
                # 只补空缺模式：已有任何语义则跳过
                if old and not overwrite:
                    continue
                con.execute(
                    "INSERT INTO point_semantics (ref, server_id, alias,"
                    " description, category, origin, updated_at, stale)"
                    " VALUES (?,?,?,?,?,'rule',?,0)"
                    " ON CONFLICT(ref) DO UPDATE SET alias=excluded.alias,"
                    " description=excluded.description,"
                    " category=excluded.category, origin='rule',"
                    " updated_at=excluded.updated_at, stale=0",
                    (node["ref"], server_id, rule["alias_tpl"],
                     rule["desc_tpl"], rule["category"], int(time.time())))
                count += 1
        return count

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def clear_model(self, server_id=None):
        """清空快照（可选按 server），语义表保留"""
        with self._conn() as con:
            if server_id is None:
                con.execute("DELETE FROM model_nodes")
            else:
                con.execute("DELETE FROM model_nodes WHERE server_id=?",
                            (server_id,))

    def stats(self):
        """简单统计：(快照点数, 语义条数, 规则数)"""
        with self._conn() as con:
            n = con.execute("SELECT COUNT(*) FROM model_nodes").fetchone()[0]
            s = con.execute("SELECT COUNT(*) FROM point_semantics").fetchone()[0]
            r = con.execute("SELECT COUNT(*) FROM mapping_rules").fetchone()[0]
        return n, s, r
