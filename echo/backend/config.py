"""
Echo - 后端配置
所有配置从环境变量 / 项目根目录 .env 读取。
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
except ImportError:
    pass


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# ---------- LLM (DeepSeek, OpenAI 兼容) ----------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
LLM_TIMEOUT = _int("ECHO_LLM_TIMEOUT", 40)

# ---------- 课堂引擎 ----------
# 每隔多少秒把新 transcript 交给 LLM 抽一次 concept
CONCEPT_INTERVAL = _int("ECHO_CONCEPT_INTERVAL", 30)
# 新 transcript 至少多少字才值得抽 concept
CONCEPT_MIN_CHARS = _int("ECHO_CONCEPT_MIN_CHARS", 40)
# 点「我掉队了」时回看多少秒 transcript
LOST_WINDOW = _int("ECHO_LOST_WINDOW", 300)

# ---------- 音频来源 ----------
# demo: 回放示例课 transcript（现场最稳）  mic: 麦克风/立体声混音 + Whisper
SOURCE = os.getenv("ECHO_SOURCE", "demo")
DEMO_LINE_INTERVAL = float(os.getenv("ECHO_DEMO_INTERVAL", "3"))
DEMO_SCRIPT = os.getenv("ECHO_DEMO_SCRIPT", "")  # 可选：自定义 transcript 文本文件

# ---------- ASR ----------
AUDIO_DEVICE = os.getenv("ECHO_AUDIO_DEVICE", "")  # 空=默认输入；可填设备序号或名称片段（如“立体声混音”）
WHISPER_MODEL = os.getenv("ECHO_WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("ECHO_WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("ECHO_WHISPER_COMPUTE", "int8")
ASR_CHUNK_SECONDS = float(os.getenv("ECHO_ASR_CHUNK", "6"))
