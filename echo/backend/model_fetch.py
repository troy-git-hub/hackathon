"""
Echo - Whisper 模型按需下载

安装包不再内置 483MB 的 model.bin：565MB 的安装包大头就是它。改成**按需下载**：

- 第一次启动由界面问要不要下（前台进度条 / 后台 / 以后再说），选过就记住
- 下到用户数据目录（打包后 %APPDATA%\\Echo\\models），下过一次就永远离线可用
- 进度由 UI 的定时器调 poll_progress()。huggingface_hub 2.x 的字节在它自己的
  tqdm 上，目标目录要等下完才有文件，所以不能只扫 model.bin.incomplete
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
_progress = {"percent": -1, "done": 0, "total": TOTAL_BYTES}      # 最近一次的百分比和字节


def model_dir() -> str:
    return os.path.join(config.user_models_dir(), "faster-whisper-small")


def is_ready() -> bool:
    """四个文件都在就算齐（只看存在性，不校验内容——坏文件会在加载时报错，走兜底）。"""
    d = model_dir()
    return all(os.path.isfile(os.path.join(d, f)) for f in FILES)


def percent() -> int:
    """当前下载进度（0~100）。没在下就返回 -1。"""
    return _progress["percent"]


def progress() -> dict:
    """给界面用：percent / done / total（字节）。没在下时 percent 为 -1。"""
    return {"percent": _progress["percent"],
            "done": int(_progress.get("done") or 0),
            "total": int(_progress.get("total") or TOTAL_BYTES)}


def running() -> bool:
    t = _thread
    return t is not None and t.is_alive()


def fmt_bytes(n: int) -> str:
    """跟控制台 tqdm 一样用十进制，免得界面写 39.9MB、控制台写 41.9MB。"""
    n = max(0, int(n or 0))
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f} GB"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    if n >= 1_000:
        return f"{n / 1_000:.0f} KB"
    return f"{n} B"


def _note_bytes(done, total):
    """huggingface 的进度条每动一下就进来。文件还在缓存里、目标目录是空的，也按这个算。

    字节条的 total 是几百 MB；「Fetching 4 files」那种计数条 total 只有几个，丢掉。
    只往前走，不因为另一条条（传输/落盘）短暂回到 0 把百分比打回去。
    """
    try:
        done = int(done or 0)
        total = int(total or 0)
    except (TypeError, ValueError):
        return
    if total < 1_000_000 or done < 0:
        return
    if _progress["percent"] in (-1, 100):
        return
    # 分母用整份模型的大小，不用这条进度条此刻的 total。
    # 小文件先下完时 total 只有几 MB，按它算会一下子到 99%，model.bin 才刚开始。
    if done < int(_progress.get("done") or 0):
        return
    _progress["done"] = done
    if total > int(_progress.get("total") or 0):
        _progress["total"] = total
    pct = min(99, int(done * 100 / TOTAL_BYTES))
    if pct >= _progress["percent"]:
        _progress["percent"] = pct


def _progress_tqdm():
    """包一层 huggingface 的 tqdm，让「Downloading / Reconstructing」的字节数写进 _progress。"""
    from huggingface_hub.utils import tqdm as hf_tqdm

    class _T(hf_tqdm):
        def update(self, n=1):
            super().update(n)
            _note_bytes(getattr(self, "n", 0), getattr(self, "total", 0))

        def refresh(self, *args, **kwargs):
            out = super().refresh(*args, **kwargs)
            _note_bytes(getattr(self, "n", 0), getattr(self, "total", 0))
            return out

    return _T


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
        _progress["done"] = 0
        _progress["total"] = TOTAL_BYTES
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
            tqdm_class=_progress_tqdm(),
        )
        _materialize(path)
        if not is_ready():
            raise RuntimeError(f"下载完了但文件不在位：{path}")
        _done = True
        _progress["percent"] = 100
        _progress["done"] = _progress.get("total") or TOTAL_BYTES
        log.info("Whisper 模型下载完成: %s", model_dir())
        if callback:
            callback(model_dir())
    except Exception as e:
        _progress["percent"] = -1
        _progress["done"] = 0
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
    """把缓存里的百分比跟目标目录里已经落盘的字节对齐，返回 0~100。没在下返回 -1。

    huggingface_hub 2.x 先把字节下进自己的缓存，进度只出现在它的 tqdm 上
    （「Reconstructing … 41.9MB / 484MB」），目标目录要等整份下完才有文件。
    只扫 model.bin.incomplete 的话，界面会一直停在 0%。字节数由 _note_bytes 从
    那条进度条写进来；扫盘只是旧版本落盘方式的兜底。
    """
    if _progress["percent"] in (-1, 100):
        return _progress["percent"]
    total_on_disk = 0
    try:
        d = model_dir()
        for f in FILES:
            for name in (f, f + ".incomplete"):
                try:
                    total_on_disk += os.path.getsize(os.path.join(d, name))
                except OSError:
                    pass
    except OSError:
        total_on_disk = 0
    if total_on_disk > int(_progress.get("done") or 0):
        _note_bytes(total_on_disk, TOTAL_BYTES)
    return _progress["percent"]
