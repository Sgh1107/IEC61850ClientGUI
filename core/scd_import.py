# -*- coding: utf-8 -*-
"""SCD/CID/ICD (SCL) 文件 desc 导入器。

把工程配置文件（IEC 61850-6 SCL）里每个 DOI / LN 的 `desc` 中文描述，
按 "LD/LN.DOI" 引用格式导入 model_store 的语义表（origin='imported'），
是点表语义最权威的来源，优先级高于规则生成（规则不会覆盖它）。

用法（代码）：
    from core.scd_import import import_scd
    n, skipped = import_scd(store, "工程.scd", ied_name="IED1",
                            server_id="192.168.0.10:102")

用法（命令行）：
    python -m core.scd_import 工程.scd [--ied IED1] [--server 192.168.0.10:102]

desc 取值优先级：DOI@desc > 所属 LN@desc > DOI 内第一个带 desc 的 DAI。
"""
import os
import sys
import xml.etree.ElementTree as ET


def _local(tag):
    """去掉 XML 命名空间前缀 {ns}IED -> IED"""
    return tag.rsplit("}", 1)[-1]


def _children(elem, names):
    """elem 的直接子元素中，本地标签名在 names 集合里的那些"""
    return [c for c in elem if _local(c.tag) in names]


def _descendants(elem, name):
    """按文档序递归查找本地标签名 == name 的元素"""
    out = []
    for c in elem.iter():
        if _local(c.tag) == name:
            out.append(c)
    return out


def _doi_desc(doi, ln_desc):
    """确定一个 DOI 的描述文本"""
    desc = doi.get("desc")
    if desc:
        return desc
    if ln_desc:
        return ln_desc
    # 兜底：DOI 内第一个带 desc 的 DAI/SDI
    for d in _descendants(doi, "DAI") + _descendants(doi, "SDI"):
        if d.get("desc"):
            return d.get("desc")
    return None


def parse_scd(scd_path, ied_name=None):
    """解析 SCL 文件，返回 [(ref, desc), ...] 列表。

    ref 格式与模型快照一致："LD实例/LN名.DOI名"，如
    "simpleIOGenericIO/GGIO1.SPCSO3"。LN 名 = prefix + lnClass + inst
    （LN0 无 prefix 时即为 LLN0）。
    """
    tree = ET.parse(scd_path)
    root = tree.getroot()
    out = []
    for ied in _descendants(root, "IED"):
        name = ied.get("name") or ""
        if ied_name and name != ied_name:
            continue
        for ap in _children(ied, {"AccessPoint"}):
            for server in _children(ap, {"Server"}):
                for ld in _children(server, {"LDevice"}):
                    ld_inst = ld.get("inst") or ""
                    for ln in _children(ld, {"LN0", "LN"}):
                        prefix = ln.get("prefix") or ""
                        ln_class = ln.get("lnClass") or ""
                        inst = ln.get("inst") or ""
                        ln_name = prefix + ln_class + inst
                        ln_desc = ln.get("desc")
                        for doi in _children(ln, {"DOI"}):
                            do_name = doi.get("name") or ""
                            desc = _doi_desc(doi, ln_desc)
                            if not desc:
                                continue
                            ref = "%s/%s.%s" % (ld_inst, ln_name, do_name)
                            out.append((ref, desc.strip()))
    return out


def import_scd(store, scd_path, ied_name=None, server_id="default",
               overwrite=False):
    """把 SCD 的 desc 导入语义表。

    :param store: core.model_store.ModelStore 实例
    :param overwrite: True 时覆盖已导入（imported）的语义；
                      人工语义（origin='manual' 且有 alias）始终不覆盖
    :return: (导入条数, 跳过条数)
    """
    entries = parse_scd(scd_path, ied_name)
    imported = skipped = 0
    for ref, desc in entries:
        old = store.get_semantics(ref)
        if old and old["origin"] == "manual" and old["alias"]:
            skipped += 1
            continue
        if old and old["origin"] == "imported" and not overwrite:
            skipped += 1
            continue
        # desc 较短时同时用作别名（点表描述通常是简洁中文短语）
        alias = desc if len(desc) <= 20 else None
        store.set_semantics(ref, server_id=server_id, alias=alias,
                            description=desc, origin="imported")
        imported += 1
    return imported, skipped


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------
def _main():
    import argparse
    from .model_store import ModelStore

    ap = argparse.ArgumentParser(description="SCD/CID/ICD desc 导入点表映射库")
    ap.add_argument("scd_file", help="SCD/CID/ICD 文件路径")
    ap.add_argument("--ied", default=None, help="只导入指定 IED name（默认全部）")
    ap.add_argument("--server", default="default",
                    help="语义表 server_id（默认 default）")
    ap.add_argument("--overwrite", action="store_true",
                    help="覆盖已导入的 desc（人工语义仍不覆盖）")
    args = ap.parse_args()

    if not os.path.isfile(args.scd_file):
        print("文件不存在：%s" % args.scd_file)
        sys.exit(1)

    store = ModelStore()
    entries = parse_scd(args.scd_file, args.ied)
    print("SCD 解析到 %d 条带 desc 的数据对象" % len(entries))
    imported, skipped = import_scd(store, args.scd_file, ied_name=args.ied,
                                   server_id=args.server,
                                   overwrite=args.overwrite)
    print("导入 %d 条，跳过 %d 条（已有同名来源或人工语义）" % (imported, skipped))


if __name__ == "__main__":
    _main()
