"""
Echo - 后端配置
所有配置从环境变量 / 项目根目录 .env 读取。
"""
import os
import sys

# 国内默认走 HF 镜像下载 Whisper 模型
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# 禁用 xet 后端，避免 401 Unauthorized 下载失败
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

try:
    from dotenv import load_dotenv

    from echo.backend import paths

    # 打包后 .env 在 %APPDATA%\Echo（安装目录不可写），首次运行按 .env.example 生成
    load_dotenv(paths.ensure_env())
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

# ---------- 课堂抽问（摸鱼探测） ----------
# 关掉就不抽问：ECHO_CHECKIN=0
CHECKIN = os.getenv("ECHO_CHECKIN", "1") != "0"
# 开课多久之后才允许第一次抽问（秒）—— 太早抽问会打断学生进入状态
CHECKIN_WARMUP = _int("ECHO_CHECKIN_WARMUP", 240)
# 两次抽问之间至少间隔多少秒
CHECKIN_INTERVAL = _int("ECHO_CHECKIN_INTERVAL", 420)
# 学生多久没有任何互动（反馈 / 补课 / 答题）就认为可能在摸鱼（秒）
CHECKIN_IDLE = _int("ECHO_CHECKIN_IDLE", 180)
# 抽问的 LLM 超时，超时就用规则题兜底，不影响听课
CHECKIN_TIMEOUT = _int("ECHO_CHECKIN_TIMEOUT", 10)

# ---------- 音频来源（真实采集） ----------
# system: 抓电脑正在播放的声音（网课/会议）+ Whisper   mic: 麦克风
SOURCE = os.getenv("ECHO_SOURCE", "system")
# 强制离线：不调 LLM，全部走规则 / mock（断网演示用）
OFFLINE = os.getenv("ECHO_OFFLINE", "0") == "1"

# ---------- ASR ----------
AUDIO_DEVICE = os.getenv("ECHO_AUDIO_DEVICE", "")  # 空=默认输入；可填设备序号或名称片段（如“立体声混音”）
WHISPER_MODEL = os.getenv("ECHO_WHISPER_MODEL", "small")


def whisper_model_path() -> str:
    """实际加载 Whisper 用的模型标识。

    打包成 exe 后优先用随程序分发的 models/faster-whisper-small 目录
    （在 sys._MEIPASS 下，离线可用）；开发时用 ECHO_WHISPER_MODEL（走 HF 缓存）。
    """
    if getattr(sys, "frozen", False):
        bundled = os.path.join(getattr(sys, "_MEIPASS", ""), "models", "faster-whisper-small")
        if os.path.isdir(bundled):
            return bundled
    return WHISPER_MODEL


WHISPER_DEVICE = os.getenv("ECHO_WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("ECHO_WHISPER_COMPUTE", "int8")
# Whisper 的 CPU 线程数。线程越多转写越快，但每个线程都会向 MKL 申请一块工作内存，
# 机器内存吃紧（可用内存不足）时会报 mkl_malloc: failed to allocate memory。
# 默认 4；还报错就降到 2，甚至 1。
WHISPER_THREADS = max(1, _int("ECHO_WHISPER_THREADS", 4))
# 让 MKL/OpenMP/oneDNN 的线程数与 ctranslate2 保持一致，避免它们另起线程把内存吃爆。
# 必须在 ctranslate2 初始化前设好（本模块在 faster_whisper 之前 import）。
os.environ["OMP_NUM_THREADS"] = str(WHISPER_THREADS)
os.environ["MKL_NUM_THREADS"] = str(WHISPER_THREADS)
os.environ["DNNL_NUM_THREADS"] = str(WHISPER_THREADS)
ASR_CHUNK_SECONDS = float(os.getenv("ECHO_ASR_CHUNK", "6"))
