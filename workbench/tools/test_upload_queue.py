"""上传队列口径回归测试（v0.1.208 / v0.1.209）

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

v0.1.209 修的是这个测试自己：
  这一版原来直接在**真实项目**的 upload_queue/ 上做备份-清空-恢复。
  实测（2026-11-07 01:05~01:08）留下两处后果：
    1) 测试里的 clear_all / remove_packages 把 5 条 clear_queue 写进了
       真实项目 data/projects/322fef90/upload_log.jsonl —— 单元测试污染生产数据；
    2) 只要中途抛异常（断言失败不会，但 IO/JSON 异常会），恢复代码就执行不到，
       真实排队包被清空。WORKbuddy 本机队列里当时有 3 个包，跑一次测试就没了。
  改为全程在临时目录里跑：monkeypatch uq._get_data_dir 指向 tempdir，
  落点一律由 uq._queue_dir(uq._ensure()) 现算，都落在临时目录，真实数据零接触。

断言分组：
  [A] 计数口径：pending_count == list_pending 条数 == 真包数
  [B] 索引文件本身仍在（不能被当成包删掉或上传掉）
  [C] clear_all 只删真包、保留索引
  [D] remove_packages 传入索引名也不会删索引
  [E] 索引在时上传挑选集里不出现它（不产生假的 KeyError 失败）
  [F] 隔离性：测试不碰真实项目目录

运行：python3 tools/test_upload_queue.py
"""
import json
import os
import shutil
import sys
import tempfile

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

    # 先看一眼「真实」数据目录，只读不写，用于 [F] 隔离性断言
    real_dir = uq._get_data_dir()

    tmp = tempfile.mkdtemp(prefix="fg_uq_test_")
    tmp_q = os.path.join(tmp, "upload_queue")
    tmp_log = os.path.join(tmp, "upload_log.jsonl")
    os.makedirs(tmp_q, exist_ok=True)

    # 把模块的目录解析指向临时目录；落点一律现算（v0.1.245 起模块里没有
    # 可变的落点全局，隔离不再依赖「改全局再还原」）。
    uq._get_data_dir = lambda: tmp
    qdir = uq._queue_dir(uq._ensure())
    assert os.path.abspath(qdir) == os.path.abspath(tmp_q), \
        f"隔离失败：队列目录仍是 {qdir}"
    print(f"队列目录（临时）: {qdir}")

    try:
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

        print()
        print("[F] 隔离性：全程没碰真实项目目录")
        real_q = os.path.join(real_dir, "upload_queue")
        real_log = os.path.join(real_dir, "upload_log.jsonl")
        real_log_size = os.path.getsize(real_log) if os.path.isfile(real_log) else -1
        check("临时日志有写入（说明确实在跑）",
              os.path.isfile(tmp_log) and os.path.getsize(tmp_log) > 0,
              "临时 upload_log 未生成")
        check("真实 upload_log 大小未变", real_log_size == _REAL_LOG_SIZE,
              f"真实日志从 {_REAL_LOG_SIZE} 变成 {real_log_size}")
        check("真实队列目录条目数未变",
              _safe_count(real_q) == _REAL_Q_COUNT,
              f"真实队列从 {_REAL_Q_COUNT} 变成 {_safe_count(real_q)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 60)
    print(f"结果：通过 {PASS} / 失败 {FAIL}")
    return 0 if FAIL == 0 else 1


def _safe_count(d):
    try:
        return len(os.listdir(d))
    except Exception:  # noqa: BLE001
        return -1


# 进入 main 前先记录真实数据的基线快照（只读）
_REAL_DIR = uq._get_data_dir()
_REAL_LOG_SIZE = (os.path.getsize(os.path.join(_REAL_DIR, "upload_log.jsonl"))
                  if os.path.isfile(os.path.join(_REAL_DIR, "upload_log.jsonl")) else -1)
_REAL_Q_COUNT = _safe_count(os.path.join(_REAL_DIR, "upload_queue"))


if __name__ == "__main__":
    sys.exit(main())
