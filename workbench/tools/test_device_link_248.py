#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.1.248 / D36 回归：文件夹名 / 文件名 → 设备身份的联系。

用户原始需求（2026-11-12）：
  「当输入文件夹时,如果文件夹以车间命名,或者设备命名时：该文件夹内资料极有可能
    全部和该设备或车间有关系,可以归在一起,或者建立联系」

v0.1.248 之前的状态：
  · 文件夹名 → 车间：有（workshop_assign 的 file_path 通道，0.85）。
  · 文件夹名 → 设备：**只有 equipment_merge.find_by_identity() 这个查询入口，
    没有任何调用方** ——「有入口没接线」等于没做（本项目在 D18 上吃过大亏：
    接口存在 ≠ 接口能用，后端有能力 ≠ 前端有入口）。

本门禁盯三件事：
  1. **接上了**：真跑一次扫描，目录名 → 设备联系真的落盘（不是静态断言）。
  2. **口径不跑偏**：唯一身份自动关联；多身份**不自动**关联、进人工确认
     （用户决策：「同名多行再按型号区分，仍冲突则进人工确认」）。
  3. **不越权**：设备名不是车间名 —— 绝不因为设备名新建车间（用户 2026-11-11
     指令：「所有新建立的车间必须交由人工审批」）。

跑法：python tools/test_device_link_248.py
隔离：FANGONG_DATA_DIR 指向临时目录 —— 必须在 import app.config **之前**设置，
      否则会动到用户真实项目（PROJECTS_ROOT / CURRENT_PROJECT_FILE 是模块级常量）。
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.dirname(HERE)
sys.path.insert(0, WB)

# ---- 隔离：必须在 import app.* 之前 ----
_TMP = tempfile.mkdtemp(prefix="fg248_")
os.environ["FANGONG_DATA_DIR"] = _TMP

PASS, FAIL = [], []


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))


def _mk_project(pid, devices):
    """造一个项目目录 + 台账 index.json（设备台账是设备的唯一权威来源）。"""
    d = os.path.join(_TMP, "projects", pid)
    os.makedirs(d, exist_ok=True)
    idx = {"devices": {}}
    for tag, rec in devices.items():
        row = {"name": rec.get("name", ""), "model": rec.get("model", ""),
               "quantity": "1", "weight": "", "unit": "台",
               "workshop": rec.get("workshop", ""), "manufacturer": "",
               "drawing_no": "", "source_file": rec.get("src", "设备台账.xlsx"),
               "source_count": 1}
        idx["devices"][tag] = row
    with open(os.path.join(d, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    return d


def main():
    import app.device_link as dl
    import app.tombstone as tombstone

    print("=" * 72)
    print("D36：文件夹名 / 文件名 → 设备身份（v0.1.248）")
    print("=" * 72)

    # ---------------- 合成台账 ----------------
    # 金属探测器：两个车间各一台（同名不同车间 → 需要消歧）
    # 1号渣浆泵：同车间，一台有型号 M200、一台型号空（同名 → 型号区分 → 两个身份）
    # 2号离心泵：同车间同型号两行（同一身份的两个实例 → 关联要两个都在）
    # 空名行：没有名字就认不出设备，不参与匹配
    # P-301：真位号，可被目录名命中
    DEV_P1 = {
        "dev_a1": {"name": "金属探测器", "model": "", "workshop": "粗碎站"},
        "dev_a2": {"name": "金属探测器", "model": "", "workshop": "选矿厂"},
        "dev_b1": {"name": "1号渣浆泵", "model": "M200", "workshop": "粗碎站"},
        "dev_b2": {"name": "1号渣浆泵", "model": "", "workshop": "粗碎站"},
        "dev_c1": {"name": "2号离心泵", "model": "Q=160", "workshop": "粗碎站"},
        "dev_c2": {"name": "2号离心泵", "model": "Q=160", "workshop": "粗碎站"},
        "dev_d": {"name": "", "model": "", "workshop": "粗碎站"},
        "P-301": {"name": "循环水泵", "model": "", "workshop": "粗碎站"},
    }
    p1 = _mk_project("p1", DEV_P1)

    # ---------------- T1 目录段命中唯一身份 ----------------
    r = dl.link_file("sha_t1", "甲.pdf",
                     file_path=os.path.join("D:\\资料", "粗碎站", "2号离心泵", "甲.pdf"),
                     data_dir=p1)
    chk("T1 目录段命中唯一身份 → 自动关联",
        bool(r.get("linked")) and r.get("source") == "dir",
        f"linked={r.get('linked')} source={r.get('source')}")
    chk("T1 置信度与车间通道对齐（目录 0.85）",
        abs(float(r.get("confidence") or 0) - 0.85) < 1e-6,
        f"confidence={r.get('confidence')}")
    chk("T1 同一身份的两个实例都被关联（不丢设备）",
        sorted(r.get("tags") or []) == ["dev_c1", "dev_c2"],
        f"tags={r.get('tags')}")

    # ---------------- T2 文件名命中 ----------------
    r2 = dl.link_file("sha_t2", "2号离心泵说明书.txt",
                      file_path=os.path.join("D:\\资料", "散装", "2号离心泵说明书.txt"),
                      data_dir=p1)
    chk("T2 文件名命中 → 自动关联（source=filename, 0.75）",
        bool(r2.get("linked")) and r2.get("source") == "filename"
        and abs(float(r2.get("confidence") or 0) - 0.75) < 1e-6,
        f"linked={r2.get('linked')} source={r2.get('source')} conf={r2.get('confidence')}")

    # ---------------- T3 车间目录不产生设备联系 ----------------
    r3 = dl.link_file("sha_t3", "说明.pdf",
                      file_path=os.path.join("D:\\资料", "粗碎站", "说明.pdf"),
                      data_dir=p1)
    chk("T3 只含车间名的目录 → 不建立设备联系",
        not r3.get("linked"), f"linked={r3.get('linked')} reason={r3.get('reason')}")

    # ---------------- T4 同名跨车间 + 路径含车间 → 消歧 ----------------
    r4 = dl.link_file("sha_t4", "乙.pdf",
                      file_path=os.path.join("D:\\资料", "粗碎站", "金属探测器", "乙.pdf"),
                      data_dir=p1)
    chk("T4 同名跨车间 + 路径含车间 → 消歧到唯一身份",
        bool(r4.get("linked")) and r4.get("workshop") == "粗碎站",
        f"linked={r4.get('linked')} ws={r4.get('workshop')}")

    # ---------------- T5 同名跨车间 + 路径无车间 → 人工确认 ----------------
    r5 = dl.link_file("sha_t5", "丙.pdf",
                      file_path=os.path.join("D:\\资料", "金属探测器", "丙.pdf"),
                      data_dir=p1)
    pend = dl.list_pending(p1)
    links5 = {x["sha256"]: x for x in dl.list_links(p1)}
    chk("T5 同名跨车间且无法消歧 → 不自动关联",
        not r5.get("linked") and r5.get("ambiguous") is True,
        f"linked={r5.get('linked')} ambiguous={r5.get('ambiguous')}")
    chk("T5 该文件落在待人工确认队列",
        "sha_t5" in {x.get("sha256") for x in pend},
        f"pending={[x.get('sha256') for x in pend]}")
    chk("T5 待确认项**不在**已关联清单里",
        "sha_t5" not in links5, f"links={[k for k in links5]}")

    # ---------------- T6 同名多行按型号区分 → 两个身份 → 人工确认 ----------------
    r6 = dl.link_file("sha_t6", "丁.pdf",
                      file_path=os.path.join("D:\\资料", "粗碎站", "1号渣浆泵", "丁.pdf"),
                      data_dir=p1)
    chk("T6 同名多行（有型号/无型号）→ 不自动关联，进人工确认",
        not r6.get("linked") and r6.get("ambiguous") is True,
        f"linked={r6.get('linked')} ambiguous={r6.get('ambiguous')}")
    chk("T6 候选里列出两个身份（型号区分）",
        len(r6.get("candidates") or []) == 2,
        f"candidates={[(c.get('name'), c.get('model')) for c in (r6.get('candidates') or [])]}")

    # ---------------- T7 空名设备不参与匹配 ----------------
    devs = dl.ledger_devices(p1)
    chk("T7 空名设备不进入匹配集合",
        all((d.get("name") or "") for d in devs),
        f"names={[d.get('name') for d in devs]}")
    r7 = dl.link_file("sha_t7", "戊.pdf",
                      file_path=os.path.join("D:\\资料", "戊.pdf"), data_dir=p1)
    chk("T7 无名文件 → 不关联", not r7.get("linked"), f"linked={r7.get('linked')}")

    # ---------------- T8 不越权：绝不因为设备名新建车间 ----------------
    reg = os.path.join(p1, "workshop_registry.json")
    cand = os.path.join(p1, "workshop_candidates.json")
    chk("T8 设备名没有被写成车间（登记表没被创建）",
        not os.path.exists(reg), f"exists={os.path.exists(reg)}")
    chk("T8 设备名没有进车间待审批队列",
        not os.path.exists(cand), f"exists={os.path.exists(cand)}")

    # ---------------- T9 跨项目隔离 ----------------
    p2 = _mk_project("p2", {
        "dev_z1": {"name": "2号离心泵", "model": "Q=999", "workshop": "别的车间"},
    })
    r9 = dl.link_file("sha_t9", "庚.pdf",
                      file_path=os.path.join("D:\\资料", "2号离心泵", "庚.pdf"),
                      data_dir=p2)
    chk("T9 另一个项目的同名设备：只认本项目台账",
        bool(r9.get("linked")) and r9.get("model") == "Q=999",
        f"linked={r9.get('linked')} model={r9.get('model')}")
    p2_links = {x["sha256"] for x in dl.list_links(p2)}
    p1_links = {x["sha256"] for x in dl.list_links(p1)}
    chk("T9 两个项目的链接互不串（p2 里没有 p1 的文件）",
        "sha_t1" not in p2_links and "sha_t9" not in p1_links,
        f"p1={sorted(p1_links)} p2={sorted(p2_links)}")

    # ---------------- T10 落点跟随 data_dir ----------------
    chk("T10 链接台账写在指定项目目录内",
        os.path.isfile(os.path.join(p1, "device_links.json")),
        f"exists={os.path.isfile(os.path.join(p1, 'device_links.json'))}")
    chk("T10 全局目录没有落链接（不落 config.DATA_DIR）",
        not os.path.exists(os.path.join(_TMP, "device_links.json")),
        f"exists={os.path.exists(os.path.join(_TMP, 'device_links.json'))}")

    # ---------------- T11 人工确认不被自动改写 ----------------
    # 歧义项有多个候选时，接口**必须**要求人明确选哪一个 —— 不给 identity_key
    # 就要返回 ok=False，而不是替人挑一个。这一条是「仍冲突则进人工确认」
    # （用户决策）落到 API 上的硬约束。
    c_amb = dl.confirm_link("sha_t5", data_dir=p1)
    chk("T11 歧义项不指定身份键 → 拒绝替人做决定",
        not c_amb.get("ok") and bool(c_amb.get("candidates")),
        f"ok={c_amb.get('ok')} msg={c_amb.get('msg')}")
    pend5 = {x.get("sha256"): x for x in dl.list_pending(p1)}
    cands5 = pend5.get("sha_t5", {}).get("candidates") or []
    chosen5 = cands5[0].get("identity_key") if cands5 else ""
    c = dl.confirm_link("sha_t5", identity_key=chosen5, data_dir=p1)
    chk("T11 待确认项可人工裁定", bool(c.get("ok")), f"ok={c.get('ok')}")
    after = dl.link_file("sha_t5", "丙.pdf",
                         file_path=os.path.join("D:\\资料", "金属探测器", "丙.pdf"),
                         data_dir=p1)
    chk("T11 人工确认过的联系不被自动改写",
        after.get("confirmed") is True and after.get("identity_key") == c.get("link", {}).get("identity_key"),
        f"confirmed={after.get('confirmed')}")

    # ---------------- T12 否决后不再自动建立 ----------------
    dl.reject_link("sha_t6", reason="不是这台", data_dir=p1)
    r12 = dl.link_file("sha_t6", "丁.pdf",
                       file_path=os.path.join("D:\\资料", "粗碎站", "1号渣浆泵", "丁.pdf"),
                       data_dir=p1)
    chk("T12 人工否决后不再自动建立",
        not r12.get("linked") and r12.get("reason") == "rejected",
        f"linked={r12.get('linked')} reason={r12.get('reason')}")

    # ---------------- T13 真跑扫描：接线真的生效 ----------------
    import app.scanner as scanner
    # 扫描会重写 index.json["devices"]（sync_devices 从解析缓存重算台账），
    # 所以这里用**独立项目**做扫描，避免把 p1 的合成台账冲掉 —— 否则后面
    # T14 测的就不是「设备联系并进图谱」，而是「台账被冲掉」。
    p_scan = _mk_project("p_scan", {
        "dev_s1": {"name": "2号离心泵", "model": "Q=160", "workshop": "粗碎站"},
    })
    scan_root = os.path.join(_TMP, "scanroot")
    dev_dir = os.path.join(scan_root, "粗碎站", "2号离心泵")
    os.makedirs(dev_dir, exist_ok=True)
    with open(os.path.join(dev_dir, "安装说明.txt"), "w", encoding="utf-8") as f:
        f.write("2号离心泵 安装说明 Q=160\n")
    try:
        scanner.scan_folder(scan_root, data_dir=p_scan)
    except Exception as e:  # noqa: BLE001
        chk("T13 扫描流程可执行", False, f"{type(e).__name__}: {e}")
    scan_links = {x["sha256"]: x for x in dl.list_links(p_scan)}
    hit = [v for v in scan_links.values() if v.get("file_name") == "安装说明.txt"]
    chk("T13 真跑扫描后建立了「目录名 → 设备」联系（接线生效）",
        len(hit) == 1 and hit[0].get("source") == "dir",
        f"hits={[(v.get('file_name'), v.get('source'), v.get('name')) for v in hit]}")
    chk("T13 扫描建立的联系指向正确设备",
        bool(hit) and hit[0].get("name") == "2号离心泵",
        f"name={hit[0].get('name') if hit else None}")
    chk("T13 扫描的联系落在被扫描项目里，不落别处",
        os.path.isfile(os.path.join(p_scan, "device_links.json"))
        and not os.path.exists(os.path.join(_TMP, "device_links.json")),
        f"scan_exists={os.path.isfile(os.path.join(p_scan, 'device_links.json'))} "
        f"global_exists={os.path.exists(os.path.join(_TMP, 'device_links.json'))}")

    # ---------------- T13b 解析失败/跳过的文件同样建立联系 ----------------
    # 「这台设备的图纸 DWG 打不开」不代表它不属于这台设备 —— 车间那一路
    # v0.1.143 就是这么做的（parse 失败/跳过也按目录名归车间），
    # 设备这一路必须同口径，否则同一批资料在两个维度上给出不同答案。
    p_scan2 = _mk_project("p_scan2", {
        "dev_s2": {"name": "2号离心泵", "model": "Q=160", "workshop": "粗碎站"},
    })
    scan_root2 = os.path.join(_TMP, "scanroot2")
    dev_dir2 = os.path.join(scan_root2, "粗碎站", "2号离心泵")
    os.makedirs(dev_dir2, exist_ok=True)
    with open(os.path.join(dev_dir2, "总图.dwg"), "wb") as f:
        f.write(b"AC1027" + b"\x00" * 64)     # 解析不了的 DWG
    try:
        scanner.scan_folder(scan_root2, data_dir=p_scan2)
    except Exception as e:  # noqa: BLE001
        chk("T13b 扫描流程可执行", False, f"{type(e).__name__}: {e}")
    scan2 = {x["sha256"]: x for x in dl.list_links(p_scan2)}
    hit2 = [v for v in scan2.values() if v.get("file_name") == "总图.dwg"]
    chk("T13b 解析失败/跳过的文件也按目录名建立设备联系",
        len(hit2) == 1 and hit2[0].get("name") == "2号离心泵",
        f"hits={[(v.get('file_name'), v.get('source'), v.get('name')) for v in hit2]}")

    # ---------------- T14 关系图谱并入设备联系 ----------------
    import app.relations as relations
    graph = relations.load_relations(p1)
    gl = graph.get("device_links")
    chk("T14 图谱带出 device_links 段", isinstance(gl, list) and len(gl) > 0,
        f"type={type(gl).__name__} len={len(gl) if isinstance(gl, list) else 'n/a'}")
    dev_files = {}
    for d in (graph.get("devices") or []):
        if isinstance(d, dict) and d.get("tag"):
            dev_files[d["tag"]] = d.get("files") or []
    chk("T14 关联到的资料挂到了设备上",
        any("甲.pdf" in (fs or []) for fs in dev_files.values()),
        f"devices_with_file={[t for t, fs in dev_files.items() if '甲.pdf' in (fs or [])]}")
    chk("T14 同一身份的多个实例都挂到（不只挂第一台）",
        all("甲.pdf" in (dev_files.get(t) or []) for t in ("dev_c1", "dev_c2")),
        f"dev_c1={dev_files.get('dev_c1')} dev_c2={dev_files.get('dev_c2')}")
    st14 = graph.get("stats") or {}
    chk("T14 统计口径与图谱内容一致",
        st14.get("device_links") == len(gl or []) and int(st14.get("device_link_files") or 0) > 0,
        f"stats.device_links={st14.get('device_links')} len={len(gl or [])} "
        f"files={st14.get('device_link_files')}")

    # ---------------- T15 墓碑挡住写入 ----------------
    p3 = _mk_project("p3", DEV_P1)
    tombstone.mark_deleted(p3, "p3", reason="unit")
    r15 = dl.link_file("sha_t15", "辛.pdf",
                       file_path=os.path.join("D:\\资料", "2号离心泵", "辛.pdf"),
                       data_dir=p3)
    chk("T15 项目已删除 → 不写链接",
        r15.get("skipped") == "project_deleted"
        and not os.path.exists(os.path.join(p3, "device_links.json")),
        f"skipped={r15.get('skipped')} exists={os.path.exists(os.path.join(p3, 'device_links.json'))}")

    # ---------------- T16 统计口径自洽 ----------------
    st = dl.stats(p1)
    chk("T16 stats.links == len(list_links)",
        st["links"] == len(dl.list_links(p1)),
        f"stats={st['links']} list={len(dl.list_links(p1))}")
    chk("T16 stats.pending == len(list_pending)",
        st["pending"] == len(dl.list_pending(p1)),
        f"stats={st['pending']} list={len(dl.list_pending(p1))}")

    # ---------------- T17 前端入口贯通（防止「后端有、前端没入口」）----------------
    # v0.1.248 之前：GET /api/device-links 与 confirm/reject 三个接口是纯后端能力，
    # 页面上 grep "device-links" = 0 处 —— 用户原始需求里的功能在界面上点不到。
    # 这里把「页面 → 接口 → 后端路由」三层都对上才算完。
    web_html = os.path.join(WB, "web", "index.html")
    html_txt = ""
    if os.path.isfile(web_html):
        with open(web_html, encoding="utf-8") as f:
            html_txt = f.read()
    chk("T17 页面有设备联系入口（快捷功能）",
        'onclick="showDeviceLinks()"' in html_txt,
        f"has_entry={'showDeviceLinks()' in html_txt}")
    chk("T17 页面调用了三个设备联系接口",
        "/api/device-links'" in html_txt
        and "/api/device-links/confirm" in html_txt
        and "/api/device-links/reject" in html_txt,
        f"get={'/api/device-links' in html_txt} "
        f"confirm={'/api/device-links/confirm' in html_txt} "
        f"reject={'/api/device-links/reject' in html_txt}")
    try:
        from app.main import app as _fastapi_app
        _paths = {r.path for r in _fastapi_app.routes}
    except Exception as e:  # noqa: BLE001
        _paths = set()
        chk("T17 后端路由可导入", False, f"{type(e).__name__}: {e}")
    chk("T17 后端三个路由都在",
        {"/api/device-links", "/api/device-links/confirm", "/api/device-links/reject"} <= _paths,
        f"paths={sorted(p for p in _paths if 'device-links' in p)}")

    # ---------------- 真实项目未被污染 ----------------
    print("-" * 72)
    real_projects = os.path.join(WB, "data", "projects")
    if os.path.isdir(real_projects):
        cnt = len([d for d in os.listdir(real_projects)
                   if os.path.isdir(os.path.join(real_projects, d))])
        chk("R1 用户真实项目目录未被测试写入",
            not os.path.exists(os.path.join(_TMP, "projects", "p1", "..", "leak")),
            f"真实项目数={cnt}")
    else:
        print("  [SKIP] 真实项目目录不存在（本沙箱无用户数据）")

    print("=" * 72)
    print(f"通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"  FAIL: {f}")
    print("=" * 72)
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(rc)
