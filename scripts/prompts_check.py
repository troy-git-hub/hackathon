"""
提示词模板自检：所有 *_SYSTEM 模板都不能把没被替换的大括号漏给模型。

    python scripts/prompts_check.py

为什么值得单独一个脚本：`prompts.system(name)` 只在**传了 fmt 时**才调 .format()，
所以不带参数的模板大括号要写单的、带参数的要写双的。这个区别肉眼很容易看漏——
已经真出过一次事故：`CHECKIN_SYSTEM` 从不带参数，却写成了双括号，于是发给模型的
JSON 示例一直是 `{{"topic": ...}}` 这种坏格式，模型的输出质量被悄悄拉低，
而且不报错、测试也全绿，靠人工看是发现不了的。

所以这里不逐个列举模板名，而是**把所有 *_SYSTEM 模板扫一遍**：以后新加的模板
自动被覆盖，不用记得来改这个文件。
"""
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echo.backend import config, prompts          # noqa: E402

_fail = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  —— {detail}" if detail and not ok else ""),
          flush=True)
    if not ok:
        _fail.append(name)


def templates():
    """prompts 模块里所有的 *_SYSTEM 模板。"""
    out = []
    for name in dir(prompts):
        if not name.endswith("_SYSTEM") or not name.isupper():
            continue
        val = getattr(prompts, name)
        if isinstance(val, str):
            out.append((name, val))
    return sorted(out)


def fields_of(tmpl: str):
    """模板里真正要替换的占位名（`{n}` → n）。

    **只认合法标识符**：JSON 示例里的 `{"topic": ...}` 也会被 Formatter 解析出一个
    字段名（`"topic"`，带引号），那是个字面量不是占位符。分不清的话，会把「本来
    就不带参数的模板」误判成带参数、硬去 .format()，报一个假 KeyError。
    """
    return {f for _lit, f, _spec, _conv in string.Formatter().parse(tmpl)
            if f and f.isidentifier()}


found = templates()
check("扫到了提示词模板", len(found) >= 6, f"只扫到 {len(found)} 个：{[n for n, _ in found]}")
print(f"      （共 {len(found)} 个：{', '.join(n for n, _ in found)}）")

for name, tmpl in found:
    need = fields_of(tmpl)
    kw = {f: 3 for f in need}          # 占位值，够跑通就行
    for lang in ("zh", "en"):
        config.set_ui_lang(lang)
        try:
            out = prompts.system(name, **kw)
        except Exception as e:
            check(f"{name} [{lang}] 取模板不报错", False, f"{type(e).__name__}: {e}")
            continue
        # 1) 不能把没转义的大括号漏出去 —— 就是 CHECKIN_SYSTEM 那次的病
        leftover = [tok for tok in ("{{", "}}") if tok in out]
        check(f"{name} [{lang}] 没有漏出双层大括号", not leftover,
              f"输出里出现了 {leftover}（不带参数的模板要用单括号，带的要用双括号）")
        # 2) 占位符都得被替换掉，不能把 {n} 原样发给模型
        unreplaced = [f"{{{f}}}" for f in need if f"{{{f}}}" in out]
        check(f"{name} [{lang}] 占位符都替换了", not unreplaced, f"残留 {unreplaced}")
        # 3) 英文界面要带上「用英文输出」的指令
        want_en = lang == "en"
        has_en = "Output language" in out
        check(f"{name} [{lang}] 语言指令正确", has_en == want_en,
              f"en 模式下{'没' if want_en else '不该'}追加英文输出指令")

config.set_ui_lang("zh")

if _fail:
    print(f"\n提示词模板自检：{len(_fail)} 项失败")
    sys.exit(1)
print("\n提示词模板自检：全部通过")
