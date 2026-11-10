"""pick_restore_target 回归测试（v0.1.230）

背景：自测收尾要「把当前项目切回用户原项目」，这条逻辑踩过两次事故，
第二次（v0.1.230）是**它自己把用户资料挪走**：
用户真实项目叫「实测_20261103_132055」、挂着 228 台设备，只因名字以
「实测」开头被判成测试残留，被换成 0 文件 0 设备的空壳「v01201实测_012805」。

本测试锁死判据：**按内容判，不按名字判**。四种场景逐一覆盖，
并带一条反向验证 —— 旧判据（只看名字）必须在这份数据上判错。
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_passed = 0
_failed = 0


def check(name, ok, detail=""):
    global _passed, _failed
    if ok:
        _passed += 1
        print(f"  [PASS] {name}" + (f": {detail}" if detail else ""))
    else:
        _failed += 1
        print(f"  [FAIL] {name}" + (f": {detail}" if detail else ""))


def load():
    spec = importlib.util.spec_from_file_location(
        "stmod_restore", os.path.join(HERE, "selftest.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules["stmod_restore"] = m
    spec.loader.exec_module(m)
    return m


def main():
    m = load()
    pick = m.pick_restore_target

    # 沙箱实测的真实数据快照（2026-11-10）
    REAL = {"id": "322fef90", "name": "实测_20261103_132055",
            "file_count": 1, "device_count": 228,
            "updated_at": "2026-11-10 01:18:23"}
    SHELL_A = {"id": "f878fb48", "name": "v01201实测_012805",
               "file_count": 0, "device_count": 0,
               "updated_at": "2026-11-09 07:04:43"}
    SHELL_B = {"id": "260bc607", "name": "v01201实测项目",
               "file_count": 0, "device_count": 0,
               "updated_at": "2026-11-09 07:04:31"}
    NORMAL = {"id": "aaa11111", "name": "马诺诺",
              "file_count": 62, "device_count": 0,
              "updated_at": "2026-11-10 02:00:00"}

    print("=== 场景1：名字像测试但有内容 → 必须保留（本次事故的正面用例）===")
    items = [REAL, SHELL_A, SHELL_B]
    t, msg = pick(items, REAL["id"])
    check("保留有内容的真实项目", t == REAL["id"], f"target={t} msg={msg[:60]}")
    check("并打印「认定为真实项目」", "认定为真实项目" in msg, msg[:80])

    print("=== 场景2：名字像测试且无内容 → 换到有内容的项目 ===")
    t, msg = pick(items, SHELL_A["id"])
    check("切到有内容的项目", t == REAL["id"], f"target={t}")
    check("不按 updated_at 挑空壳", t != SHELL_B["id"], f"target={t}")

    print("=== 场景3：名字正常 → 原样保留 ===")
    t, msg = pick([NORMAL, REAL, SHELL_A], NORMAL["id"])
    check("名字正常的项目保留", t == NORMAL["id"], f"target={t}")
    check("不打印多余说明", msg == "", f"msg={msg[:40]}")

    print("=== 场景4：全是空壳、无内容项目可切 → 保持不动（不能切到另一个空壳）===")
    t, msg = pick([SHELL_A, SHELL_B], SHELL_A["id"])
    check("没有有内容项目时保持不动", t == SHELL_A["id"], f"target={t}")
    check("明确说明没有可切目标", "没有别的有内容项目可切" in msg, msg[:80])

    print("=== 场景5（反向验证）：旧判据「只看名字」必须在这份数据上判错 ===")
    # 旧逻辑：名字以 自测/实测 开头 → 直接换成「不以这些前缀开头」的最新项目
    def old_pick(items, origin_pid):
        cur = next((p for p in items if p.get("id") == origin_pid), {})
        nm = str(cur.get("name") or "")
        if nm.startswith("自测") or nm.startswith("实测"):
            real = [p for p in items
                    if not str(p.get("name") or "").startswith(("自测", "实测"))]
            real.sort(key=lambda p: str(p.get("updated_at") or ""), reverse=True)
            if real:
                return real[0].get("id")
        return origin_pid

    old_t = old_pick(items, REAL["id"])
    check("旧判据会把 228 台设备的项目误判为残留（证明本条测试抓得住缺陷）",
          old_t != REAL["id"], f"旧判据 target={old_t}（应为 {REAL['id']}）")

    print(f"\n===== 通过 {_passed} / 失败 {_failed} =====")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
