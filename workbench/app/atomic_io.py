# 繁工AI - 原子 JSON 写盘工具（v0.1.199）
#
# 为什么要有这个模块：
#
# 本程序把几乎全部业务状态都存成「一个 JSON 文件」——设备台账、资料库索引、
# 竣工清单、施工日志、隐蔽验收、方案清单、上传队列索引……上线以来同一个缺陷
# 反反复复出现，v0.1.197 修竣工清单、v0.1.198 修扫描索引和上传队列，都是同一回事：
#
#     ① 直接 open(path, "w") 覆盖写 —— 写到一半断电 / 进程被任务管理器强杀 /
#        笔记本电池耗尽，磁盘上留下**半截 JSON**；读取方的 except 一律兜底成 {}，
#        界面表现为「数据全没了」，而且**一个字都不报**。
#        实测（v0.1.198）：2000 条 / 121831 B 的资料库索引，中断后剩 60915 B，
#        JSONDecodeError: Unterminated string at line 4075 → 用户 2000 个已入库
#        文件全被当成没处理过，重扫几小时。
#     ② 临时文件名固定写成 path + ".tmp" —— 两个线程/两个请求同时写，
#        A 把 .tmp rename 走了，B 再 rename 就报「文件不存在」；Windows 上
#        A 还持有句柄时 B 直接 PermissionError。外面的 except 一兜，索引更新
#        被悄悄丢掉，去重失效、同一文件反复入队。
#
# 所以把「原子写」收成一个唯一实现，全仓库统一调用，不再让每个模块自己抄一遍：
#
#     write_json(path, obj, indent=2)
#
# 内部做三件事：
#   1. 临时文件名带 uuid —— 任意多路并发互不踩踏；
#   2. 写完 flush + fsync 再 os.replace —— 替换是原子操作，读方永远只看到
#      「上一份完整文件」或「这一份完整文件」，不存在半截；
#   3. 同一路径一把可重入锁串行化「写」—— 避免两个线程各写一份、后写的
#      覆盖先写的。
#
# 注意锁只覆盖单次写盘。如果调用方是「读全量 → 改一条 → 写全量」，仍然必须
# 自己把整段读改写放进同一把锁（用 path_lock(path) 取锁），否则后写的线程会用
# 旧快照整份覆盖，前面的修改凭空消失 —— v0.1.197 竣工清单丢 4 台设备就是这个。

import json
import os
import threading
import uuid

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def path_lock(path):
    """取某个路径对应的可重入锁。同一路径全局唯一一把。

    用途：调用方要做「读—改—写」时，必须用同一把锁把整段包起来，
    只锁单次写是不够的（后写者会用旧快照覆盖）。
    """
    key = os.path.abspath(os.fspath(path))
    with _LOCKS_GUARD:
        lk = _LOCKS.get(key)
        if lk is None:
            lk = _LOCKS[key] = threading.RLock()
        return lk


def write_json(path, obj, indent=2, ensure_ascii=False, fsync=True):
    """原子写一个 JSON 文件。

    path    目标文件绝对/相对路径
    obj     要写的对象（dict / list / 任意可 json 序列化的值）
    indent  缩进；None 表示紧凑单行（与原 json.dump 的 indent 参数一致）
    """
    path = os.fspath(path)
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with path_lock(path):
        tmp = f"{path}.{uuid.uuid4().hex[:12]}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=ensure_ascii, indent=indent)
                f.flush()
                if fsync:
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        # 某些文件系统（如部分网络盘）不支持 fsync，不必因此失败
                        pass
            os.replace(tmp, path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
    return path


def read_json(path, default=None):
    """读一个 JSON 文件；不存在或损坏时返回 default。

    损坏时**故意**返回 default，但会打印一行留痕 —— 原来各处直接
    `except: return {}`，用户完全看不出数据已经出问题了。
    """
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:  # noqa: BLE001
        try:
            print(f"[atomic_io] 读取失败，按空处理：{path} → {type(e).__name__}: {e}")
        except Exception:  # noqa: BLE001
            pass
        return default



def sweep_orphan_tmp(root, max_age_sec=3600, max_depth=6):
    """清扫 root 目录下历史遗留的孤儿临时文件，返回清除个数。

    只删形如 `xxx.<uuid>.tmp` / `index.XXXXXX.tmp` 这类**本程序自己生成**的
    临时文件，且要求 mtime 早于 max_age_sec（默认 1 小时），避免误删正在写的。

    为什么需要：早期几处写盘用手写 mkstemp 但异常路径里没删临时文件，
    进程被强杀（用户在合并大台账时以为卡死、直接关窗口）后，临时文件
    就永久留在项目目录里。实测现场一个真实项目下积了 3 个 index.*.tmp，
    每个 127304 B、各存一份完整的 228 台设备索引，白占空间且把设备数据
    在用户目录里重复了三份。

    现在 write_json 都有 finally 清理，新代码不会再产生；这个函数只是
    把用户机器上已有的历史垃圾自愈掉。
    """
    import time as _t
    removed = 0
    cutoff = _t.time() - max_age_sec
    root = os.fspath(root)
    if not os.path.isdir(root):
        return 0
    base_depth = os.path.abspath(root).rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.abspath(dirpath).count(os.sep) - base_depth >= max_depth:
            dirnames[:] = []
        for fn in filenames:
            if not fn.endswith(".tmp"):
                continue
            # 只认本程序的两类命名：`<name>.<8~12位hex>.tmp` 与 `index.<6~8位>.tmp`
            if not _is_our_tmp(fn):
                continue
            p = os.path.join(dirpath, fn)
            try:
                st = os.stat(p)
                if st.st_mtime > cutoff:
                    continue          # 可能是正在写的，放过
                os.remove(p)
                removed += 1
            except OSError:
                continue
    return removed


def _is_our_tmp(fn):
    """判断是不是本程序生成的临时文件（而不是用户自己的 .tmp 文件）。

    本程序只产生两种命名，逐个精确匹配，不做模糊判断：
      ① write_json：`<name>.<12位小写hex>.tmp`      （uuid4().hex[:12]）
      ② 旧 mkstemp：`index.<8位小写字母数字>.tmp`     （tempfile.mkstemp 默认）
    用户的 `我的备份.tmp` / `报告.20261104.tmp` 都不会命中。
    """
    import re
    stem = fn[:-4]
    if "." not in stem:
        return False
    head, tail = stem.rsplit(".", 1)
    if not head:
        return False
    if re.fullmatch(r"[0-9a-f]{12}", tail):
        return True
    if re.fullmatch(r"[a-z0-9_]{8}", tail) and head == "index":
        return True
    return False
