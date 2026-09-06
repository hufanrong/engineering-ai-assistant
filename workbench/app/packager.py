# 繁工AI 本地解析工作台 - 解析库打包/合并（v0.1.9）
# 场景：多台电脑各自解析工程资料 → 导出 .fglib 库包 → 导入合并为一个完整库。
# 去重口径（v3.7 锁定）：SHA256 相同 → 去重；同名不同哈希（多版本）→ 保留全部，最新时间戳为准。
# 合并后自动重建关联图谱 relations.json。

import os
import io
import json
import zipfile
import datetime

from . import config


def export_library() -> bytes:
    """把 data/ 下可迁移部分打成 .fglib（index.json + parsed_cache/ + relations.json + upload_log 摘要）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        index_path = os.path.join(config.DATA_DIR, "index.json")
        rel_path = os.path.join(config.DATA_DIR, "relations.json")
        cache_dir = os.path.join(config.DATA_DIR, "parsed_cache")
        if os.path.exists(index_path):
            zf.write(index_path, "index.json")
        if os.path.exists(rel_path):
            zf.write(rel_path, "relations.json")
        if os.path.isdir(cache_dir):
            for fn in sorted(os.listdir(cache_dir)):
                fp = os.path.join(cache_dir, fn)
                if fn.endswith(".json"):
                    zf.write(fp, f"parsed_cache/{fn}")
        manifest = {
            "app": "fangong-workbench",
            "format": "fglib-v1",
            "exported_at": datetime.datetime.now().isoformat(),
            "node": config.NODE_NAME,
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    return buf.getvalue()


def import_library(raw: bytes) -> dict:
    """导入 .fglib：SHA256 去重合并进本地库，随后重建关联图谱。
    返回合并统计：{index_added, index_dup, caches_added, cache_conflict, relations_merged}"""
    stats = {"index_added": 0, "index_dup": 0, "caches_added": 0,
             "cache_conflict": 0, "relations_merged": False, "error": None}
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        names = zf.namelist()
        if "index.json" not in names:
            stats["error"] = "不是有效的 .fglib 库包（缺少 index.json）"
            return stats
        manifest = json.loads(zf.read("manifest.json").decode("utf-8")) if "manifest.json" in names else {}
        if manifest.get("format") != "fglib-v1":
            stats["error"] = "库包格式不兼容"
            return stats

        # 1) 合并 index.json
        idx = {}
        idx_path = os.path.join(config.DATA_DIR, "index.json")
        if os.path.exists(idx_path):
            with open(idx_path, encoding="utf-8") as f:
                idx = json.load(f)
        incoming_idx = json.loads(zf.read("index.json").decode("utf-8"))
        for sha, info in incoming_idx.items():
            # v0.1.32：登记版本（同名不同 sha → 多版本对照，按时间戳最新版为准）
            try:
                from . import version_manager
                version_manager.record_version(
                    info.get("file_name", ""), sha,
                    ts=info.get("ts", "") or datetime.datetime.now().isoformat(),
                    source_node=manifest.get("node", "imported"),
                    size=info.get("size", 0),
                    status=info.get("status", "parsed"))
            except Exception:  # noqa: BLE001
                pass
            if sha in idx:
                stats["index_dup"] += 1
                # 升级：包内解析更完整（parsed/partial）则覆盖本地记录（同一 sha=同一文件）
                if info.get("status") in ("parsed", "partial") and \
                        idx[sha].get("status") != info.get("status"):
                    idx[sha] = info
                continue
            idx[sha] = info
            stats["index_added"] += 1
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, indent=1)

        # 2) 合并 parsed_cache（同 sha 内容一致即跳过；不一致以导入库为准覆盖，旧版备份 .conflict.json）
        cache_dir = os.path.join(config.DATA_DIR, "parsed_cache")
        os.makedirs(cache_dir, exist_ok=True)
        for fn in sorted(n for n in names if n.startswith("parsed_cache/") and n.endswith(".json")):
            content = zf.read(fn)
            target = os.path.join(cache_dir, os.path.basename(fn))
            if os.path.exists(target):
                with open(target, "rb") as f:
                    if f.read() == content:
                        continue          # 内容一致视为重复（index 层已计数）
                stats["cache_conflict"] += 1   # 同一 sha 解析结果不同：以导入库为准覆盖
                # 旧内容备份保留，不丢信息
                backup = f"{os.path.splitext(target)[0]}.conflict.json"
                if not os.path.exists(backup):
                    import shutil
                    shutil.copy2(target, backup)
            with open(target, "wb") as f:
                f.write(content)
            stats["caches_added"] += 1

        # 3) relations.json 若本地缺失或更旧 → 合并后重建（幂等）
        rel_path = os.path.join(config.DATA_DIR, "relations.json")
        if "relations.json" in names:
            rel = json.loads(zf.read("relations.json").decode("utf-8"))
            rel["stats"]["merged_from"] = manifest.get("node", "unknown")
            stats["relations_merged"] = True
        try:
            from . import relations
            relations.build_relations(force=True)
        except Exception as e:  # noqa: BLE001
            stats["error"] = f"关联图谱重建失败：{e}"
        return stats
    except zipfile.BadZipFile:
        stats["error"] = "文件损坏或不是 .fglib 库包"
        return stats
    except Exception as e:  # noqa: BLE001
        stats["error"] = f"导入失败：{e}"
        return stats
