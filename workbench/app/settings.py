# 繁工AI 本地解析工作台 - 本机设置（v0.1.249 / D37）
"""本机级设置：目前只有「语义检索开关」。

为什么需要它（v0.1.249 / D37）
---------------------------
语义模型加载失败时，程序一直给用户的提示是：

    「如下载失败，可在「设置」里关闭语义检索，关键词检索不受影响。」

**这个「设置」从来不存在。** 全项目 grep 不到语义开关，也没有设置页 ——
用户被告知了一条走不通的出路，唯一的实际选项是「等」或者「把程序杀掉」。

这不是文案问题，是**逃生通道缺失**：
    · 内网/断网机器上 huggingface.co 不可达，语义模型永远下不下来；
    · 扫描第一个文件就会卡在「下载模型」上（真机实测：done 一直是 0/63，
      整个扫描永远不推进，下游全部读到「0 台设备」）；
    · 用户没有任何办法告诉程序「别再试下载」。

所以这里补上真正的开关，并且让向量库与扫描**真的尊重它**：
关掉之后不再触发任何模型加载与下载，扫描照常走完，
检索退化为关键词检索（本来就支持，不受影响）。

落点：`config.DATA_DIR/settings.json`（本机级，不进项目目录 ——
      这个开关跟资料库内容无关，换项目不该重置）。
"""

import os
import json
import threading

from . import config

_LOCK = threading.RLock()
_SETTINGS_FILE = None  # 延迟到首次使用时按 config.DATA_DIR 解析

# 默认值：语义检索**开**（保持既有行为）。
# 之所以不是默认关：降级路径有界且可见，不需要靠牺牲功能来掩盖问题。
DEFAULTS = {
    "semantic_enabled": True,
}


def _path() -> str:
    """设置文件路径。config.DATA_DIR 是模块级常量，测试里改它即可重定向。"""
    return os.path.join(config.DATA_DIR, "settings.json")


def _read_raw() -> dict:
    p = _path()
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:  # noqa: BLE001 —— 文件损坏不能拖垮整个程序
        return {}


def _write_raw(data: dict) -> bool:
    p = _path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return True
    except Exception:  # noqa: BLE001
        return False


def get_settings() -> dict:
    """当前设置（缺失项用默认值补齐）。"""
    raw = _read_raw()
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        if k in raw:
            out[k] = bool(raw[k])
    return out


def semantic_enabled() -> bool:
    """语义检索是否启用。"""
    return bool(get_settings().get("semantic_enabled", True))


def set_semantic_enabled(flag: bool) -> dict:
    """开关语义检索。返回更新后的设置。

    关掉之后：向量库不再加载/下载模型，扫描不再做向量化，
    检索自动走关键词（search_keyword），资料库本身不受影响。
    """
    val = bool(flag)
    with _LOCK:
        raw = _read_raw()
        raw["semantic_enabled"] = val
        raw["updated_at"] = __import__("datetime").datetime.now().isoformat()
        ok = _write_raw(raw)
    if not ok:
        # 写不进去也不能装作成功 —— 返回值里说清楚。
        return dict(get_settings(), saved=False)
    return get_settings()
