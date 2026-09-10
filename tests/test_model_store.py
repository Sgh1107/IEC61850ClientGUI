# -*- coding: utf-8 -*-
"""
core/model_store.py 的自验证测试（不依赖 libiec61850 / 真实 IED）

运行：python tests/test_model_store.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core.model_store import ModelStore, guess_do_type, split_ln_name


class FakeClient(object):
    """ 模拟 core.connection.Client 的模型枚举接口 """

    def get_logical_node_refs(self):
        return ["simpleIOGenericIO/LLN0", "simpleIOGenericIO/GGIO1",
                "ensecvt/MMXU1"]

    def get_data_objects(self, ln_ref):
        return {"simpleIOGenericIO/LLN0": ["Beh", "NamPlt"],
                "simpleIOGenericIO/GGIO1": ["SPCSO1", "SPCSO2", "SPCSO3",
                                            "AnIn1", "Ind1"],
                "ensecvt/MMXU1": ["A", "TotW"]}[ln_ref]

    def get_data_directory(self, do_ref, with_fc=False):
        data = {
            "simpleIOGenericIO/GGIO1.SPCSO3": ["stVal$ST", "ctlVal$CO", "q$ST"],
            "simpleIOGenericIO/GGIO1.AnIn1": ["mag$MX", "q$MX"],
            "simpleIOGenericIO/LLN0.Beh": ["stVal$ST"],
        }
        return data.get(do_ref, ["stVal$ST"])


class TestHelpers(unittest.TestCase):
    def test_guess_do_type(self):
        self.assertEqual(guess_do_type("SPCSO3"), "SPC")
        self.assertEqual(guess_do_type("AnIn1"), "MV")
        self.assertEqual(guess_do_type("Beh"), "ENS")
        self.assertIsNone(guess_do_type("Something123"))

    def test_split_ln_name(self):
        self.assertEqual(split_ln_name("GGIO1"), ("", "GGIO", 1))
        self.assertEqual(split_ln_name("LLN0"), ("", "LLN0", 0))
        self.assertEqual(split_ln_name("Q01SB1.GGIO2"), ("Q01SB1.", "GGIO", 2))


class TestModelStore(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(path)
        self.db = path
        self.store = ModelStore(path)

    def tearDown(self):
        if os.path.exists(self.db):
            os.remove(self.db)

    def test_scan_and_rules(self):
        n = self.store.scan_model(FakeClient(), server_id="demo")
        self.assertEqual(n, 9)  # 2 + 5 + 2 个 DO
        nodes = self.store.get_nodes(server_id="demo")
        self.assertEqual(len(nodes), 9)
        # SPCSO3 快照正确，FC 提取正确
        node = self.store.find_node("simpleIOGenericIO/GGIO1.SPCSO3")
        self.assertIsNotNone(node)
        self.assertEqual(node["do_type"], "SPC")
        self.assertIn("ST", node["fcs"].split(","))
        self.assertIn("CO", node["fcs"].split(","))
        self.assertEqual(node["ln_class"], "GGIO")
        # 大小写不敏感查找
        self.assertIsNotNone(
            self.store.find_node("SIMPLEIOGENERICIO/GGIO1.SPCSO3"))

        # 规则批量生成语义
        cnt = self.store.apply_rules(server_id="demo")
        self.assertEqual(cnt, 9)
        sema = self.store.get_semantics("simpleIOGenericIO/GGIO1.SPCSO3")
        self.assertEqual(sema["alias"], "单点控制")
        self.assertEqual(sema["origin"], "rule")
        self.assertEqual(sema["category"], "开关量")
        # LLN0.Beh -> 行为状态（ref 特征规则）
        beh = self.store.get_semantics("simpleIOGenericIO/LLN0.Beh")
        self.assertEqual(beh["alias"], "行为状态")
        # MMXU1.A 没有命中 ref 特征，命中 ln_class=MMXU 规则
        a = self.store.get_semantics("ensecvt/MMXU1.A")
        self.assertEqual(a["alias"], "测量单元")

    def test_manual_semantics_protected(self):
        self.store.scan_model(FakeClient(), server_id="demo")
        ref = "simpleIOGenericIO/GGIO1.SPCSO3"
        self.store.set_semantics(ref, server_id="demo", alias="1号开关",
                                 description="车间1号断路器遥控点")
        # 再应用规则，人工语义不被覆盖
        self.store.apply_rules(server_id="demo", overwrite=True)
        sema = self.store.get_semantics(ref)
        self.assertEqual(sema["alias"], "1号开关")
        self.assertEqual(sema["origin"], "manual")
        self.assertEqual(sema["description"], "车间1号断路器遥控点")

    def test_set_semantics_partial_update(self):
        self.store.set_semantics("x/y.Z", alias="甲", category="遥测")
        self.store.set_semantics("x/y.Z", description="描述")  # 部分更新
        sema = self.store.get_semantics("X/Y.Z")
        self.assertEqual(sema["alias"], "甲")
        self.assertEqual(sema["category"], "遥测")
        self.assertEqual(sema["description"], "描述")

    def test_stale_marking(self):
        self.store.scan_model(FakeClient(), server_id="demo")

        class SmallerClient(FakeClient):
            def get_data_objects(self, ln_ref):
                return ["SPCSO1"] if ln_ref.endswith("GGIO1") \
                    else super().get_data_objects(ln_ref)

        self.store.scan_model(SmallerClient(), server_id="demo")
        self.assertEqual(
            self.store.find_node("simpleIOGenericIO/GGIO1.SPCSO3")["stale"], 1)
        self.assertEqual(
            self.store.find_node("simpleIOGenericIO/GGIO1.SPCSO1")["stale"], 0)
        # 规则只作用于活跃点：stale 点不生成语义（但快照和已有语义都保留）
        self.store.apply_rules(server_id="demo")
        self.assertIsNone(
            self.store.get_semantics("simpleIOGenericIO/GGIO1.SPCSO3"))
        self.assertIsNotNone(
            self.store.get_semantics("simpleIOGenericIO/GGIO1.SPCSO1"))

    def test_rule_crud(self):
        rid = self.store.add_rule("MyDev", "ref", alias_tpl="我的设备",
                                  priority=200)
        self.assertIn(rid, [r["rule_id"] for r in
                            self.store.list_rules(enabled_only=True)])
        self.store.set_rule_enabled(rid, False)
        self.assertNotIn(
            rid, [r["rule_id"] for r in self.store.list_rules(True)])
        # 内置规则不可删除
        built_in = [r for r in self.store.list_rules() if r["built_in"]]
        self.assertTrue(len(built_in) >= 10)
        with self.assertRaises(ValueError):
            self.store.delete_rule(built_in[0]["rule_id"])
        # 自定义规则可删除
        self.store.delete_rule(rid)
        self.assertNotIn(rid, [r["rule_id"] for r in self.store.list_rules()])

    def test_lookup_and_stats(self):
        self.store.scan_model(FakeClient(), server_id="demo")
        self.store.apply_rules(server_id="demo")
        out = self.store.lookup("simpleIOGenericIO/GGIO1.AnIn1")
        self.assertEqual(out["alias"], "模拟量输入")
        self.assertEqual(out["node"]["do_type"], "MV")
        self.assertEqual(out["category"], "遥测")
        n, s, r = self.store.stats()
        self.assertEqual((n, s), (9, 9))
        self.assertGreaterEqual(r, 10)
        self.store.delete_semantics("simpleIOGenericIO/GGIO1.AnIn1")
        self.assertIsNone(
            self.store.get_semantics("simpleIOGenericIO/GGIO1.AnIn1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
