"""智能生成落盘回归测试（v0.1.201）

本测试针对实测发现的缺陷链（不只是单个 bug）：

  【症状】前端「资料生成」模块 11 个可选文件类型，实测：
    · 8 个返回 {"ok":true,"success":1,"failed":0} 但 generated_docs 里
      docx 数量 14 → 14，一个都没多；
    · 另 3 个（吊装方案 / 设备验收记录 / 焊接方案）报 failed；
    · /api/smart-doc/history 恒返回 {"ok":true,"history":[]}（实际有 14 份）；
    · /api/smart-doc/download/<真实文件名> 恒返回「文件不存在」。

  【根因 1】_call_generator 调的都是 mining_* 内容编排模块，只返回
    sections/plan 这类 JSON，从不写 docx；else 分支直接返回占位 JSON。
    调用方只看 r["ok"]，把「生成了 JSON」记成「生成了文件」。

  【根因 2】history / download 读全局 data/generated_docs 的**平铺**目录，
    而 v0.1.168 起文件落在 <项目>/generated_docs/<类型>/，位置和结构都变了。

  【根因 3】_save_generated 文件名只精确到秒，同一秒内连续生成同名覆盖。
    实测连续 3 次只落 2 个文件 —— 批量 30 台设备会静默丢一半。

断言分组：
  [A] 每种支持类型都真的产出 docx 文件，且落在项目 generated_docs 下
  [B] 产出的每一份都是合法 docx（可被 python-docx 打开，含 document.xml）
  [C] 返回体必须带 output_path；没有文件就不许报 ok=True
  [D] _save_generated 同秒连续调用不覆盖（文件名唯一）
  [E] 全部产出都在「生成历史」里可见，并且能按 id 下载
  [F] 写入的是当前项目目录，不是全局 data/（与 v0.1.200 的隔离口径一致）

运行：python3 tools/test_smart_doc_persist.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.config as config  # noqa: E402
import app.project_manager as pm  # noqa: E402
import app.archive as archive  # noqa: E402
import app.docgen as docgen  # noqa: E402
import app.smart_doc_generator as sdg  # noqa: E402

passed = 0
failed = 0
fail_detail = []


def check(cond, label, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        fail_detail.append(f"{label}｜{detail}")
        print(f"  [FAIL] {label}" + (f"｜{detail}" if detail else ""))


def is_docx(path):
    """真 docx 判定：能被 zipfile 打开且含 word/document.xml。"""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
        return any(n == "word/document.xml" for n in names)
    except Exception:
        return False


# 前端下拉里实际提供的 11 个类型（web/index.html 的 docgenType / batchGenType）
FE_TYPES = [
    "施工日志", "施工方案", "吊装方案", "安全技术交底", "技术交底",
    "设备验收记录", "开箱检验记录", "隐蔽工程验收记录", "焊接方案",
    "设计变更", "货损报告",
]


def main():
    originals = {
        "DATA_DIR": config.DATA_DIR,
        "PROJECTS_ROOT": pm.PROJECTS_ROOT,
        "CURRENT_PROJECT_FILE": pm.CURRENT_PROJECT_FILE,
    }
    tmp = tempfile.mkdtemp(prefix="fg_smartdoc_")
    try:
        config.DATA_DIR = os.path.join(tmp, "data")
        os.makedirs(config.DATA_DIR, exist_ok=True)
        pm.PROJECTS_ROOT = os.path.join(config.DATA_DIR, "projects")
        pm.CURRENT_PROJECT_FILE = os.path.join(config.DATA_DIR, "current_project.json")
        os.makedirs(pm.PROJECTS_ROOT, exist_ok=True)

        proj = pm.create_project("落盘测试项目")
        pid = proj["project"]["id"]
        pm.set_current_project(pid)
        pdir = pm.get_project_data_dir(pid)
        print(f"临时项目: {pid} -> {pdir}")

        # ---------- [A] 每种类型都真的产出文件 ----------
        print("\n[A] 每种支持类型都真的产出 docx")
        results = {}
        for t in FE_TYPES:
            r = sdg.generate_from_natural_language(f"生成{t}：球磨机", project_id=pid)
            results[t] = r
            po = r.get("output_path")
            ok_file = bool(po) and os.path.isfile(po) and os.path.getsize(po) > 0
            check(r.get("ok") is True and ok_file,
                  f"{t} 产出文件", f"ok={r.get('ok')} path={po} err={r.get('error')}")

        # ---------- [B] 每份都是合法 docx ----------
        print("\n[B] 产出的每一份都是合法 docx")
        for t, r in results.items():
            po = r.get("output_path")
            check(bool(po) and os.path.exists(po) and is_docx(po),
                  f"{t} 是合法 docx", f"path={po}")

        # ---------- [C] ok=True 必须有文件 ----------
        print("\n[C] 没有文件就不许报成功")
        ok_with_file = [t for t, r in results.items() if r.get("ok")]
        check(len(ok_with_file) == len(FE_TYPES),
              "全部 11 个类型都成功", f"成功={len(ok_with_file)}/{len(FE_TYPES)}")
        for t, r in results.items():
            if r.get("ok"):
                check(bool(r.get("output_path")),
                      f"{t} 成功时必须带 output_path", f"path={r.get('output_path')}")

        # ---------- [D] 同秒连续生成不覆盖 ----------
        print("\n[D] 同一秒内连续生成不覆盖")
        content, _missing = docgen.fill_template("施工方案", {
            "项目名称": "T", "车间": "X", "编制单位": "",
            "编制人": "", "施工内容": "", "施工日期": ""})
        paths = [archive._save_generated("施工方案", content) for _ in range(5)]
        check(len(set(paths)) == 5, "连续 5 次落盘得到 5 个不同文件名",
              f"实际不同={len(set(paths))}")
        check(all(os.path.exists(p) for p in paths), "5 份文件全部存在",
              f"存在={sum(os.path.exists(p) for p in paths)}")

        # ---------- [E] 历史可见 + 可下载 ----------
        print("\n[E] 生成历史可见、可按 id 下载")
        gen = archive._list_generated()
        total = sum(len(v) for v in gen.values())
        # 前端下拉名 -> 内部类型 -> 归档目录名
        internal = {}
        for t in FE_TYPES:
            dt, _c = sdg._extract_doc_type(f"生成{t}：球磨机")
            internal[t] = dt or t
        expected = {sdg._archive_type_of(internal[t]) for t in FE_TYPES}
        listed = [t for t in expected if t in gen]
        check(total >= len(FE_TYPES), "生成历史能看到本轮产出的文件",
              f"archive 里共 {total} 份")
        check(len(listed) == len(expected), "11 个类型都在生成目录里有归档",
              f"缺: {sorted(expected - set(listed))}")

        # 归档目录名必须与接口返回给前端的 doc_type 一致，
        # 否则「历史里的类型」和「下载时的路径」是两套名字
        for t, r in results.items():
            arch = sdg._archive_type_of(internal[t])
            po = r.get("output_path") or ""
            check(os.path.basename(os.path.dirname(po)) == arch,
                  f"{t} 归档目录名与映射一致", f"实际={os.path.basename(os.path.dirname(po)) or '-'} 期望={arch}")

        # 用 history 接口同一套实现（archive._list_generated）核对 id 形状
        sample_type = "施工方案"
        sample = os.path.basename(gen[sample_type][0])
        doc_id = f"{sample_type}/{sample}"
        found = os.path.join(archive._gen_dir(), sample_type, sample)
        check(os.path.isfile(found), "按「类型/文件名」能定位到文件", f"id={doc_id}")

        # ---------- [F] 写入项目目录，不写全局 data ----------
        print("\n[F] 写入当前项目目录，全局 data/ 不新增业务文件")
        for t, r in results.items():
            po = r.get("output_path") or ""
            check(pdir in po, f"{t} 落在当前项目目录", f"path={po}")
        global_gen = os.path.join(config.DATA_DIR, "generated_docs")
        check(not os.path.exists(global_gen),
              "全局 data/generated_docs 未被创建", f"exists={os.path.exists(global_gen)}")

        # ---------- [G] 再生成：归档名必须能反查回内部类型并真的产出 ----------
        # 这条是外部接口实测打出来的缺陷：生成历史里点「重新生成」一直失败。
        # 两个叠加原因：① 目录名是归档名，生成器只认内部类型；
        #             ② 原实现复用自然语言解析，认不出设备名就停在 need_equipment。
        print("\n[G] 再生成：归档名反查内部类型且真落盘")
        gen2 = archive._list_generated() or {}
        print_types = [t for t in sorted(gen2.keys())]
        for at in print_types:
            it = sdg._internal_type_of(at)
            check(it and it != at or it in sdg.DOC_TYPE_MAP,
                  f"归档名「{at}」能反查回内部类型", f"-> {it}")
        # 逐个归档名真的跑一次再生成，必须产出新文件
        for at in print_types[:4]:
            it = sdg._internal_type_of(at)
            r = sdg.regenerate_by_type(it, project_id=proj["project"]["id"])
            okp = bool(r.get("ok")) and bool(r.get("output_path"))
            check(okp, f"再生成「{at}」真产出文件",
                  f"ok={r.get('ok')} file={r.get('output_file')} err={r.get('error')}")
            if okp:
                check(is_docx(r["output_path"]),
                      f"再生成「{at}」是合法 docx", f"path={r['output_path']}")

        # ---------- [H] 真实台账口径：设备名原样识别、不许改写 ----------
        # v0.1.202：原实现只在 8 个硬编码设备名里做子串匹配，
        # 实测真实台账 215 台有名称的设备只认出 14 台（6.5%），
        # 且把「圆锥破碎机」印成「颚式破碎机」这类改写。
        print("\n[H] 真实台账口径的设备识别")
        # 用一台真实台账里有的、但**不在**内置 8 类名单里的设备
        REAL_DEVICES = ["Y0#胶带输送机", "金属探测器", "重型板式给料机",
                        "液下渣浆泵", "电动单梁起重机", "静压润滑油站"]
        # 先把它们灌进台账（模拟真实项目）
        idx_path = os.path.join(pdir, "index.json")
        _idx = {}
        if os.path.isfile(idx_path):
            with open(idx_path, encoding="utf-8") as f:
                _idx = json.load(f)
        _devs = _idx.get("devices") or {}
        for _i, _nm in enumerate(REAL_DEVICES):
            _devs[f"_no_tag_{_nm}|测试车间|||"] = {
                "name": _nm, "workshop": "测试车间", "model": "", "manufacturer": "",
                "unit": "台"}
        _idx["devices"] = _devs
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump(_idx, f, ensure_ascii=False)

        for _nm in REAL_DEVICES:
            eq, _sc = sdg._extract_equipment(f"生成设备验收记录：{_nm}", project_id=pid)
            check(eq == _nm, f"台账设备「{_nm}」原样识别", f"got={eq!r}")

        # 不许改写：这几种都是被原实现印错的
        _must_not_rewrite = [
            ("生成设备验收记录：圆锥破碎机", "颚式破碎机"),
            ("生成设备验收记录：真空带式过滤机", "压滤机"),
            ("生成设备验收记录：高压辊磨机变频器", "球磨机"),
        ]
        for _txt, _bad in _must_not_rewrite:
            eq, _sc = sdg._extract_equipment(_txt, project_id=pid)
            check(eq != _bad, f"「{_txt.split('：')[1]}」不被改写成「{_bad}」", f"got={eq!r}")

        # 用户自己写的设备名（不在任何名单里）也要能出表，不许卡在 need_equipment
        _custom = "ZM-9000试验台"
        _r = sdg.generate_from_natural_language(f"生成设备验收记录：{_custom}", project_id=pid)
        check(_r.get("ok") is True and bool(_r.get("output_path")),
              "名单外设备名也能出表", f"stage={_r.get('stage')} err={_r.get('error')}")
        check(_r.get("equipment") == _custom,
              "名单外设备名原样落到 equipment", f"got={_r.get('equipment')!r}")

        # ---------- [I] 按设备出表：每份带自己的设备、内容不串台 ----------
        # v0.1.202：原来 _persist_docx 从不把 equipment 传给表单渲染器，
        # 实测 3 台设备出 3 份表，「设备名称/设备位号」两列全空且内容一致。
        print("\n[I] 按设备批量出表不串台")
        import hashlib as _hashlib
        import docx as _docx
        _batch = ["Y0#胶带输送机", "液下渣浆泵", "电动单梁起重机"]
        _hashes = {}
        for _nm in _batch:
            _r = sdg.generate_from_natural_language(
                f"生成设备验收记录：{_nm}", project_id=pid)
            _po = _r.get("output_path")
            okp = bool(_r.get("ok")) and bool(_po) and os.path.isfile(_po)
            check(okp, f"批量出表「{_nm}」产出文件", f"err={_r.get('error')}")
            if not okp:
                continue
            _d = _docx.Document(_po)
            _cells = "".join(c.text for t in _d.tables for row in t.rows for c in row.cells)
            check(_nm in _cells, f"「{_nm}」的表里印着自己的设备名")
            _hashes[_nm] = _hashlib.sha256(open(_po, "rb").read()).hexdigest()
            # 设备名称那一行必须真的有值，不能是空的
            _row_name = [c.text.strip() for c in _d.tables[0].rows[2].cells]
            check(len(_row_name) > 1 and _row_name[1] == _nm,
                  f"「{_nm}」设备名称行已填", f"row={_row_name[:2]}")

        check(len(set(_hashes.values())) == len(_hashes),
              "批量出的表互不相同（不串台）", f"不同={len(set(_hashes.values()))}/{len(_hashes)}")

        # 设备关联必须真的登记进去（原来 dict 不可哈希被静默吞掉）
        from app import doc_relations as _dr
        # 直接测 register_doc 自身的输入契约：传 dict 不许抛异常，
        # 否则调用方的 try/except 会把它静默吞掉（=一条都不登记）。
        # 这条必须绕过 _save_generated 的归一化来测，否则测不出缺陷。
        try:
            _rec = _dr.register_doc("测试/dict输入.docx", "测试", file_path="",
                                    devices=[{"tag": "球磨机"}, {"name": "破碎机"}],
                                    workshops=[{"name": "磨浮车间"}], source="generated")
            check(_rec.get("devices") == ["球磨机", "破碎机"]
                  or set(_rec.get("devices") or []) == {"球磨机", "破碎机"},
                  "register_doc 接受 dict 并按位号登记", f"devices={_rec.get('devices')}")
            check(_rec.get("workshops") == ["磨浮车间"],
                  "register_doc 接受 dict 车间", f"workshops={_rec.get('workshops')}")
        except Exception as _e:  # noqa: BLE001
            check(False, "register_doc 接受 dict 不抛异常",
                  f"{type(_e).__name__}: {_e}")

        _st = _dr.stats()
        check(_st.get("with_devices", 0) >= len(_batch),
              "生成文件登记了设备关联", f"with_devices={_st.get('with_devices')}")
        for _nm in _batch:
            check(_nm in (_st.get("device_docs") or {}),
                  f"关联里能按「{_nm}」查到资料",
                  f"device_docs={list((_st.get('device_docs') or {}))[:5]}")

        # ---------- [J] 再生成保留原设备名 ----------
        # v0.1.202：regenerate_by_type 的 equipment 缺省为空，
        # 实测再生成出来的表设备名称列是空的。
        print("\n[J] 再生成保留原设备名")
        _gen = archive._list_generated() or {}
        _tgt_type = sdg._archive_type_of("设备验收")
        _tgt = None
        for _p in (_gen.get(_tgt_type) or []):
            _rel = _dr.get_all().get(f"{_tgt_type}/{os.path.basename(_p)}") or {}
            if _batch[0] in (_rel.get("devices") or []):
                _tgt = _p
                break
        check(_tgt is not None, "能找到一台设备对应的原文件", f"type={_tgt_type}")
        if _tgt:
            _did = f"{_tgt_type}/{os.path.basename(_tgt)}"
            _r = sdg.regenerate_by_type(sdg._internal_type_of(_tgt_type),
                                        project_id=pid, doc_id=_did)
            check(_r.get("ok") is True and bool(_r.get("output_path")),
                  "按原文件再生成产出文件", f"err={_r.get('error')}")
            if _r.get("output_path"):
                _dd = _docx.Document(_r["output_path"])
                _cells2 = "".join(c.text for t in _dd.tables
                                  for row in t.rows for c in row.cells)
                check(_batch[0] in _cells2,
                      "再生成的表仍印着原设备名", f"eq={_r.get('equipment')!r}")

    finally:
        config.DATA_DIR = originals["DATA_DIR"]
        pm.PROJECTS_ROOT = originals["PROJECTS_ROOT"]
        pm.CURRENT_PROJECT_FILE = originals["CURRENT_PROJECT_FILE"]
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n合计：{passed} PASS / {failed} FAIL")
    if fail_detail:
        print("失败明细：")
        for f in fail_detail:
            print("  -", f)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
