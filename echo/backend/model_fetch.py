"""
Echo - Whisper 模型按需下载

安装包不再内置 483MB 的 model.bin：565MB 的安装包大头就是它。改成**按需下载**：

- **app 启动时就开始下**（main.py 触发），不等到第一次开课 —— 那时候已经太晚
- 下到用户数据目录（打包后 %APPDATA%\\Echo\\models），下过一次就永远离线可用
- 进度由 UI 的定时器调 poll_progress() 扫盘算出来，显示在状态栏上 ——
  学生看到的不是干等，是「正在下载语音识别模型 40%（只下一次，以后离线可用）」
- 只用 huggingface_hub（faster-whisper 本来就依赖它），不引新的包
- 下载失败不拦着上课：WhisperModel 自己还有「从 HF 缓存加载」的兜底路径
"""
import logging
import os
import shutil
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
        # max_workers=1：串行下载让进度是线性的，看着不跳
        path = snapshot_download(
            repo_id=HF_REPO,
            local_dir=model_dir(),
            allow_patterns=list(FILES),
            max_workers=1,
        )
        _materialize(path)
        if not is_ready():
            raise RuntimeError(f"下载完了但文件不在位：{path}")
        _done = True
        _progress["percent"] = 100
        log.info("Whisper 模型下载完成: %s", model_dir())
        if callback:
            callback(model_dir())
    except Exception as e:
        _progress["percent"] = -1
        # 不拦着上课：WhisperModel 还有「从 HF 缓存加载」的兜底；模型这边等下次开课再试
        log.warning("Whisper 模型下载失败（开课时会再试）: %s", e)


def _materialize(src: str):
    """确认四个文件真的落在 model_dir() 里，不在就从下载落点拷过来。

    huggingface_hub 的 snapshot_download(local_dir=...) 行为在不同版本/网络状况下
    并不一致：实测 0.29.3 在文件已经在 HF 缓存里时，会把文件留在缓存目录、
    local_dir 反而是空的。与其跟它较劲，不如下完自己核一遍 —— 本地拷 483MB
    只要几秒，比「以为下好了其实没下」强得多。
    """
    if is_ready():
        return
    dst = model_dir()
    os.makedirs(dst, exist_ok=True)
    for f in FILES:
        s, d = os.path.join(src, f), os.path.join(dst, f)
        if os.path.isfile(s) and not os.path.isfile(d):
            shutil.copy2(s, d)


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
