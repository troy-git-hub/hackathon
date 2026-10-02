"""
Echo - 头像

圆形头像控件：设过自定义头像就显示它，没设过就显示默认的喵喵
（跟主窗口右上角用的是同一张 assets/emojis/smug.png）。

学生的照片多半不是正方形、尺寸也乱：统一按「短边居中裁成正方形 → 缩放 →
圆形裁剪」处理，不然会被拉扁。
"""
import os

from PyQt5.QtCore import Qt, QRectF, QSize, pyqtSignal
from PyQt5.QtGui import QColor, QImageReader, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QWidget

from echo.backend import paths, profile
from echo.theme import Colors

# 默认头像：主窗口右上角那张喵喵
DEFAULT_FILE = "smug.png"


def default_pixmap() -> QPixmap:
    """默认的喵喵头像；图缺失时返回空 QPixmap（调用方画个占位圆）。"""
    return QPixmap(paths.asset("assets", "emojis", DEFAULT_FILE))


def load_normalized(path: str, max_side: int = 512) -> QPixmap:
    """读一张图并规范化：应用 EXIF 旋转、长边缩到 max_side 以内。读不了返回空 QPixmap。

    两件事都不能省：
    · 手机竖着拍的照片在 EXIF 里记了旋转，直接 QPixmap(path) 载入会躺着；
    · 原图动辄 4000×3000，先按目标尺寸解码，省得为了一个 72px 的头像解出 48MB 位图。
    存进配置目录的也是这张规范化后的图，用户的原图删了、挪了都不影响。
    """
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > max_side:
        scale = max_side / float(max(size.width(), size.height()))
        reader.setScaledSize(QSize(max(1, int(size.width() * scale)),
                                   max(1, int(size.height() * scale))))
    img = reader.read()
    return QPixmap.fromImage(img) if not img.isNull() else QPixmap()


def _circle(pm: QPixmap, size: int) -> QPixmap:
    """把任意尺寸的图裁成 size×size 的圆。"""
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    if pm.isNull():
        return out
    p = QPainter(out)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    path.addEllipse(QRectF(0, 0, size, size))
    p.setClipPath(path)
    side = min(pm.width(), pm.height())          # 短边居中裁正方形，不变形
    src = QRectF((pm.width() - side) / 2.0, (pm.height() - side) / 2.0, side, side)
    p.drawPixmap(QRectF(0, 0, size, size), pm, src)
    p.end()
    return out


def avatar_pixmap(size: int, dpr: float = 1.0) -> QPixmap:
    """当前头像裁成圆形；自定义的没有/坏了就退回默认喵喵。

    dpr 用于高分屏：按物理像素渲染再缩回逻辑尺寸，不然会糊。
    """
    px = max(1, int(round(size * (dpr or 1.0))))
    path = ""
    try:
        path = profile.avatar_path()
    except Exception:
        path = ""
    pm = load_normalized(path, max_side=max(256, px * 2)) if path else QPixmap()
    if pm.isNull():
        pm = default_pixmap()
    out = _circle(pm, px)
    out.setDevicePixelRatio(dpr or 1.0)
    return out


class AvatarView(QWidget):
    """圆形头像，点一下可以触发事情（比如打开资料页）。"""

    clicked = pyqtSignal()

    def __init__(self, size: int = 72, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self._pm = QPixmap()
        self.refresh()

    def refresh(self):
        """重新读一遍头像（换过图之后调）。"""
        self._pm = avatar_pixmap(self._size, self.devicePixelRatioF())
        self.update()

    def set_pixmap(self, pm: QPixmap):
        """直接显示一张图（首次登录窗里做预览用，那时还没落盘）。"""
        if pm is None or pm.isNull():
            pm = default_pixmap()
        self._pm = _circle(pm, max(1, int(self._size * self.devicePixelRatioF())))
        self._pm.setDevicePixelRatio(self.devicePixelRatioF())
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self._size, self._size)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(Colors.SURFACE_HOVER))
        if self._pm.isNull():                    # 连默认图都缺：画个圆底，别留空白
            p.drawEllipse(r)
        else:
            p.drawPixmap(0, 0, self._pm)
        p.setBrush(Qt.NoBrush)
        # 必须包成 QColor：直接把 '#RRGGBB' 字符串喂给 setPen 会段错误（不是抛异常）
        p.setPen(QPen(QColor(Colors.BORDER_STRONG), 1))
        p.drawEllipse(r.adjusted(0.5, 0.5, -0.5, -0.5))
        p.end()
