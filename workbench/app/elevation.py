# 繁工AI 本地解析工作台 - 设备标高/楼层 z 坐标提取（v0.1.38）
# 目的：从设备台账、CAD 图纸标注、OCR 铭牌中提取设备安装标高/楼层，
#       完善空间结构模型的 z 坐标，让 AI 能理解设备的竖向位置。
#
# 口径（用户锁定）：
#   - 不用真正的三维模型，能理解空间结构就可以
#   - 空间数据主要来自图纸，车间有哪些设备来自台账文件

import re
import math


# 台账中可能的标高列名关键词
ELEVATION_COLUMNS = [
    "标高", "安装标高", "设备标高", "中心标高", "基础标高",
    "EL", "EL.", "ELEV", "ELEVATION",
    "楼层", "层", "层数", "所在层", "楼层号",
    "FLOOR", "LEVEL",
    "高度", "安装高度", "设备高度",
]

# 标高正则
# EL+100.000, EL100.000, EL+5.5, ±0.000, +5.500, -2.500, 100.00m, 5.5m
_EL_RE = re.compile(
    r"(?:EL\.?\s*)?([+-]?\d+\.?\d*)\s*(?:m|米|MM|mm)?",
    re.IGNORECASE
)
# 带 ± 的标高
_ELEV_SYMBOL_RE = re.compile(r"[±+-]\s*\d+\.?\d*")
# 楼层：3层、2F、二楼、地下1层、B1、F2
_FLOOR_RE = re.compile(r"(?:(地下|地上)?\s*(\d+)\s*层)|(?:([BbFf])\s*(\d+))|(?:(\d+)\s*([FfBb]))|([一二三四五六七八九十]+)楼")

# 标准层高（米），用于楼层→标高换算
DEFAULT_FLOOR_HEIGHT = 3.0
# 1层（地上1层）对应标高 0.000m
GROUND_FLOOR_ELEVATION = 0.0


def parse_elevation(value: str) -> dict:
    """解析标高/楼层字符串，返回 {elevation_m, source_type, raw, confidence}。
    elevation_m 为 None 表示无法解析。"""
    if not value:
        return {"elevation_m": None, "source_type": "unknown", "raw": value, "confidence": 0}

    val = str(value).strip()
    if not val:
        return {"elevation_m": None, "source_type": "unknown", "raw": value, "confidence": 0}

    # 1) 楼层格式
    floor_match = _FLOOR_RE.search(val)
    if floor_match:
        floor_num = None
        is_basement = False

        if floor_match.group(2):  # "3层" 格式
            floor_num = int(floor_match.group(2))
            is_basement = floor_match.group(1) == "地下"
        elif floor_match.group(4):  # "B1" 或 "F2" 格式（前缀在前）
            prefix = floor_match.group(3).upper()
            floor_num = int(floor_match.group(4))
            is_basement = prefix == "B"
        elif floor_match.group(5):  # "2F" 或 "1B" 格式（数字在前）
            floor_num = int(floor_match.group(5))
            prefix = floor_match.group(6).upper()
            is_basement = prefix == "B"
        elif floor_match.group(7):  # "二楼" 格式
            cn_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                      "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            floor_num = cn_map.get(floor_match.group(7), 0)

        if floor_num is not None and floor_num > 0:
            if is_basement:
                elevation = GROUND_FLOOR_ELEVATION - floor_num * DEFAULT_FLOOR_HEIGHT
            else:
                elevation = GROUND_FLOOR_ELEVATION + (floor_num - 1) * DEFAULT_FLOOR_HEIGHT
            return {
                "elevation_m": round(elevation, 2),
                "source_type": "floor",
                "raw": val,
                "floor": floor_num,
                "is_basement": is_basement,
                "confidence": 0.7,
                "note": f"按标准层高{DEFAULT_FLOOR_HEIGHT}m换算",
            }

    # 2) EL 格式：EL+100.000, EL100.000, EL+5.5
    el_match = re.search(r"EL\.?\s*([+-]?\d+\.?\d*)", val, re.IGNORECASE)
    if el_match:
        num = float(el_match.group(1))
        # 如果数值 > 100，可能是毫米单位，转换为米
        if abs(num) > 100:
            num = num / 1000.0
        return {
            "elevation_m": round(num, 3),
            "source_type": "EL",
            "raw": val,
            "confidence": 0.95,
        }

    # 3) ±0.000 格式
    sym_match = _ELEV_SYMBOL_RE.search(val)
    if sym_match:
        num_str = sym_match.group(0).replace("±", "+").replace(" ", "")
        try:
            num = float(num_str)
            return {
                "elevation_m": round(num, 3),
                "source_type": "symbol",
                "raw": val,
                "confidence": 0.9,
            }
        except ValueError:
            pass

    # 4) 纯数字 + m/米：5.5m, 100.000m, 3米
    pure_match = re.search(r"([+-]?\d+\.?\d*)\s*(?:m|米)", val, re.IGNORECASE)
    if pure_match:
        num = float(pure_match.group(1))
        if abs(num) > 100:
            num = num / 1000.0
        return {
            "elevation_m": round(num, 3),
            "source_type": "meter",
            "raw": val,
            "confidence": 0.8,
        }

    # 5) 纯数字（可能是标高值），但需要上下文判断，这里低置信度
    pure_num = re.match(r"^[+-]?\d+\.?\d*$", val)
    if pure_num:
        num = float(val)
        if -100 < num < 500:  # 合理标高范围
            if abs(num) > 100:
                num = num / 1000.0
            return {
                "elevation_m": round(num, 3),
                "source_type": "number",
                "raw": val,
                "confidence": 0.4,
            }

    return {"elevation_m": None, "source_type": "unknown", "raw": val, "confidence": 0}


def extract_from_excel(structure: dict) -> dict:
    """从 Excel 解析结构中提取设备标高。
    返回 {tag: {elevation_m, source_type, confidence, column}}。"""
    result = {}
    sheets = structure.get("sheets", [])
    if not sheets:
        return result

    for sheet in sheets:
        header = sheet.get("header", [])
        rows = sheet.get("rows", [])

        # 找到标高列
        elev_col = None
        for h in header:
            h_lower = str(h).upper().strip()
            for kw in ELEVATION_COLUMNS:
                if kw.upper() in h_lower:
                    elev_col = h
                    break
            if elev_col:
                break

        if not elev_col:
            continue

        # 找到位号列
        tag_col = None
        for h in header:
            h_str = str(h).strip()
            if h_str in ("位号", "设备位号", "设备编号", "编号", "TAG", "tag"):
                tag_col = h
                break

        for row in rows:
            tag = str(row.get(tag_col, "")).strip() if tag_col else ""
            elev_val = str(row.get(elev_col, "")).strip()
            if not tag or not elev_val or elev_val in ("-", "/", "无", "N/A", "NA"):
                continue
            parsed = parse_elevation(elev_val)
            if parsed["elevation_m"] is not None:
                parsed["column"] = elev_col
                parsed["sheet"] = sheet.get("sheet", "")
                # 高置信度覆盖低置信度
                if tag not in result or parsed["confidence"] > result[tag]["confidence"]:
                    result[tag] = parsed

    return result


def extract_from_cad(text: str) -> list:
    """从 CAD 文本中提取标高标注。
    返回 [{elevation_m, source_type, raw, context}]。"""
    results = []
    if not text:
        return results

    # EL 格式
    for m in re.finditer(r"EL\.?\s*[+-]?\d+\.?\d*", text, re.IGNORECASE):
        parsed = parse_elevation(m.group(0))
        if parsed["elevation_m"] is not None:
            start = max(0, m.start() - 30)
            end = min(len(text), m.end() + 30)
            parsed["context"] = text[start:end].replace("\n", " ")
            results.append(parsed)

    # ±0.000 格式
    for m in re.finditer(r"[±+-]\s*\d+\.\d{3}", text):
        parsed = parse_elevation(m.group(0))
        if parsed["elevation_m"] is not None:
            start = max(0, m.start() - 30)
            end = min(len(text), m.end() + 30)
            parsed["context"] = text[start:end].replace("\n", " ")
            results.append(parsed)

    return results


def build_elevation_map(docs: dict) -> dict:
    """从所有已解析文档中构建设备标高映射。
    返回 {tag: {elevation_m, source_type, confidence, source_file}}。"""
    elevation_map = {}

    for sha, d in docs.items():
        parser = d.get("parser", "")
        structure = d.get("structure") or {}
        file_name = d.get("file_name", "")

        if parser == "excel":
            # 从台账提取
            excel_elev = extract_from_excel(structure)
            for tag, elev in excel_elev.items():
                elev["source_file"] = file_name
                if tag not in elevation_map or elev["confidence"] > elevation_map[tag]["confidence"]:
                    elevation_map[tag] = elev

        elif parser == "cad":
            # 从 CAD 文本提取标高，关联到附近设备
            cad_text = d.get("text", "") or ""
            cad_elevs = extract_from_cad(cad_text)
            # CAD 中标高通常是区域标高，不直接关联到具体设备
            # 这里记录为车间/区域标高，供参考
            if cad_elevs:
                d["_cad_elevations"] = cad_elevs

        elif parser == "ocr":
            # 从 OCR 铭牌提取标高
            ocr_text = d.get("text", "") or ""
            # 尝试从 OCR 文本中提取位号+标高
            tags_in_text = re.findall(r"[A-Z]{1,3}-\d{1,6}", ocr_text)
            for tag in tags_in_text:
                # 在该位号附近找标高
                idx = ocr_text.find(tag)
                context = ocr_text[max(0, idx - 50):min(len(ocr_text), idx + 100)]
                el_match = re.search(r"EL\.?\s*[+-]?\d+\.?\d*", context, re.IGNORECASE)
                if el_match:
                    parsed = parse_elevation(el_match.group(0))
                    if parsed["elevation_m"] is not None:
                        parsed["source_file"] = file_name
                        parsed["source_type"] = "ocr"
                        if tag not in elevation_map or parsed["confidence"] > elevation_map[tag]["confidence"]:
                            elevation_map[tag] = parsed

    return elevation_map
