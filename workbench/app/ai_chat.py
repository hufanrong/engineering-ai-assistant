# 繁工AI 本地解析工作台 - AI 助手（v0.1.16）
# 目的：工作台内直接对话，自动调用解析好的数据库（项目库+平台库+关系库+资料计划），
#       既能离线生成工程资料（施工方案/吊装方案/施工日志等，Word 模板+检索预填），
#       也能在配置 AI 网关（豆包/企业 Agent 端点）后升级为完整联网问答。
#
# 模式（config.AI_MODE）：
#   local   ：离线可用。资料生成类意图 → docgen 模板预填生成；知识类意图 → 本地多库检索结构化回答
#   gateway ：将检索上下文注入 AI 网关端点 → 返回完整 AI 回答（联网在线搜索由网关承担）
#
# 配置：
#   AI_MODE = "local" | "gateway"
#   AI_GATEWAY_ENDPOINT / AI_GATEWAY_API_KEY：网关 POST {"query", "context", "history"} → {"answer"}

import os
import base64
import json
import re

import requests

from . import config, docgen, docplan, platform_store, relations, vector_store


def _store() -> vector_store.VectorStore:
    """当前项目的向量库。

    v0.1.205：原来这里硬编码 `config.DATA_DIR/vectordb`（全局目录）。
    项目隔离约定（app/project_scope.py）：业务数据一律落在
    data/projects/<project_id>/ 下，向量库也不例外 ——
    main.py 的 _get_store() 与 scanner.py 都是按当前项目取 vector_db 的，
    只有 ai_chat 指向全局库。结果：AI 助手永远检索不到当前项目的资料
    （实测项目 322fef90 有 228 台设备台账，问「磨浮车间有哪些设备」
     返回 sources.project = 0，全局 data/vectordb 目录压根不存在）。
    另外全局库还串了别的项目的数据，属于跨项目串数据。

    这里改成与 main.py._get_store() 同一套解析：当前项目 → 项目级 vector_db；
    没有当前项目时才回退全局库（保功能不失效）。
    """
    try:
        from . import project_manager as _pm
        cur = _pm.get_current_project()
        if cur:
            ddir = _pm.get_project_data_dir(cur["id"])
            if ddir:
                return vector_store.VectorStore(db_path=os.path.join(ddir, "vector_db"))
    except Exception:  # noqa: BLE001
        pass
    return vector_store.VectorStore(db_path=os.path.join(config.DATA_DIR, "vectordb"))


def classify_intent(query: str):
    """识别资料生成意图 → ("doc", 模板类型) 或 ("query", None)。"""
    q = query or ""
    hits = [t for t in docgen.TYPES if t in q]
    if hits:
        # 取 query 中最靠前出现的模板
        hits.sort(key=lambda t: q.index(t))
        return "doc", hits[0]
    return "query", None


def retrieve_context(query: str, top_k: int = 6) -> dict:
    """多库检索：项目库 + 平台库 + 关系库 + 资料计划待办。

    v0.1.205：向量检索不可用时必须降级为关键词检索。
    原来这里只调 store.search()，而 search() 依赖 chromadb + embedding 模型；
    离线单机、模型没下载、chromadb 没装时，search() 直接抛
    ModuleNotFoundError，被 except 吞掉 → ctx["project"] 永远是空列表，
    AI 助手恒定回答「当前解析库未命中相关内容」。
    而 vector_store.search_keyword() 正是为此准备的降级路径
    （直接对 parsed_cache 做中英文关键词匹配，不依赖任何模型），
    main.py 的 /api/search 早就这么做了 —— 这里漏了。

    实测（项目 322fef90，真实台账 228 台设备）：
      降级检索「磨浮车间 设备」命中 1 份《设备台账_真实_选矿厂.xlsx》；
      走 search() 则命中 0 条。
    """
    ctx = {"project": [], "platform": [], "relations": None, "todo": [],
           "retrieval": "vector", "vector_error": ""}
    try:
        for r in _store().search(query, top_k=top_k):
            ctx["project"].append({
                "text": (r.get("text") or "")[:400],
                "file": (r.get("meta") or {}).get("file_name", ""),
                "distance": round(float(r.get("distance", 0)), 3),
            })
    except Exception as e:  # noqa: BLE001
        # 向量库不可用 → 降级关键词检索，命中数照样如实上报
        ctx["vector_error"] = f"{type(e).__name__}: {e}"[:200]
        ctx["retrieval"] = "keyword"
        try:
            for r in _store().search_keyword(query, top_k=top_k):
                ctx["project"].append({
                    "text": (r.get("text") or "")[:400],
                    "file": (r.get("meta") or {}).get("file_name", ""),
                    "distance": round(float(r.get("distance", 0)), 3),
                })
        except Exception as e2:  # noqa: BLE001
            ctx["vector_error"] += f"；降级检索亦失败：{e2}"[:200]
    try:
        for r in platform_store.search(query, top_k=top_k):
            if isinstance(r, dict) and r.get("text"):
                ctx["platform"].append({
                    "text": r["text"][:400],
                    "std_no": r.get("std_no", ""),
                    "status": r.get("status", ""),
                })
    except Exception:  # noqa: BLE001
        pass
    try:
        rel = relations.load_relations()
        # v0.1.205：车间口径原来只读 rel["workshops"]（关系图谱跑出来才有）。
        # 实测项目 322fef90：只导入台账、没跑关系图谱时 rel["workshops"] 是空数组，
        # 但 228 台设备各自带着 workspaces:["粗碎站"] 这类车间归属（合并自台账）。
        # 于是 AI 助手报「0 个车间、60 台设备」——车间数凭空为 0，
        # 设备数还被 [:60] 截断成 60 台（实际 228），两句都在说假话。
        # 修法：车间数优先用图谱的，图谱为空时从设备的 workspaces 字段回补；
        # 设备数报真实总数，截断只用于展示明细。
        ws_names = []
        for w in (rel.get("workshops") or []):
            nm = (w.get("workshop") or w.get("name") or "").strip()
            if nm and nm not in ws_names:
                ws_names.append(nm)
        all_devs = rel.get("devices") or []
        if not ws_names:
            for d in all_devs:
                for nm in (d.get("workshops") or []):
                    nm = str(nm).strip()
                    if nm and nm not in ws_names:
                        ws_names.append(nm)
        ctx["relations"] = {
            "workshops": ws_names,
            "devices": [d.get("tag") or d.get("name") or "" for d in all_devs][:60],
            "device_count": len(all_devs),
            "drawings": len(rel.get("drawings", [])),
        }
    except Exception:  # noqa: BLE001
        pass
    try:
        plans = docplan.plan_status().get("plans", [])
        # v0.1.205：待办字段名原来取错 —— 读的是 p.get("name") 和
        # p.get("missing_summary")，而 docplan.plan_status() 返回的每条是
        # {key, doc_type, desc, state, have, missing, have_files}，
        # 没有 name / missing_summary 这两个键。
        # 结果 AI 回答里 9 项待办的名字全是空字符串，内容全是「资料不全」，
        # 用户看到的是「  - ：资料不全」这种没头没尾的条目。
        # 改成用 doc_type 当名称、missing 拼出「缺什么」。
        todo = []
        for p in plans:
            if str(p.get("state") or "") == "ready":
                continue
            miss = p.get("missing") or []
            if isinstance(miss, str):
                miss = [x.strip() for x in miss.strip("[]").split(",") if x.strip()]
            todo.append({
                "name": p.get("doc_type") or p.get("key") or "",
                "desc": p.get("desc") or "",
                "state": p.get("state") or "",
                "missing": list(miss),
                "missing_summary": ("缺 " + "、".join(str(m) for m in miss[:6])) if miss else "资料齐全",
            })
        ctx["todo"] = todo[:10]
    except Exception:  # noqa: BLE001
        pass
    return ctx


def _prefill(doc_type: str) -> dict:
    """从解析库预填：车间设备清单 + 平台库规范引用（与 ⑧ 页预填同源）。"""
    data = {"项目名称": "", "施工单位": "", "编制日期": ""}
    try:
        g = relations.load_relations()
        ws = [w["workshop"] for w in g.get("workshops", [])]
        if ws:
            data["车间"] = ws[0]
        devs = [d["tag"] for d in g.get("devices", [])][:80]
        if devs:
            data["设备名称"] = devs[0]
            data["设备清单"] = "；".join(devs[:40])
    except Exception:  # noqa: BLE001
        pass
    try:
        idx = platform_store.list_items().get("items", [])
        refs = [it for it in idx[:8] if it.get("std_no")]
        if refs:
            data["规范引用"] = "；".join(f"{it['std_no']}《{it.get('std_name','')}》" for it in refs)
    except Exception:  # noqa: BLE001
        pass
    return data


def _extract_key_data(query: str) -> dict:
    """从用户话里尽力提取关键数据（设备号/重量/高度/位置/日期等），用于预填文档。"""
    data = {}
    m = re.search(r"(?:设备|泵|压缩机|风机|电机)?\s*([A-Za-z]{1,3}-\d{3})", query)
    if m:
        data["设备名称"] = m.group(1)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(t|吨)", query)
    if m:
        data["设备重量"] = f"{m.group(1)}t"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(m|米)", query)
    if m:
        data["吊装高度"] = f"{m.group(1)}m"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(t|吨)[吊起]?重?", query)
    if m:
        data["吊车吨位"] = f"{m.group(1)}t"
    m = re.search(r"(1号车间|2号车间|3号车间|4号车间|[\u4e00-\u9fa5]{1,6}车间)", query)
    if m:
        data["车间"] = m.group(1)
    return data


def chat(query: str, history: list | None = None) -> dict:
    """AI 助手主入口。返回 {mode, answer?, doc?, missing?, sources}。"""
    history = history or []
    intent, dtype = classify_intent(query)

    if intent == "doc":
        # 资料生成：解析库预填 + 用户话中提取的关键数据 → 生成 Word
        try:
            data = _prefill(dtype)
            data.update(_extract_key_data(query))
            content, missing = docgen.fill_template(dtype, data)
            doc_name = f"{dtype}_{data.get('车间') or data.get('设备名称') or '工程'}.docx"
            return {
                "mode": "local_doc",
                "doc_type": dtype,
                "doc": {"file_name": doc_name, "content_b64": base64.b64encode(content).decode()},
                "missing": missing,
                "answer": f"已按「{dtype}」模板生成 Word 文档（检索数据库自动预填 + 提取你给出的关键数据）。"
                          + (f"仍有 {len(missing)} 项待补充：{'、'.join(missing)}。" if missing else "字段已齐全，可直接下载打印签字。"),
            }
        except Exception as e:  # noqa: BLE001
            return {"mode": "error", "answer": f"资料生成失败：{e}"}

    # 知识类意图：多库检索
    ctx = retrieve_context(query)
    sources = {"project": len(ctx["project"]), "platform": len(ctx["platform"])}
    gateway = (config.AI_GATEWAY_ENDPOINT or "").strip().rstrip("/")
    if config.AI_MODE == "gateway" and gateway:
        try:
            r = requests.post(
                gateway,
                json={"query": query, "context": ctx, "history": history[-8:]},
                timeout=90,
                headers={"Authorization": f"Bearer {config.AI_GATEWAY_API_KEY}"} if config.AI_GATEWAY_API_KEY else {},
            )
            if r.status_code == 200:
                d = r.json()
                return {"mode": "gateway", "answer": d.get("answer", "(网关未返回内容)"),
                        "sources": sources, "context": ctx,
                        "retrieval": ctx.get("retrieval") or "vector",
                        "vector_error": ctx.get("vector_error") or ""}
        except Exception as e:  # noqa: BLE001
            return {"mode": "error", "answer": f"AI 网关调用失败：{e}（可切换 local 模式离线使用）", "sources": sources}

    # local 模式：本地结构化回答
    lines = []
    if ctx["project"]:
        lines.append("项目资料库命中（按相关度）：")
        for i, r in enumerate(ctx["project"][:5], 1):
            lines.append(f"  {i}. 《{r['file']}》：{r['text'][:120]}…")
    if ctx["platform"]:
        lines.append("平台规范库命中：")
        for i, r in enumerate(ctx["platform"][:5], 1):
            lines.append(f"  {i}. {r['std_no']}（{r['status']}）：{r['text'][:100]}…")
    if ctx["relations"]:
        rel = ctx["relations"]
        # v0.1.205：设备数报真实总数（device_count），不再用被 [:60] 截断后的明细长度。
        lines.append(f"工程结构：{len(rel['workshops'])} 个车间、{rel.get('device_count', len(rel['devices']))} 台设备、{rel['drawings']} 张图纸已关联。")
    if ctx["todo"]:
        lines.append(f"资料待办 {len(ctx['todo'])} 项待补资料：")
        for p in ctx["todo"][:5]:
            lines.append(f"  - {p.get('name','')}：{p.get('missing_summary') or '资料不全'}")
    if not ctx["project"] and not ctx["platform"]:
        lines.append("当前解析库未命中相关内容。可先在「扫描/上传」页导入项目资料与平台规范。")
    elif ctx.get("retrieval") == "keyword":
        # v0.1.205：降级为关键词检索时如实说明，不要让用户以为这是向量语义检索的结果。
        lines.append(f"（本次按关键词匹配检索，未使用向量语义检索）")
    answer = "\n".join(lines)
    if not gateway:
        answer += ("\n\n（当前为本地检索模式。配置 AI_GATEWAY_ENDPOINT 并设 AI_MODE=gateway 后，"
                   "可升级为联网 AI 问答；资料生成始终离线可用。）")
    # v0.1.205 修正：retrieval / vector_error 原来只塞在 context 里，
    # 顶层不透出 —— 前端拿不到「这次是不是降级检索」，用户看到的来源行
    # 永远只有「项目库 N 条」，看不出检索方式。补到顶层。
    return {"mode": "local_rag", "answer": answer, "sources": sources, "context": ctx,
            "retrieval": ctx.get("retrieval") or "vector",
            "vector_error": ctx.get("vector_error") or ""}
