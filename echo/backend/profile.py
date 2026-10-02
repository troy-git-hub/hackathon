"""
Echo - 用户资料

首次启动时让学生填一次资料（姓名、昵称、年龄、爱好），存成 JSON 文档，
之后每次启动直接读，不再弹登录界面。设置窗口里的「用户：」改的就是这里的 username。

存储位置：config_dir()/profile.json（打包后 %APPDATA%\\Echo，开发时项目根目录）。
卸载重装不会丢；删掉这个文件就会重新弹登录界面。
"""
import json
import os
import time

from echo.backend import paths

FIELDS = ("name", "nickname", "age", "hobbies", "username")


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
    cur = load()
    cur.update({k: data[k] for k in FIELDS if k in data})
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
