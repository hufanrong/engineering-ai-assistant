# -*- coding: utf-8 -*-
"""v0.1.243 门禁：空间模型必须与 /api/relations 用同一份设备集合。

缺陷背景（全量自测 73 PASS / 2 FAIL 里的第二条）：
  GET /api/relations         -> devices 228（load 时合并台账）
  GET /api/spatial/structure -> stats.total_devices 0（build 时未合并）
自测断言「设备数跨接口一致」判红：relations=228 spatial=0。
根因是 graph["devices"] 在 build 阶段只来自已解析文档，而对外读数还要再加台账。

断言（全部在隔离目录跑，绝不碰真实项目）：
  S1 只有台账、没有解析缓存时，build 出来的 devices 仍等于台账条数
  S2 同上场景 spatial_model.json 的 total_devices 与 devices 条数相等（核心守卫）
  S3 layout 条数 == devices 条数，且每条都有 workshop
  S4 空间模型写进隔离目录，不落到当前项目/全局
  S5 台账里有、图纸没解析的设备，坐标状态必须是「台账记录（图纸未标注）」而不是假装有坐标
"""
import json, os, sys, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from app import relations as R
from app import spatial_model as SM

WS_A, WS_B = "破碎车间", "磨浮车间"
FAILS = []


def ck(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def make_ledger_project(ddir):
    """只造台账（index.json devices），一条解析缓存都不造 —— 模拟沙箱重建后的真实状态。"""
    devices = {
        "T-001": {"name": "1#胶带输送机", "model": "TD75-800", "quantity": "2", "unit": "台",
                  "weight": "5.2t", "workshop": WS_A, "manufacturer": "", "drawing_no": ""},
        "T-002": {"name": "颚式破碎机", "model": "PE-600×900", "quantity": "1", "unit": "台",
                  "weight": "12t", "workshop": WS_A, "manufacturer": "", "drawing_no": ""},
        "T-003": {"name": "浮选机", "model": "XCF-8", "quantity": "6", "unit": "台",
                  "weight": "", "workshop": WS_B, "manufacturer": "", "drawing_no": ""},
    }
    os.makedirs(ddir, exist_ok=True)
    with open(os.path.join(ddir, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"devices": devices, "files": {}}, f, ensure_ascii=False, indent=1)
    return devices


def main():
    ddir = tempfile.mkdtemp(prefix="fg243_")
    try:
        devices = make_ledger_project(ddir)
        g = R.build_relations(force=True, data_dir=ddir)

        # S1：只有台账时，build 出的 devices 必须等于台账条数
        ck("S1 build 后 devices 等于台账条数",
           len(g.get("devices") or []) == len(devices),
           f"台账={len(devices)} graph={len(g.get('devices') or [])}")

        # S2（核心守卫）：空间模型的设备数必须与同一份集合相等
        sp_path = os.path.join(ddir, "spatial_model.json")
        sp = json.load(open(sp_path, encoding="utf-8")) if os.path.exists(sp_path) else {}
        total = (sp.get("stats") or {}).get("total_devices")
        ck("S2 空间模型台数 == 图谱设备数",
           total == len(g.get("devices") or []) and total == len(devices),
           f"spatial.total={total} graph={len(g.get('devices') or [])} 台账={len(devices)}")

        # S3：layout 与 devices 同源同量
        lay = g.get("layout") or []
        ck("S3 layout 条数 == devices 条数且都有车间",
           len(lay) == len(g.get("devices") or []) and all(r.get("workshop") for r in lay),
           f"layout={len(lay)} devices={len(g.get('devices') or [])}")

        # S4：写进隔离目录，不落真实项目
        ck("S4 空间模型落在隔离目录", os.path.exists(sp_path), sp_path.replace(ddir, "<tmp>"))
        real = os.path.join(ROOT, "data", "projects", "322fef90", "spatial_model.json")
        real_mtime = os.stat(real).st_mtime if os.path.exists(real) else None
        before = json.load(open(real, encoding="utf-8")) if real_mtime else {}
        # 触发一次再比对，确认没被隔离运行写坏
        R.build_relations(force=True, data_dir=ddir)
        after = json.load(open(real, encoding="utf-8")) if os.path.exists(real) else {}
        ck("S4b 真实项目空间模型未被隔离运行改写",
           json.dumps(after, sort_keys=True) == json.dumps(before, sort_keys=True),
           f"real_devices={(after.get('stats') or {}).get('total_devices')}")

        # S5：台账设备不得假装有图纸坐标
        idx_all = sp.get("device_index") or {}
        tags = set(idx_all)
        ck("S5 台账设备全部进空间索引", tags == set(devices), f"索引={len(tags)} 台账={len(devices)}")
        bad = [t for t, d in idx_all.items() if d.get("coord_status") == "图纸标注"]
        ck("S5b 无图纸证据时不得标成「图纸标注」", not bad, f"误标={bad}")
        # 假守卫修正：all() 在空集合上恒真，必须同时要求索引非空
        okc = bool(idx_all) and all(d.get("coord_status") == "台账记录（图纸未标注）" for d in idx_all.values())
        ck("S5c 坐标状态为「台账记录（图纸未标注）」", okc,
           str({d.get("coord_status") for d in idx_all.values()}))

        # S6：车间数不被臆造
        wss = {d.get("workshop_group") or d.get("workshops") for d in idx_all.values()}
        ck("S6 车间只来自台账（2 个）",
           (sp.get("stats") or {}).get("workshops") == 2,
           f"workshops={(sp.get('stats') or {}).get('workshops')}")
    finally:
        shutil.rmtree(ddir, ignore_errors=True)

    print("=" * 50)
    print(f"通过 {len(FAILS) == 0 and 'ALL' or 0} / 失败 {len(FAILS)}" + (f"  {FAILS}" if FAILS else ""))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
