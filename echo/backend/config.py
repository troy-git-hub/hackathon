"""
Echo - 后端配置
所有配置从环境变量 / 项目根目录 .env 读取。
"""
import os

# 国内默认走 HF 镜像下载 Whisper 模型
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# 禁用 xet 后端，避免 401 Unauthorized 下载失败
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

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
# ---------- 「圈一下问 AI」视觉模型 ----------
# 优先用 Qwen-VL（阿里云百炼），真正的视觉模型，能读屏/OCR 公式；没有 key 时退回 DeepSeek 视觉
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWEN_VL_MODEL = os.getenv("ECHO_QWEN_VL_MODEL", "qwen-vl-plus")   # 更准可换 qwen-vl-max
VISION_MODEL = os.getenv("ECHO_VISION_MODEL", "deepseek-flash")
# 桌宠皮肤：modern 矢量 AI 猫 + 声纹条 / classic 原来的表情包猫
PET_SKIN = os.getenv("ECHO_PET_SKIN", "modern")

# ---------- 课堂引擎 ----------
# 每隔多少秒把新 transcript 交给 LLM 抽一次 concept
CONCEPT_INTERVAL = _int("ECHO_CONCEPT_INTERVAL", 30)
# 新 transcript 至少多少字才值得抽 concept
CONCEPT_MIN_CHARS = _int("ECHO_CONCEPT_MIN_CHARS", 40)
# 点「我掉队了」时回看多少秒 transcript
LOST_WINDOW = _int("ECHO_LOST_WINDOW", 300)
# 掉队分析的 LLM 超时（秒），超时走规则兜底，保证 UI 不会一直转圈
BREAKPOINT_TIMEOUT = _int("ECHO_BREAKPOINT_TIMEOUT", 12)
# 断点结果出来后，最多再等多久让未处理转写并入时间轴（秒）
FLUSH_GRACE = float(os.getenv("ECHO_FLUSH_GRACE", "2"))

# ---------- 音频来源 ----------
# system: 抓电脑正在播放的声音（网课/会议）+ Whisper   mic: 麦克风   demo: 回放示例讲稿
SOURCE = os.getenv("ECHO_SOURCE", "system")
DEMO_LINE_INTERVAL = float(os.getenv("ECHO_DEMO_INTERVAL", "3"))
DEMO_SCRIPT = os.getenv("ECHO_DEMO_SCRIPT", "")  # 可选：自定义 transcript 文本文件
# 现场兜底：音频采集失败时自动改放示例讲稿（1=开，0=关）
AUTO_DEMO = os.getenv("ECHO_AUTO_DEMO", "1") != "0"
# 强制离线：不调 LLM，全部走规则 / mock（断网演示用）
OFFLINE = os.getenv("ECHO_OFFLINE", "0") == "1"

# ---------- ASR ----------
AUDIO_DEVICE = os.getenv("ECHO_AUDIO_DEVICE", "")  # 空=默认输入；可填设备序号或名称片段（如“立体声混音”）
WHISPER_MODEL = os.getenv("ECHO_WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("ECHO_WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("ECHO_WHISPER_COMPUTE", "int8")
ASR_CHUNK_SECONDS = float(os.getenv("ECHO_ASR_CHUNK", "6"))
