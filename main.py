"""
Echo - 入口
网课里的 AI 学习副驾驶。
"""
import sys
import os

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# !!! 必须在 import PyQt5 之前预加载 Whisper 模型 !!!
# PyQt5 与 ctranslate2 的 native 库加载顺序冲突：先 import PyQt5 再加载 WhisperModel 会访问违例
# 必须在主线程、QApplication 创建之前、且未 import 任何 PyQt5 模块时加载
def _preload_whisper():
    """在 import PyQt5 之前预加载 Whisper，避开 native 库冲突。
    把模型存到 WhisperASR._model，避免 _startup 再加载一次（双倍内存会导致 mkl_malloc 失败）。
    """
    try:
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        from echo.backend import config
        from echo.backend.sources import _WhisperWorker
        from faster_whisper import WhisperModel
        _WhisperWorker._model = WhisperModel(
            config.whisper_model_path(), device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE,
            cpu_threads=min(config.WHISPER_THREADS, os.cpu_count() or 1),
            local_files_only=True)
        print(f"[Echo] Whisper 预加载完成: {config.WHISPER_MODEL}")
    except Exception as e:
        print(f"[Echo] Whisper 预加载失败（将在后台重试）: {e}")

# 在 import PyQt5 之前执行预加载
_preload_whisper()

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from echo.theme import apply_theme
from echo.widgets.floating_window import FloatingWindow
from echo.widgets.tray import EchoTray
from echo.widgets.desk_pet import DeskPet
from echo.widgets.profile_setup import ensure_profile


def main():
    # 高分屏（如 2880x1800 @200%）按系统缩放渲染，否则整个界面只有一半大
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    if hasattr(QApplication, "setHighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    apply_theme(app)

    # 把界面语言告诉后端：AI 的回答跟着界面语言走。
    # 后端自己不能 import echo.i18n（它依赖 QSettings，会把 PyQt5 拖进后端导入链，
    # 踩上面那条 ctranslate2/PyQt5 加载顺序的坑），所以在这里单向写一次。
    from echo import i18n
    from echo.backend import config as backend_config
    backend_config.set_ui_lang(i18n.lang())

    # 第一次打开先填资料（存成 profile.json，以后启动直接读）；关掉不填就不启动
    if not ensure_profile():
        sys.exit(0)

    win = FloatingWindow()
    # 定位到屏幕中央
    screen = app.primaryScreen().availableGeometry()
    win.move(screen.center().x() - win.width() // 2,
             screen.center().y() - win.height() // 2)
    win.show()

    # 语音识别模型不再随安装包分发（483MB 的大头），改成按需下载。启动就开始下 ——
    # 等到第一次开课才下就太晚了。不阻塞：窗口已经出来了，进度显示在状态栏。
    try:
        from echo.backend import model_fetch
        model_fetch.ensure()
    except Exception as e:
        print(f"[Echo] 触发模型下载失败（不影响使用）: {e}")

    tray = EchoTray(app, win)   # 托盘 + 关闭到托盘 + 全局快捷键（Ctrl+Alt+L 掉队 / Ctrl+Alt+E 显示隐藏 / Ctrl+Alt+Q 圈一下问 AI）

    pet = DeskPet(win, tray)    # 桌宠：跟着课堂变表情，双击圈一下问 AI
    pet.circle_ask.connect(tray.circle_ask)
    tray.pet = pet
    pet.place_default()
    pet.show()
    wire_pet_checkin(win, pet)

    sys.exit(app.exec_())


def wire_pet_checkin(win, pet):
    """课堂抽问（课上突然被问一道）时让桌宠喊一声。

    学生正低头听课、或者面板收起来了，不提醒根本不知道有人在问他。
    窗口不在面前时再亮个红点，点一下桌宠就能把窗口调出来答题。
    """
    if not hasattr(win.echo, "checkin"):
        return

    def on_checkin(q):
        topic = (q or {}).get("topic") or ""
        who = f"「{topic}」" if topic else "刚讲的内容"
        pet.say(f"老师刚讲的{who}还记得吗？点我答一道～", 12000, "alert", 4000)
        if not win.isVisible():
            pet.badge = True

    def on_result(_record):
        pet.badge = False           # 答完了，红点收掉

    win.echo.checkin.connect(on_checkin)
    win.echo.checkin_result.connect(on_result)


if __name__ == "__main__":
    main()
