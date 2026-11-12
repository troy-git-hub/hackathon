"""Keep Echo visible while excluding its own windows from a capture transaction."""
import ctypes
import sys
from PyQt5.QtCore import Qt


def native_affinity(widget, value=None):
    if sys.platform != "win32" or sys.getwindowsversion().build < 19041:
        return None
    try:
        from ctypes import wintypes
        api = ctypes.WinDLL("user32", use_last_error=True)
        get = api.GetWindowDisplayAffinity
        get.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        get.restype = wintypes.BOOL
        set_ = api.SetWindowDisplayAffinity
        set_.argtypes = [wintypes.HWND, wintypes.DWORD]
        set_.restype = wintypes.BOOL
        hwnd = int(widget.winId())
        current = wintypes.DWORD()
        if not get(hwnd, ctypes.byref(current)):
            return None
        if value is None:
            return current.value
        return current.value if set_(hwnd, value) else None
    except (OSError, AttributeError, ValueError):
        return None


class CaptureExclusion:
    def __init__(self, windows):
        self.excluded, self.hidden = [], []
        self.finished = False
        for widget in dict.fromkeys(w for w in windows if w is not None and w.isVisible()):
            previous = native_affinity(widget, 0x11)
            if previous is not None:
                self.excluded.append((widget, previous))
            else:
                self.hidden.append((widget, widget.testAttribute(Qt.WA_ShowWithoutActivating)))
                widget.hide()

    def restore(self):
        if self.finished:
            return
        self.finished = True
        from PyQt5 import sip
        for widget, affinity in self.excluded:
            if not sip.isdeleted(widget):
                native_affinity(widget, affinity)
        for widget, previous in self.hidden:
            if not sip.isdeleted(widget):
                widget.setAttribute(Qt.WA_ShowWithoutActivating, True)
                widget.show()
                widget.setAttribute(Qt.WA_ShowWithoutActivating, previous)
