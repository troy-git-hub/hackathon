"""
Echo - 桌宠提醒课堂抽问的自检

    python scripts/pet_checkin_check.py

课上突然被抽问，学生低头听课根本不知道 —— 桌宠得喊一声。这里验的就是
main.wire_pet_checkin 那段接线：信号接对了、话说了、窗口不在面前时亮红点。

用真的 DeskPet（win=None 建一个），只把 win 换成假的 —— 不然要拉起整个主窗口。

退出码：全部通过为 0。
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ECHO_OFFLINE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# main 在 import 时就会预加载 Whisper 模型（几百兆），自检不需要：给个假模块让它快速失败
sys.modules.setdefault("faster_whisper", types.ModuleType("faster_whisper"))

from PyQt5.QtCore import QObject, pyqtSignal        # noqa: E402
from PyQt5.QtWidgets import QApplication            # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(f"  {'通过' if cond else '失败'}  {name}" + (f"  —— {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


app = QApplication.instance() or QApplication(sys.argv)
from echo.theme import apply_theme                  # noqa: E402
apply_theme(app)

import main as app_main                             # noqa: E402
from echo.widgets.desk_pet import DeskPet           # noqa: E402


class FakeBridge(QObject):
    """真的 FloatingWindow 里这两个信号挂在 win.echo（bridge）上。"""

    checkin = pyqtSignal(object)
    checkin_result = pyqtSignal(object)


class FakeWin(QObject):
    """只带 main.wire_pet_checkin 用得到的东西：echo + isVisible。"""

    def __init__(self):
        super().__init__()
        self.echo = FakeBridge()
        self.visible = False

    def isVisible(self):
        return self.visible


print("A. 桌宠本身有 say / badge 这两个口子")
pet = DeskPet(win=None, tray=None)
check("有 say()", callable(getattr(pet, "say", None)))
check("有 badge 标记", isinstance(getattr(pet, "badge", None), bool))

said = []
pet.say = lambda text, ms=4000, mood=None, hold_ms=None: said.append((text, ms, mood))

print("\nB. 抽问来了 → 桌宠喊一声")
win = FakeWin()
app_main.wire_pet_checkin(win, pet)
win.echo.checkin.emit({"topic": "条件概率定义", "question": "P(A|B) 是什么？"})
app.processEvents()
check("桌宠说话了", len(said) == 1, f"说了 {len(said)} 次")
check("话里带上被问的知识点", bool(said) and "条件概率定义" in said[0][0],
      said[0][0] if said else "")
check("用 alert 语气（会晃一下，学生才注意得到）", bool(said) and said[0][2] == "alert")
check("窗口不在面前 → 亮红点", pet.badge is True)

print("\nC. 答完 → 红点收掉")
win.echo.checkin_result.emit({"result": "right"})
app.processEvents()
check("红点清掉", pet.badge is False)
check("不再多说一句（学生已经在看题了）", len(said) == 1, f"说了 {len(said)} 次")

print("\nD. 没听清知识点也要能喊")
said.clear()
win.echo.checkin.emit({})
app.processEvents()
check("照样说话", len(said) == 1)
check("不出现空括号", bool(said) and "「」" not in said[0][0], said[0][0] if said else "")
win.echo.checkin_result.emit({})

print("\nE. 窗口就在眼前 → 不亮红点")
win.visible = True
win.echo.checkin.emit({"topic": "贝叶斯公式"})
app.processEvents()
check("还是说话", len(said) == 2)
check("不亮红点（人正看着窗口）", pet.badge is False)

print("\nF. 没有抽问信号的老 bridge 不能炸")
class OldWin(QObject):
    """老版本的 bridge 上还没有 checkin 信号。"""

    def __init__(self):
        super().__init__()
        self.echo = QObject()

    def isVisible(self):
        return True


try:
    app_main.wire_pet_checkin(OldWin(), pet)
    check("没有 checkin 信号时安静跳过", True)
except Exception as e:
    check("没有 checkin 信号时安静跳过", False, f"{type(e).__name__}: {e}")

pet.close()
print("\n" + "=" * 56)
if FAILED:
    print(f"失败 {len(FAILED)} 项：" + "、".join(FAILED))
    sys.exit(1)
print("桌宠提醒自检：全部通过")
