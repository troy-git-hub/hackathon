"""
Echo - 用户资料

首次启动时让学生填一次资料（姓名、昵称、年龄、爱好），存成 JSON 文档，
之后每次启动直接读，不再弹登录界面。设置窗口里的「用户：」改的就是这里的 username。

存储位置：config_dir()/profile.json（打包后 %APPDATA%\\Echo，开发时项目根目录）。
卸载重装不会丢；删掉这个文件就会重新弹登录界面。
"""
import json
import os
import shutil
import time

from echo.backend import paths

FIELDS = ("name", "nickname", "age", "hobbies", "username")
# 头像：图片本体单独放配置目录，profile.json 里只记文件名。
# 记绝对路径的话，换台机器（用户名不同）或换个安装位置就指向不存在的文件了。
AVATAR_STEM = "avatar"
AVATAR_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def _path() -> str:
    return os.path.join(paths.config_dir(), "profile.json")


def exists() -> bool:
    """首次登录填过没有。文件损坏也算没填，重新问一遍。"""
    return bool(load())


def load() -> dict:
    """读资料，文件不存在或损坏时返回 {}。"""
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict):
    """写资料（先写临时文件再替换，写一半断电也不会把旧资料弄坏）。

    写失败直接抛 OSError —— 资料必须存下来，调用方要提示学生。
    """
    _update({k: data[k] for k in FIELDS if k in data})


def _update(patch: dict):
    """把 patch 并进 profile.json 并落盘（临时文件 + 原子替换）。

    写失败直接抛 OSError —— 资料必须存下来，调用方要提示学生。
    """
    cur = load()
    cur.update(patch)
    cur.setdefault("created", time.time())
    cur["updated"] = time.time()
    path = _path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def display_name(data: dict = None) -> str:
    """问候时怎么称呼学生：用户名 > 昵称 > 姓名。"""
    data = load() if data is None else data
    for k in ("username", "nickname", "name"):
        v = str(data.get(k) or "").strip()
        if v:
            return v
    return ""


# ================= 头像 =================
def _avatar_files() -> list:
    """配置目录里现存的头像文件。可能有历史遗留的其它扩展名，一起收进来。"""
    out = []
    for ext in AVATAR_EXTS:
        p = os.path.join(paths.config_dir(), AVATAR_STEM + ext)
        if os.path.isfile(p):
            out.append(p)
    return out


def avatar_path() -> str:
    """当前头像的路径；没设过、或文件已经不在了 → 返回 ""（调用方用默认喵喵）。"""
    name = str(load().get("avatar") or "").strip()
    if not name or os.path.basename(name) != name:     # 防御：不接受带路径的名字
        return ""
    p = os.path.join(paths.config_dir(), name)
    return p if os.path.isfile(p) else ""


def set_avatar(src: str) -> str:
    """把选中的图片拷进配置目录当头像，返回存下来的路径；src 传空 = 清除，回到默认喵喵。

    只拷贝、不解码也不缩放：backend 不能引 PyQt5（会把 Qt 拖进后端导入链，踩
    main.py 里记的 ctranslate2 加载顺序坑）。缩放交给 UI 层用 QPixmap 做。
    """
    clear_avatar()
    src = (src or "").strip()
    if not src:
        return ""
    ext = os.path.splitext(src)[1].lower()
    if ext not in AVATAR_EXTS:
        ext = ".png"
    dst = os.path.join(paths.config_dir(), AVATAR_STEM + ext)
    shutil.copyfile(src, dst)
    _update({"avatar": os.path.basename(dst)})
    return dst


def clear_avatar():
    """删掉头像文件，profile 里也不再记（回到默认的喵喵）。"""
    for p in _avatar_files():
        try:
            os.remove(p)
        except OSError:
            pass
    if load().get("avatar"):
        _update({"avatar": ""})
