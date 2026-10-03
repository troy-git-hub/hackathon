"""
Echo - Whisper 模型按需下载

安装包不再内置 483MB 的 model.bin：565MB 的安装包大头是它，GitHub Release 虽装得下，
但评装体验差 —— 装完第一次开课还要陪它一起等。改成**第一次开课时后台下载**：

- 下到用户数据目录（打包后 %APPDATA%\Echo\models），下过一次就永远离线可用
- 进度经引擎的 status 事件进 UI —— 学生看到的不是黑等，是「正在下载语音识别模型
  37%」，跟现有的「正在加载语音识别」同一套反馈路
- 只用 huggingface_hub（faster-whisper 本来就依赖它），不引新的包
- 下载失败不拦着上课：WhisperModel 自己还有「从 HF 缓存加载」的兜底路径
"""
import logging
import os
import threading

from echo.backend import config

log = logging.getLogger("echo.model_fetch")

HF_REPO = "Systran/faster-whisper-small"
FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
# model.bin 483MB，其余三个共 2.7MB —— 用它的字节占比算总进度，误差不到 1%
MODEL_BIN_BYTES = 483_546_902
TOTAL_BYTES = MODEL_BIN_BYTES + 2_704_000

_lock = threading.Lock()
_thread = None          # 正在跑的下载线程（同一时刻最多一个）
_done = False           # 本次会话里已经确认过「模型齐了」，别反复扫盘
_progress = {"percent": -1}      # 最近一次上报的百分比（10% 一档，免得刷屏）


def model_dir() -> str:
    return os.path.join(config.user_models_dir(), "faster-whisper-small")


def is_ready() -> bool:
    """四个文件都在就算齐（只看存在性，不校验内容——坏文件会在加载时报错，走兜底）。"""
    d = model_dir()
    return all(os.path.isfile(os.path.join(d, f)) for f in FILES)


def percent() -> int:
    """当前下载进度（0~100）。没在下就返回 -1。"""
    return _progress["percent"]


def ensure(callback=None):
    """模型不齐就后台开始下载。callback(下载到的目录) 完成时回调（后台线程里调）。"""
    global _thread, _done
    with _lock:
        if _done or is_ready():
            _done = True
            if callback:
                callback(model_dir())
            return
        if _thread is not None and _thread.is_alive():
            return                      # 已经在下着了，别起两个
        _progress["percent"] = 0
        _thread = threading.Thread(target=_run, args=(callback,), daemon=True,
                                   name="echo-model-download")
        _thread.start()


def _run(callback):
    global _done
    from huggingface_hub import snapshot_download
    try:
        # max_workers=1：串行下载让进度条是线性的，看着不跳
        path = snapshot_download(
            repo_id=HF_REPO,
            local_dir=model_dir(),
            allow_patterns=list(FILES),
            max_workers=1,
            # 进度不走 tqdm（那是给人看的交互条），走每 3 秒扫一次文件大小 —— 简单可靠
            tqdm_class=_QuietTqdm,
        )
        _done = True
        _progress["percent"] = 100
        log.info("Whisper 模型下载完成: %s", path)
        if callback:
            callback(path)
    except Exception as e:
        _progress["percent"] = -1
        # 不拦着上课：WhisperModel 还有「从 HF 缓存加载」的兜底；模型这边等下次开课再试
        log.warning("Whisper 模型下载失败（开课时会再试）: %s", e)


def wait_ready(timeout: float = 1800) -> bool:
    """等模型下好（ASR 线程用）。

    为什么要等：不等的话 WhisperModel 会拿模型名去 HF 缓存再下一遍 —— 同样 483MB，
    白下一份，还跟这里的下载抢带宽。等它下完，从本地目录直接加载一次就好。
    超时返回 False，调用方自己决定要不要走兜底。
    """
    if _done or is_ready():
        return True
    t = _thread
    if t is None:
        return False
    t.join(timeout)
    return is_ready()


def poll_progress():
    """扫一遍模型目录的字节数，更新缓存住的百分比。UI 的定时器隔几秒调一次。"""
    if _progress["percent"] in (-1, 100):
        return _progress["percent"]
    total = 0
    try:
        d = model_dir()
        for f in FILES:
            try:
                total += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
            # .incomplete 后缀是 huggingface_hub 的下载中临时文件
            try:
                total += os.path.getsize(os.path.join(d, f + ".incomplete"))
            except OSError:
                pass
    except OSError:
        return _progress["percent"]
    pct = min(99, int(total * 100 / TOTAL_BYTES))
    if pct >= _progress["percent"] + 10:       # 10% 一档往上跳，别每秒刷
        _progress["percent"] = pct
    return _progress["percent"]


class _QuietTqdm:
    """顶掉 huggingface_hub 的 tqdm：下载进度不走命令行条，走 poll_progress() 扫盘。"""

    def __init__(self, *a, **kw):
        pass

    def __iter__(self):
        return iter(())

    def update(self, n=1):
        pass

    def close(self):
        pass

    def set_description(self, desc=None):
        pass

    @property
    def n(self):
        return 0

    @n.setter
    def n(self, v):
        pass
