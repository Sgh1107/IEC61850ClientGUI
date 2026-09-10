# -*- coding: utf-8 -*-
"""
core/scd_import.py 的自验证测试（使用内置最小样例 SCD 不需要真实工程文件）
运行：python tests/test_scd_import.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core.model_store import ModelStore
from core.scd_import import import_scd, parse_scd

# SCD 测试文件全文
SAMPLE_SCD = """<?xml version="1.0" encoding="UTF-8"?>
<SCL xmlns="http://www.iec.ch/61850/2003/SCL" version="2007" revision="B">
  <IED name="IED1" desc="测试装置">
    <AccessPoint name="P1">
      <Server>
        <LDevice inst="simpleIOGenericIO">
          <LN0 lnClass="LLN0" inst="" desc="装置公共逻辑节点">
            <DOI name="Beh" desc="运行行为状态"/>
            <DOI name="NamPlt"/>
          </LN0>
          <LN prefix="" lnClass="GGIO" inst="1" desc="车间1号通用IO">
            <DOI name="SPCSO3" desc="1号开关遥控"/>
            <DOI name="SPCSO2"/>
          </LN>
        </LDevice>
        <LDevice inst="measLD">
          <LN prefix="Q01SB1" lnClass="MMXU" inst="2">
            <DOI name="A" desc="A相电流测量"/>
          </LN>
        </LDevice>
      </Server>
    </AccessPoint>
  </IED>
  <IED name="IED2">
    <AccessPoint name="P1">
      <Server>
        <LDevice inst="ld2">
          <LN prefix="" lnClass="GGIO" inst="1">
            <DOI name="SPCSO1" desc="IED2遥控点"/>
          </LN>
        </LDevice>
      </Server>
    </AccessPoint>
  </IED>
</SCL>
"""


class TestScdImport(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(path)
        self.db = path
        self.store = ModelStore(path)
        fd2, scd = tempfile.mkstemp(suffix=".scd")
        with os.fdopen(fd2, "w", encoding="utf-8") as f:
            f.write(SAMPLE_SCD)
        self.scd = scd

    def tearDown(self):
        for p in (self.db, self.scd):
            if os.path.exists(p):
                os.remove(p)

    def test_parse_refs(self):
        entries = parse_scd(self.scd)
        refs = dict(entries)
        # ref 格式与模型快照一致
        self.assertIn("simpleIOGenericIO/LLN0.Beh", refs)
        self.assertIn("simpleIOGenericIO/GGIO1.SPCSO3", refs)
        self.assertIn("measLD/Q01SB1MMXU2.A", refs)
        self.assertEqual(refs["simpleIOGenericIO/GGIO1.SPCSO3"], "1号开关遥控")
        # DOI 无 desc 时用所属 LN 的 desc 兜底
        self.assertEqual(refs["simpleIOGenericIO/GGIO1.SPCSO2"], "车间1号通用IO")
        # LN0 desc 作为兜底
        self.assertEqual(refs["simpleIOGenericIO/LLN0.Beh"], "运行行为状态")

    def test_parse_filter_ied(self):
        entries = parse_scd(self.scd, ied_name="IED1")
        self.assertTrue(all("IED2" not in e[1] for e in entries))
        self.assertNotIn("ld2/GGIO1.SPCSO1", dict(entries))

    def test_import(self):
        imported, skipped = import_scd(self.store, self.scd, server_id="proj1")
        self.assertEqual((imported, skipped), (6, 0))
        sema = self.store.get_semantics("simpleIOGenericIO/GGIO1.SPCSO3")
        self.assertEqual(sema["origin"], "imported")
        self.assertEqual(sema["description"], "1号开关遥控")
        self.assertEqual(sema["alias"], "1号开关遥控")  # 短描述同时作别名
        # NamPlt 无自身 desc，用 LN0 的 desc 兜底
        nplt = self.store.get_semantics("simpleIOGenericIO/LLN0.NamPlt")
        self.assertEqual(nplt["description"], "装置公共逻辑节点")
        # 短描述同时作别名（"A相电流测量"仅6字）
        self.assertEqual(self.store.get_semantics("measLD/Q01SB1MMXU2.A")["alias"], "A相电流测量")

        # 重复导入默认跳过
        imported2, skipped2 = import_scd(self.store, self.scd, server_id="proj1")
        self.assertEqual((imported2, skipped2), (0, 6))
        # --overwrite 后重新导入
        imported3, _ = import_scd(self.store, self.scd, server_id="proj1", overwrite=True)
        self.assertEqual(imported3, 6)

    def test_manual_protected(self):
        ref = "simpleIOGenericIO/GGIO1.SPCSO3"
        self.store.set_semantics(ref, server_id="proj1", alias="手填别名", description="手填描述")
        imported, skipped = import_scd(self.store, self.scd, server_id="proj1", overwrite=True)
        sema = self.store.get_semantics(ref)
        self.assertEqual(sema["alias"], "手填别名")
        self.assertEqual(sema["origin"], "manual")
        self.assertEqual(skipped, 1)  # 该条被跳过


if __name__ == "__main__":
    unittest.main(verbosity=2)
