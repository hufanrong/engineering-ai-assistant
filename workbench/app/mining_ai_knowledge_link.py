"""
v0.1.95：矿山设备AI助手与资料库深度联动

AI助手能够深度访问解析好的资料库，支持从资料库检索相关设备信息、
施工记录、规范等，结合资料库内容生成更专业的回答，支持多库检索
（项目库+平台规范库）。
"""

import os
import json
import datetime
from typing import Optional


# ============================================================
# AI助手与资料库深度联动
# ============================================================

def search_equipment_in_knowledge_base(
    equipment_name: str = "",
    equipment_tag: str = "",
    workshop: str = "",
) -> dict:
    """
    在资料库中检索设备信息。
    
    Args:
        equipment_name: 设备名称
        equipment_tag: 设备位号
        workshop: 车间
    
    Returns:
        检索结果
    """
    results = {
        "ok": True,
        "equipment_name": equipment_name,
        "equipment_tag": equipment_tag,
        "workshop": workshop,
        "found": False,
        "device_info": {},
        "related_docs": [],
        "related_records": [],
        "related_standards": [],
        "search_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    # 从relations获取设备信息
    try:
        from . import relations as _rel
        g = _rel.load_relations()
        devices = g.get("devices", {})
        
        # 按位号检索
        if equipment_tag and equipment_tag in devices:
            dev = devices[equipment_tag]
            results["found"] = True
            results["device_info"] = {
                "tag": equipment_tag,
                "name": dev.get("name", ""),
                "type": dev.get("type", ""),
                "workshop": dev.get("workshop", ""),
                "model": dev.get("model", ""),
                "manufacturer": dev.get("manufacturer", ""),
                "sources": dev.get("sources", {}),
                "position": dev.get("position", {}),
                "elevation": dev.get("elevation", ""),
                "floor": dev.get("floor", ""),
                "related_drawings": dev.get("drawings", []),
                "related_docs": dev.get("docs", []),
            }
        # 按名称检索
        elif equipment_name:
            for tag, dev in devices.items():
                if equipment_name in dev.get("name", "") or equipment_name in dev.get("type", ""):
                    results["found"] = True
                    results["device_info"] = {
                        "tag": tag,
                        "name": dev.get("name", ""),
                        "type": dev.get("type", ""),
                        "workshop": dev.get("workshop", ""),
                        "model": dev.get("model", ""),
                        "sources": dev.get("sources", {}),
                        "position": dev.get("position", {}),
                    }
                    break
        
        # 按车间检索设备列表
        if workshop:
            workshop_devices = []
            for tag, dev in devices.items():
                if workshop in dev.get("workshop", ""):
                    workshop_devices.append({
                        "tag": tag,
                        "name": dev.get("name", ""),
                        "type": dev.get("type", ""),
                    })
            results["workshop_devices"] = workshop_devices
            results["workshop_device_count"] = len(workshop_devices)
    
    except Exception as e:
        results["relations_error"] = str(e)
    
    # 从资料库检索相关文档
    try:
        from . import scanner as _scanner
        all_results = _scanner.get_all_results()
        related_docs = []
        
        for res in all_results:
            text = (res.get("text", "") + res.get("filename", "")).lower()
            if (equipment_name and equipment_name.lower() in text) or \
               (equipment_tag and equipment_tag.lower() in text) or \
               (workshop and workshop.lower() in text):
                related_docs.append({
                    "filename": res.get("filename", ""),
                    "file_type": res.get("file_type", ""),
                    "text_preview": res.get("text", "")[:200],
                    "workshop": res.get("workshop", ""),
                })
        
        results["related_docs"] = related_docs[:20]
        results["related_docs_count"] = len(related_docs)
    
    except Exception as e:
        results["scanner_error"] = str(e)
    
    # 从平台规范库检索相关规范
    try:
        from . import platform_store as _ps
        standards = _ps.search_platform(equipment_name or equipment_tag or workshop, top_k=10)
        results["related_standards"] = standards.get("results", [])
        results["related_standards_count"] = len(standards.get("results", []))
    except Exception as e:
        results["platform_error"] = str(e)
    
    return results


def generate_ai_context_from_knowledge_base(
    question: str,
    equipment_name: str = "",
    equipment_tag: str = "",
    workshop: str = "",
    include_standards: bool = True,
    include_device_info: bool = True,
    include_related_docs: bool = True,
) -> dict:
    """
    从资料库生成AI问答上下文。
    
    Args:
        question: 用户问题
        equipment_name: 设备名称
        equipment_tag: 设备位号
        workshop: 车间
        include_standards: 是否包含规范
        include_device_info: 是否包含设备信息
        include_related_docs: 是否包含相关文档
    
    Returns:
        AI上下文
    """
    # 检索资料库
    kb_result = search_equipment_in_knowledge_base(
        equipment_name, equipment_tag, workshop
    )
    
    # 构建上下文
    context_parts = []
    
    if include_device_info and kb_result.get("found"):
        dev = kb_result["device_info"]
        context_parts.append("【设备信息】")
        context_parts.append(f"位号：{dev.get('tag', '')}")
        context_parts.append(f"名称：{dev.get('name', '')}")
        context_parts.append(f"类型：{dev.get('type', '')}")
        context_parts.append(f"车间：{dev.get('workshop', '')}")
        if dev.get('model'):
            context_parts.append(f"型号：{dev.get('model', '')}")
        if dev.get('elevation'):
            context_parts.append(f"标高：{dev.get('elevation', '')}")
        if dev.get('position'):
            pos = dev['position']
            context_parts.append(f"位置：x={pos.get('x', '')}, y={pos.get('y', '')}, z={pos.get('z', '')}")
        if dev.get('sources'):
            sources = dev['sources']
            context_parts.append(f"数据来源：CAD={sources.get('cad', 0)}, Excel={sources.get('excel', 0)}, OCR={sources.get('ocr', 0)}")
        context_parts.append("")
    
    if include_related_docs and kb_result.get("related_docs"):
        context_parts.append("【相关文档】")
        for doc in kb_result["related_docs"][:10]:
            context_parts.append(f"- {doc.get('filename', '')}（{doc.get('file_type', '')}）")
            if doc.get("text_preview"):
                context_parts.append(f"  摘要：{doc['text_preview'][:100]}")
        context_parts.append("")
    
    if include_standards and kb_result.get("related_standards"):
        context_parts.append("【相关规范标准】")
        for std in kb_result["related_standards"][:5]:
            context_parts.append(f"- {std.get('title', '')}")
            if std.get("content_preview"):
                context_parts.append(f"  内容：{std['content_preview'][:100]}")
        context_parts.append("")
    
    # 获取设备专业知识
    equipment_knowledge = ""
    if equipment_name or kb_result.get("device_info", {}).get("type"):
        dev_type = kb_result.get("device_info", {}).get("type") or equipment_name
        try:
            from . import mining_equipment as _me
            # 获取吊装参数
            if dev_type in _me.MINING_LIFTING_PARAMS:
                lp = _me.MINING_LIFTING_PARAMS[dev_type]
                equipment_knowledge += f"\n【设备吊装参数】\n"
                equipment_knowledge += f"重量范围：{lp.get('weight_range', '')}\n"
                equipment_knowledge += f"吊点：{lp.get('lifting_points', '')}\n"
                equipment_knowledge += f"注意事项：{lp.get('special_notes', '')}\n"
                equipment_knowledge += f"推荐吊车：{lp.get('crane_recommendation', '')}\n"
        except Exception:
            pass
    
    full_context = "\n".join(context_parts) + equipment_knowledge
    
    # 构建完整提示词
    system_prompt = """你是一位资深矿山工程AI助手，能够深度访问项目资料库和平台规范库。

回答问题时请：
1. 优先使用资料库中的设备信息和相关文档
2. 引用相关规范标准的具体条款
3. 结合设备的实际安装位置、标高、车间等信息
4. 给出具体、可操作的建议，不要泛泛而谈
5. 如果资料库中信息不足，明确指出需要补充哪些信息
6. 区分"资料库中已查证"和"基于专业知识推断"的内容"""
    
    user_prompt = f"""用户问题：{question}

以下是从项目资料库中检索到的相关信息：
{full_context}

请根据以上资料库信息，结合你的专业知识，回答用户问题。"""
    
    return {
        "ok": True,
        "question": question,
        "equipment_name": equipment_name,
        "equipment_tag": equipment_tag,
        "workshop": workshop,
        "knowledge_base_found": kb_result.get("found", False),
        "device_info": kb_result.get("device_info", {}),
        "related_docs_count": kb_result.get("related_docs_count", 0),
        "related_standards_count": kb_result.get("related_standards_count", 0),
        "context": full_context,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "full_prompt": system_prompt + "\n\n" + user_prompt,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def multi_knowledge_base_search(
    query: str,
    search_project: bool = True,
    search_platform: bool = True,
    search_equipment: bool = True,
    top_k: int = 10,
) -> dict:
    """
    多库联合检索（项目库+平台规范库+设备知识库）。
    
    Args:
        query: 检索关键词
        search_project: 是否检索项目库
        search_platform: 是否检索平台规范库
        search_equipment: 是否检索设备知识库
        top_k: 每个库返回的结果数
    
    Returns:
        多库检索结果
    """
    results = {
        "ok": True,
        "query": query,
        "project_results": [],
        "platform_results": [],
        "equipment_results": [],
        "total_results": 0,
        "search_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    # 项目库检索
    if search_project:
        try:
            from . import scanner as _scanner
            all_results = _scanner.get_all_results()
            project_matches = []
            for res in all_results:
                text = (res.get("text", "") + res.get("filename", "")).lower()
                if query.lower() in text:
                    project_matches.append({
                        "filename": res.get("filename", ""),
                        "file_type": res.get("file_type", ""),
                        "text_preview": res.get("text", "")[:200],
                        "workshop": res.get("workshop", ""),
                        "source": "project",
                    })
            results["project_results"] = project_matches[:top_k]
            results["project_count"] = len(project_matches)
        except Exception as e:
            results["project_error"] = str(e)
    
    # 平台规范库检索
    if search_platform:
        try:
            from . import platform_store as _ps
            platform_matches = _ps.search_platform(query, top_k=top_k)
            results["platform_results"] = platform_matches.get("results", [])
            results["platform_count"] = len(platform_matches.get("results", []))
        except Exception as e:
            results["platform_error"] = str(e)
    
    # 设备知识库检索
    if search_equipment:
        try:
            from . import mining_equipment as _me
            equipment_matches = []
            for dev_type in _me.ALL_MINING_EQUIPMENT:
                if query.lower() in dev_type.lower():
                    # 获取吊装参数
                    lifting = _me.MINING_LIFTING_PARAMS.get(dev_type, {})
                    equipment_matches.append({
                        "name": dev_type,
                        "category": _me.EQUIPMENT_CATEGORY_MAP.get(dev_type, ""),
                        "lifting_params": lifting,
                        "source": "equipment_kb",
                    })
            results["equipment_results"] = equipment_matches[:top_k]
            results["equipment_count"] = len(equipment_matches)
        except Exception as e:
            results["equipment_error"] = str(e)
    
    results["total_results"] = (
        results.get("project_count", 0) +
        results.get("platform_count", 0) +
        results.get("equipment_count", 0)
    )
    
    return results


def get_knowledge_base_stats() -> dict:
    """获取资料库统计信息。"""
    stats = {
        "ok": True,
        "project_docs": 0,
        "devices": 0,
        "workshops": 0,
        "platform_standards": 0,
        "equipment_types": 0,
        "stats_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    # 项目文档统计
    try:
        from . import scanner as _scanner
        all_results = _scanner.get_all_results()
        stats["project_docs"] = len(all_results)
    except Exception:
        pass
    
    # 设备统计
    try:
        from . import relations as _rel
        g = _rel.load_relations()
        devices = g.get("devices", {})
        stats["devices"] = len(devices)
        workshops = set()
        for dev in devices.values():
            if dev.get("workshop"):
                workshops.add(dev["workshop"])
        stats["workshops"] = len(workshops)
        stats["workshop_list"] = list(workshops)
    except Exception:
        pass
    
    # 平台规范统计
    try:
        from . import platform_store as _ps
        platform_stats = _ps.get_platform_stats()
        stats["platform_standards"] = platform_stats.get("count", 0)
    except Exception:
        pass
    
    # 设备知识库统计
    try:
        from . import mining_equipment as _me
        stats["equipment_types"] = len(_me.ALL_MINING_EQUIPMENT)
        stats["equipment_categories"] = {k: len(v) for k, v in _me.EQUIPMENT_CATEGORIES.items()}
    except Exception:
        pass
    
    return stats
