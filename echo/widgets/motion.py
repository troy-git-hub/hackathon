"""通用 UI 动效：开关设置 + 几个安全的动画助手。

开关记在 QSettings("Echo","Echo") 的 "ui_motion"：system / on / off，默认 system。
system 跟随 Windows「在 Windows 中显示动画」(SPI_GETCLIENTAREAANIMATION)——
用户在系统里关了动画，Echo 也不动。

所有助手在动效关闭时零操作直通；异常一律吞掉并保证控件最终处于
可见/不透明状态，动画永远不能把界面卡在半透明或错位上。
"""
import ctypes
import os

from PyQt5.QtCore import (QAbstractAnimation, QEasingCurve, QPropertyAnimation,
                          QRect, QSettings, QTimer)
from PyQt5.QtWidgets import QApplication, QGraphicsOpacityEffect, QWidget

SPI_GETCLIENTAREAANIMATION = 0x1042
DURATION = 120             # ms；短促到不挡操作（再长就开始感觉「卡」了）
DURATION_PAGE = 110        # 页面切换，再短一点免得叠着点击


def mode():
    return QSettings("Echo", "Echo").value("ui_motion", "system")


def set_mode(value):
    QSettings("Echo", "Echo").setValue("ui_motion", value if value in ("system", "on", "off") else "system")


def system_allows_animation():
    """Windows 的客户端区域动画开关（设置 → 辅助功能 → 视觉效果）。"""
    if os.name != "nt":
        return True
    try:
        from ctypes import wintypes
        value = wintypes.BOOL()
        if ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0,
                                                      ctypes.byref(value), 0):
            return bool(value.value)
    except Exception:
        pass
    return True


def enabled():
    # 验收/自检脚本（还有 CI、无头跑测）设这个变量：动画全部直通，
    # 截图不会停在半透明那一帧。
    if os.environ.get("ECHO_DISABLE_MOTION"):
        return False
    m = mode()
    if m == "on":
        return True
    if m == "off":
        return False
    return system_allows_animation()


def _alive(widget):
    try:
        from PyQt5.QtCore import QCoreApplication
        return widget is not None and QCoreApplication.instance() is not None
    except Exception:
        return False


def fade_window(window, duration=DURATION):
    """顶层窗口淡入。必须在 show() 之后立刻调用；只动 windowOpacity，
    不套 QGraphicsOpacityEffect——套上去会让 WebEngine / 蒙版圆角一起糊掉。"""
    try:
        if not _alive(window) or not window.isWindow():
            return
        if not enabled():
            window.setWindowOpacity(1.0)
            return
        window.setWindowOpacity(0.0)
        anim = QPropertyAnimation(window, b"windowOpacity", window)
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: window.setWindowOpacity(1.0))
        anim.start(QAbstractAnimation.DeleteWhenStopped)
    except Exception:
        try:
            window.setWindowOpacity(1.0)
        except Exception:
            pass


_NO_EFFECT_CLASSES = ("QWebEngineView",)          # 套透明度效果会白屏/闪烁


def _has_webengine(widget):
    """子树里有没有 WebEngine。透明度效果罩不住它（单独合成层），反而会闪。"""
    try:
        for child in widget.findChildren(QWidget):
            if child.metaObject().className() in _NO_EFFECT_CLASSES:
                return True
    except Exception:
        pass
    return False


def fade_widget(widget, duration=DURATION_PAGE, slide=0):
    """内嵌控件淡入（页面切换、展开面板），可选「从下方滑入到位」——
    SwiftUI 那种又淡又微微上浮的入场。结束后摘掉效果，不长期背着渲染开销。"""
    try:
        if not _alive(widget) or not widget.isVisible():
            return
        if widget.metaObject().className() in _NO_EFFECT_CLASSES or hasattr(widget, "page"):
            return
        if _has_webengine(widget):
            return
        if not enabled():
            return
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)

        def _cleanup():
            try:
                if _alive(widget):
                    widget.setGraphicsEffect(None)   # setGraphicsEffect 会接管并销毁旧效果
            except Exception:
                pass

        anim = QPropertyAnimation(effect, b"opacity", effect)
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(_cleanup)

        def _start():
            try:
                if not _alive(widget):
                    return
                if slide:
                    # 从下方 slide 像素滑到布局本来的位置；布局激活会把坐标
                    # 拉回去，所以真正的目标位置以动画启动那一刻为准。
                    target = widget.pos()
                    widget.move(target.x(), target.y() + slide)
                    gliding = QPropertyAnimation(widget, b"pos", widget)
                    gliding.setDuration(duration)
                    gliding.setStartValue(widget.pos())
                    gliding.setEndValue(target)
                    gliding.setEasingCurve(QEasingCurve.OutCubic)
                    gliding.start(QAbstractAnimation.DeleteWhenStopped)
                anim.start(QAbstractAnimation.DeleteWhenStopped)
            except Exception:
                _cleanup()

        QTimer.singleShot(0, _start)                 # 等布局画完第一帧再动
    except Exception:
        try:
            widget.setGraphicsEffect(None)
        except Exception:
            pass


def reveal(widget, slide=8):
    """展开某个被 setVisible(True) 的面板时调用：淡入 + 微微上浮。"""
    fade_widget(widget, DURATION, slide=slide)


def glide_window(window, target, restore_min=None, duration=170):
    """顶层窗口位置/尺寸平滑过渡（折叠成条、从条展开）。SwiftUI 弹簧感的近似：
    OutCubic 先快后缓。restore_min 是动画结束后要钉回的 (最小宽, 最小高)——
    动画期间得把最小尺寸放宽到比起点还小，否则 setGeometry 会被 min 钳住直接跳到位。
    返回 True 表示动画已启动；False 表示没启动（调用方退回硬设）。"""
    try:
        if not _alive(window) or not window.isWindow():
            return False
        if not enabled():
            return False
        end = target if isinstance(target, QRect) else QRect(*target)
        if window.geometry() == end:
            return False
        anim = QPropertyAnimation(window, b"geometry", window)
        anim.setDuration(duration)
        anim.setStartValue(window.geometry())
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        if restore_min is not None:
            def _restore():
                try:
                    if _alive(window):
                        window.setMinimumSize(restore_min[0], restore_min[1])
                except Exception:
                    pass
            anim.finished.connect(_restore)
        anim.start(QAbstractAnimation.DeleteWhenStopped)
        return True
    except Exception:
        return False
