"""
Echo - 运行路径

开发时所有路径相对项目根目录；用 PyInstaller 打成 exe 后：

  · 随程序附带的只读资源（assets/、.env.example）在 sys._MEIPASS 下
  · 可写的配置（.env）放在 %APPDATA%\\Echo，不能放安装目录
    —— 装在 C:\\Program Files 时那里需要管理员权限，设置窗口会保存失败

首次运行会把 .env.example 复制成 %APPDATA%\\Echo\\.env，让设置窗口有文件可写。
"""
import os
import shutil
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """exe 所在目录（打包后）或项目根目录（开发时）。"""
    return os.path.dirname(sys.executable) if is_frozen() else PROJECT_ROOT


def bundle_dir() -> str:
    """随程序分发的只读资源目录。PyInstaller 的 _MEIPASS；开发时=项目根目录。"""
    return getattr(sys, "_MEIPASS", PROJECT_ROOT)


def config_dir() -> str:
    """放 .env 的可写目录：打包后 %APPDATA%\\Echo，开发时项目根目录。"""
    if not is_frozen():
        return PROJECT_ROOT
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "Echo")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return base
    return path


def env_path() -> str:
    return os.path.join(config_dir(), ".env")


def example_env() -> str:
    """.env.example：打包后在 _MEIPASS 里，开发时在项目根目录。"""
    return os.path.join(bundle_dir(), ".env.example")


def asset(*parts) -> str:
    """打包资源路径，例如 asset("assets", "emojis", "smug.png")。"""
    return os.path.join(bundle_dir(), *parts)


def ensure_env() -> str:
    """保证有一个可写的 .env；没有就按 .env.example 建一个（不覆盖已有文件）。"""
    target = env_path()
    if os.path.exists(target):
        return target
    src = example_env()
    try:
        if os.path.exists(src):
            shutil.copyfile(src, target)
        else:
            with open(target, "w", encoding="utf-8") as f:
                f.write("DEEPSEEK_API_KEY=\nECHO_SOURCE=system\n")
    except OSError:
        return target
    return target
