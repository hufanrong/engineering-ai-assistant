"""上传队列口径回归测试（v0.1.208）

验证目标：队列里「1 个真包 + 内部索引 _sha_index.json」时，
所有对外读取点必须都只认那 1 个真包，不能把索引算进去。

针对实测缺陷：
  · 项目 322fef90 队列目录实际 = 1 个真包 + _sha_index.json
  · pending_count() 返回 2（多算索引），list_pending() 返回 1 条 —— 同一队列两个答案
  · /api/status 的 queue_pending 就是这个 pending_count，WORKbuddy 报告里
    queue_pending: 3 同样是「2 个真包 + 索引」被算成 3
  · upload_all 会把 _sha_index.json 当包读 payload['payload'] -> KeyError，
    记进「上传失败」，用户看到「1 成功 1 失败」，而失败那条根本不存在
  · clear_all 会把索引一起删掉

断言分组：
  [A] 计数口径：pending_count == list_pending 条数 == 真包数
  [B] 索引文件本身仍在（不能被当成包删掉或上传掉）
  [C] clear_all 只删真包、保留索引
  [D] remove_packages 传入索引名也不会删索引
  [E] 索引在时上传挑选集里不出现它（不产生假的 KeyError 失败）

运行：python3 tools/test_upload_queue.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.upload_queue as uq  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def _make_pkg(dirname, fname):
    """造一个最小可用的待上传包。"""
    payload = {
        "created_at": "2026-11-07 01:00:00",
        "payload": {
            "file_name": fname,
            "sha256": fname.encode().hex()[:32],
            "status": "parsed",
        },
    }
    p = os.path.join(dirname, fname + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return os.path.basename(p)


def main():
    global PASS, FAIL
    PASS = FAIL = 0
    uq._ensure()
    qdir = uq.QUEUE_DIR
    print(f"队列目录: {qdir}")

    # 备份现场，测完恢复，绝不破坏真实队列
    backup = {}
    for f in os.listdir(qdir):
        p = os.path.join(qdir, f)
        with open(p, encoding="utf-8") as fh:
            backup[f] = fh.read()

    # 清成已知状态：1 个真包 + 索引
    for f in os.listdir(qdir):
        os.remove(os.path.join(qdir, f))
    pk1 = _make_pkg(qdir, "真包A.xlsx")
    uq._rebuild_idx()  # 走模块自己的索引生成路径，写出 _sha_index.json
    idx_exists = os.path.isfile(os.path.join(qdir, uq._IDX_FILE))
    print(f"准备: 真包 1 个 + 索引存在={idx_exists}, 目录={sorted(os.listdir(qdir))}")
    print()

    print("[A] 计数口径一致")
    n_pending = uq.pending_count()
    n_list = len(uq.list_pending())
    check("pending_count 不含索引", n_pending == 1, f"实际 {n_pending}，期望 1")
    check("list_pending 条数一致", n_list == n_pending, f"pending={n_pending} list={n_list}")
    check("_queue_files 只列真包", uq._queue_files() == [pk1], f"实际 {uq._queue_files()}")

    print()
    print("[B] 索引文件不被当作包")
    check("索引仍在磁盘上", os.path.isfile(os.path.join(qdir, uq._IDX_FILE)))
    try:
        with open(os.path.join(qdir, uq._IDX_FILE), encoding="utf-8") as fh:
            idx = json.load(fh)
        check("索引内容可读（未损坏）", isinstance(idx, dict), f"实际 {type(idx)}")
    except Exception as e:  # noqa: BLE001
        check("索引内容可读（未损坏）", False, str(e))

    print()
    print("[E] 上传挑选集不含索引")
    picked = uq._queue_files()
    check("挑选集里没有 _sha_index", uq._IDX_FILE not in picked, f"实际 {picked}")
    ok_read = True
    for f in picked:
        try:
            with open(os.path.join(qdir, f), encoding="utf-8") as fh:
                json.load(fh)["payload"]["file_name"]
        except Exception:  # noqa: BLE001
            ok_read = False
    check("挑选集全部能读到 payload.file_name", ok_read,
          "有包读不到 file_name（会变成假失败）")

    print()
    print("[D] remove_packages 不误删索引")
    r = uq.remove_packages([uq._IDX_FILE])
    check("按索引名移除被拒", r["removed"] == 0, f"实际 {r}")
    check("索引仍存在", os.path.isfile(os.path.join(qdir, uq._IDX_FILE)))

    print()
    print("[C] clear_all 只删真包、保留索引")
    c = uq.clear_all()
    check("删除数=真包数", c["deleted"] == 1, f"实际 {c}")
    check("索引未被清掉", os.path.isfile(os.path.join(qdir, uq._IDX_FILE)))
    check("队列已空", uq.pending_count() == 0, f"实际 {uq.pending_count()}")

    # 恢复现场
    for f in os.listdir(qdir):
        os.remove(os.path.join(qdir, f))
    for f, content in backup.items():
        with open(os.path.join(qdir, f), "w", encoding="utf-8") as fh:
            fh.write(content)
    print()
    print(f"现场已恢复: {sorted(os.listdir(qdir))}")

    print()
    print("=" * 60)
    print(f"结果：通过 {PASS} / 失败 {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
