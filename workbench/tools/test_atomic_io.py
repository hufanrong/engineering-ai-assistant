#!/usr/bin/env python3
"""v0.1.198 回归：两个高频写盘点的「整份 JSON 读改写」必须原子、可并发。

v0.1.197 已修竣工清单（completion_archive.json），本文件守的是同一根因的
另外两处，都是用户数据会**整个消失**的写盘点：

  ① app/scanner.py::_save_index —— 资料库索引 index.json
     实测：2000 条 / 121831 B 的索引，写到第 4075 行附近中断，文件剩
     60915 B 半截 JSON；json.load 抛 JSONDecodeError，而 _load_index 的
     except 把它吞成 {} → 用户已入库的全部文件清单归零（原始文件还在，
     界面却是空的），重扫一遍要几小时。

  ② app/upload_queue.py::_save_idx —— 上传队列 sha256 去重索引
     实测反向验证：固定名字的 ".tmp" 在并发入队时互相踩踏，刷出
       [Errno 2] No such file or directory: .../_sha_index.json.tmp
     而 except 只 pass，连一行日志都没有 → 去重悄悄失效，同一文件
     反复入队、反复解析，队列无限膨胀。

用法：python3 tools/test_atomic_io.py   （退出码 0 = 全过）
"""
import io
import json
import os
import shutil
import sys
import tempfile
import threading

WB = os.environ.get("FANGONG_WB",
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, WB)
os.environ.setdefault("FANGONG_NO_BROWSER", "1")

from app import project_manager as pm      # noqa: E402
from app import scanner as sc              # noqa: E402
from app import upload_queue as uq         # noqa: E402

_PASS = [0]
_FAIL = []


def check(name, cond, detail=""):
    if cond:
        _PASS[0] += 1
        print(f"  [PASS] {name}")
    else:
        _FAIL.append(f"{name}  {detail}")
        print(f"  [FAIL] {name}  {detail}")


class _Boom(Exception):
    """模拟写到一半断电/进程被杀。"""


def _halfway_dump(obj, fp, **kw):
    """只写一半内容再抛异常——和真实现场一样留下半截 JSON。"""
    s = json.dumps(obj, ensure_ascii=False, indent=1)
    fp.write(s[:len(s) // 2])
    raise _Boom("模拟写盘中途断电")


def _mkproj(tmp, pid):
    """建一个临时项目并切为当前项目（scanner/upload_queue 都按当前项目取数据目录）。"""
    pm.PROJECTS_ROOT = os.path.join(tmp, "projects")
    pm.CURRENT_PROJECT_FILE = os.path.join(tmp, "current_project.json")
    d = os.path.join(pm.PROJECTS_ROOT, pid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "project_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"id": pid, "name": pid}, f, ensure_ascii=False)
    with open(pm.CURRENT_PROJECT_FILE, "w", encoding="utf-8") as f:
        json.dump({"project_id": pid}, f, ensure_ascii=False)
    uq.QUEUE_DIR = None
    uq.LOG_PATH = None
    return d


def _tmp_left(d):
    return [f for f in os.listdir(d) if f.endswith(".tmp")]


class _R:
    """假的 ParseResult，够 upload_queue 打包即可。"""

    def __init__(self, sha, i):
        self.sha256 = sha
        self.file_name = f"f{i}.pdf"
        self.file_size = 1
        self.ext = ".pdf"
        self.parser = "x"
        self.status = "parsed"
        self.error = None
        self.text = "t"
        self.structure = {}
        self.entities = []
        self.chunks = []


def part_a_index_crash_safe(tmp):
    """[A] 索引写盘中断后，磁盘上仍是**上一份完整索引**，不是半截 JSON。"""
    print("\n[A] 扫描索引：写盘中断后旧索引必须完整")
    d = _mkproj(tmp, "pa")
    good = {"files": {f"f{i}": {"sha256": f"s{i}", "status": "parsed"}
                      for i in range(2000)},
            "devices": {}, "workshops": {}}
    sc._save_index(good, d)
    p = os.path.join(d, "index.json")
    size_ok = os.path.getsize(p)
    loaded = sc._load_index(d)
    check("基线：2000 条索引正常写完可读",
          len(loaded.get("files") or {}) == 2000, f"实得 {len(loaded.get('files') or {})} 条")

    real_dump = json.dump
    json.dump = _halfway_dump          # scanner 与 json 模块同名全局生效
    try:
        try:
            sc._save_index(dict(good, files=dict(good["files"], __probe__={"x": 1})), d)
            crashed = False
        except _Boom:
            crashed = True
    finally:
        json.dump = real_dump

    check("写盘过程确实被打断（模拟断电生效）", crashed, "没有抛出模拟异常")
    after_size = os.path.getsize(p)
    check("中断后索引文件大小未被截短", after_size == size_ok,
          f"原 {size_ok} B → 现 {after_size} B")
    try:
        got = json.load(open(p, encoding="utf-8"))
        parse_ok, n = True, len(got.get("files") or {})
    except Exception as e:                                # noqa: BLE001
        parse_ok, n = False, 0
        got = None
        print(f"    解析失败：{type(e).__name__}: {str(e)[:70]}")
    check("中断后索引仍是合法 JSON", parse_ok)
    check("中断后仍能读出完整 2000 条（用户资料库不丢）", parse_ok and n == 2000,
          f"实得 {n} 条")
    check("中断后没有残留 .tmp", _tmp_left(d) == [], f"残留 {_tmp_left(d)}")

    # 正常再写一份，确认中断没有把写盘路径搞坏
    sc._save_index(good, d)
    check("中断后再次正常写入可用", len(sc._load_index(d).get("files") or {}) == 2000)


def part_b_index_concurrent(tmp):
    """[B] 扫描线程与网页上传线程同时写索引：文件永远可读、无残留 .tmp、无异常。"""
    print("\n[B] 扫描索引：并发写不产生半截文件")
    d = _mkproj(tmp, "pb")
    p = os.path.join(d, "index.json")
    sc._save_index({"files": {}, "devices": {}, "workshops": {}}, d)

    errs = []
    unreadable = []
    real_dump = json.dump

    def _slow_dump(obj, fp, **kw):
        # 放大写盘窗口，让"并发撞进同一个写区间"更容易发生
        s = json.dumps(obj, ensure_ascii=False, indent=1)
        for i in range(0, len(s), 4096):
            fp.write(s[i:i + 4096])
        return None

    bar = threading.Barrier(8)

    def worker(k):
        try:
            idx = {f"f{i}": {"sha256": f"s{i}", "status": "parsed", "who": k}
                   for i in range(600)}
            bar.wait()
            for _ in range(3):
                sc._save_index({"files": idx, "devices": {}, "workshops": {}}, d)
                # 每次写完之后立刻读一次：原子替换意味着任何时刻都是完整的一份
                try:
                    with open(p, encoding="utf-8") as f:
                        json.load(f)
                except Exception as e:                    # noqa: BLE001
                    unreadable.append(f"{type(e).__name__}: {str(e)[:50]}")
        except Exception as e:                            # noqa: BLE001
            errs.append(f"{type(e).__name__}: {str(e)[:60]}")

    json.dump = _slow_dump
    try:
        ths = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
        [t.start() for t in ths]
        [t.join() for t in ths]
    finally:
        json.dump = real_dump

    check("8 线程 × 3 轮并发写索引：0 错误", not errs, f"错误 {errs[:3]}")
    check("并发期间读到的索引从未损坏（0 次解析失败）", not unreadable,
          f"损坏 {len(unreadable)} 次：{unreadable[:2]}")
    fin = sc._load_index(d)
    check("并发结束后索引可读且完整 600 条",
          len(fin.get("files") or {}) == 600, f"实得 {len(fin.get('files') or {})} 条")
    check("并发结束后无残留 .tmp", _tmp_left(d) == [], f"残留 {_tmp_left(d)}")


def part_c_queue_unique(tmp):
    """[C] 20 个不同文件并发入队：索引一条不少、包一个不少、无残留 .tmp。"""
    print("\n[C] 上传队列：并发入队不丢索引")
    d = _mkproj(tmp, "pc")
    uq._ensure()
    n = 20
    errs = []
    bar = threading.Barrier(n)

    def worker(i):
        try:
            bar.wait()
            uq.enqueue(_R(f"sha{i:04d}", i))
        except Exception as e:                            # noqa: BLE001
            errs.append(f"{type(e).__name__}: {str(e)[:60]}")

    ths = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    [t.start() for t in ths]
    [t.join() for t in ths]

    idx = uq._load_idx()
    pkgs = [f for f in os.listdir(uq.QUEUE_DIR)
            if f.endswith(".json") and f != uq._IDX_FILE]
    check(f"{n} 路并发入队：0 错误", not errs, f"错误 {errs[:3]}")
    check(f"去重索引 {n} 条一条不少", len(idx) == n, f"实得 {len(idx)} 条")
    check(f"队列包 {n} 个一个不少", len(pkgs) == n, f"实得 {len(pkgs)} 个")
    check("并发入队后无残留 .tmp", _tmp_left(uq.QUEUE_DIR) == [],
          f"残留 {_tmp_left(uq.QUEUE_DIR)}")


def part_d_queue_dedup(tmp):
    """[D] 同一批 sha 再来 20 路：必须去重（不再入队），索引也不丢。"""
    print("\n[D] 上传队列：重复入队必须去重")
    d = _mkproj(tmp, "pd")
    uq._ensure()
    base = 20
    for i in range(base):
        uq.enqueue(_R(f"sha{i:04d}", i))
    pkg_before = len([f for f in os.listdir(uq.QUEUE_DIR)
                      if f.endswith(".json") and f != uq._IDX_FILE])

    n = 20
    errs = []
    ret = []
    bar = threading.Barrier(n)

    def worker(i):
        try:
            bar.wait()
            ret.append(uq.enqueue(_R(f"sha{i:04d}", i)))
        except Exception as e:                            # noqa: BLE001
            errs.append(f"{type(e).__name__}: {str(e)[:60]}")

    ths = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    [t.start() for t in ths]
    [t.join() for t in ths]

    pkg_after = len([f for f in os.listdir(uq.QUEUE_DIR)
                     if f.endswith(".json") and f != uq._IDX_FILE])
    idx = uq._load_idx()
    check(f"重复 {n} 路并发：0 错误", not errs, f"错误 {errs[:3]}")
    check("包数没有增长（去重生效，没重复打包）", pkg_after == pkg_before,
          f"前 {pkg_before} 个 → 后 {pkg_after} 个")
    check(f"索引仍是 {base} 条，一条没丢", len(idx) == base, f"实得 {len(idx)} 条")
    check(f"重复调用都返回已有包名（{n} 个返回值）", len(ret) == n, f"实得 {len(ret)}")


def part_e_queue_logged(tmp):
    """[E] 索引写盘失败必须留痕，不能再 except: pass 静默吞掉。"""
    print("\n[E] 上传队列：索引写盘失败必须留痕")
    d = _mkproj(tmp, "pe")
    uq._ensure()

    real_open = open
    buf = io.StringIO()
    real_stdout = sys.stdout

    def _bad_open(path, *a, **kw):
        if str(path).endswith(".tmp"):
            raise OSError("模拟磁盘写满")
        return real_open(path, *a, **kw)

    import builtins
    builtins.open = _bad_open
    sys.stdout = buf
    try:
        uq._save_idx({"x": "y"})
    finally:
        builtins.open = real_open
        sys.stdout = real_stdout

    out = buf.getvalue()
    check("写盘失败时打印了留痕信息", "索引写盘失败" in out, f"实得输出 {out!r}")
    check("留痕里带上了原始错误原因", "模拟磁盘写满" in out, f"实得输出 {out!r}")
    check("失败后没有残留 .tmp", _tmp_left(uq.QUEUE_DIR) == [],
          f"残留 {_tmp_left(uq.QUEUE_DIR)}")


def main():
    tmp = tempfile.mkdtemp(prefix="atomic_io_")
    _root, _cur = pm.PROJECTS_ROOT, pm.CURRENT_PROJECT_FILE
    print("=" * 62)
    print("v0.1.198 回归：扫描索引 / 上传队列索引的原子写与并发")
    print("=" * 62)
    try:
        part_a_index_crash_safe(tmp)
        part_b_index_concurrent(tmp)
        part_c_queue_unique(tmp)
        part_d_queue_dedup(tmp)
        part_e_queue_logged(tmp)
    finally:
        pm.PROJECTS_ROOT, pm.CURRENT_PROJECT_FILE = _root, _cur
        uq.QUEUE_DIR = None
        uq.LOG_PATH = None
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "-" * 62)
    print(f"结果：通过 {_PASS[0]} / 失败 {len(_FAIL)} / 共 {_PASS[0] + len(_FAIL)}")
    for f in _FAIL:
        print(f"  FAIL: {f}")
    sys.exit(0 if not _FAIL else 1)


if __name__ == "__main__":
    main()
