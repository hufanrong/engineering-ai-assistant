# 繁工AI 本地解析工作台 - 手机语音自动转写引擎（v0.1.26）
# 适配器设计：local(whisper/faster-whisper) / gateway(AI 网关 /transcribe) / none(待转写清单人工补录)
# 部署提示：pip install faster-whisper 后自动启用本地转写；或配置 VOICE_GATEWAY_ENDPOINT 走网关。
import os

from . import config

# 测试/外部注入 hook：Mock 用
_ENGINE = None


def _set_engine(engine):
    global _ENGINE
    _ENGINE = engine


def _whisper_local(path: str):
    """本机 faster-whisper / openai-whisper 转写；未装返回 None。"""
    try:
        from faster_whisper import WhisperModel  # noqa: N813
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(path, language="zh")
        return "".join(s.text for s in segments).strip()
    except Exception:  # noqa: BLE001
        pass
    try:
        import whisper
        m = whisper.load_model("small")
        return m.transcribe(path, language="zh").get("text", "").strip()
    except Exception:  # noqa: BLE001
        return None


def _gateway(path: str):
    """AI 网关 /transcribe：POST 音频文件 → {text}。"""
    import requests
    ep = (config.VOICE_GATEWAY_ENDPOINT or "").rstrip("/")
    if not ep:
        return None
    try:
        with open(path, "rb") as fh:
            r = requests.post(f"{ep}/transcribe", files={"file": (os.path.basename(path), fh)},
                              timeout=120)
        if r.status_code == 200:
            d = r.json()
            return (d.get("text") or "").strip() or None
    except Exception:  # noqa: BLE001
        return None
    return None


def transcribe_audio(path: str):
    """转写语音文件 → (text, mode)。text 为 None 表示无法自动转写（待人工）。"""
    if _ENGINE is not None:
        try:
            t = _ENGINE(path)
            return (t or "").strip() or None, "mock"
        except Exception:  # noqa: BLE001
            return None, "mock"
    mode = (config.VOICE_TRANSCRIBE_MODE or "auto").lower()
    if mode == "gateway":
        return _gateway(path), "gateway"
    if mode == "local":
        return _whisper_local(path), "local"
    # auto：优先本机模型，网关兜底
    t = _whisper_local(path)
    if t:
        return t, "local"
    t2 = _gateway(path)
    if t2:
        return t2, "gateway"
    return None, "none"


def is_voice_file(name: str) -> bool:
    return os.path.splitext(name or "")[1].lower() in config.VOICE_EXT
