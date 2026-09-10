# -*- coding: utf-8 -*-
"""
联机验证脚本：扫描真实服务器 -> 应用规则 -> 打印映射结果

用法：python tests/verify_live.py [服务器IP] [端口]
默认 127.0.0.1:102（libiec61850 自带演示服务器）
需先连接并退出 GUI程序避免与 GUI 同时写同一个数据库文件
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core.connection import Client
from core.model_store import ModelStore


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 102
    sid = "%s:%d" % (host, port)

    print("连接 %s:%d ..." % (host, port))
    cli = Client()
    cli.connect(host, port)
    try:
        store = ModelStore()
        n = store.scan_model(cli, server_id=sid)
        print("模型扫描完成：%d 个数据对象" % n)
        cnt = store.apply_rules(server_id=sid)
        print("规则生成语义：%d 条" % cnt)

        print("\n映射结果（前 20 条）：")
        print("%-45s %-8s %-14s %s" % ("ref", "CDC", "别名", "分类"))
        print("-" * 90)
        for node in store.get_nodes(server_id=sid)[:20]:
            info = store.lookup(node["ref"])
            print("%-45s %-8s %-14s %s" % (
                node["ref"], node["do_type"] or "-",
                info["alias"] or "-", info["category"] or "-"))

        # 交互式查询
        while True:
            try:
                q = input("\n输入 ref 查询（回车空行退出）：").strip()
            except EOFError:
                break
            if not q:
                break
            info = store.lookup(q)
            if info["node"] is None and info["semantics"] is None:
                print("  未找到：%s" % q)
                continue
            print("  别名：%s" % (info["alias"] or "(无)"))
            print("  描述：%s" % (info["description"] or "(无)"))
            print("  分类：%s  来源：%s" % (
                info["category"] or "(无)",
                (info["semantics"] or {}).get("origin") or "(未映射)"))
    finally:
        cli.close()


if __name__ == "__main__":
    main()
