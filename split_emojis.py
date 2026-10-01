"""
把 assets/cat_emojis.png（2列 x 4行 = 8张表情包）切成 8 张独立 PNG。
输出到 assets/emojis/ 目录。
"""
import os
from PIL import Image

SRC = os.path.join("assets", "cat_emojis.png")
OUT_DIR = os.path.join("assets", "emojis")
COLS, ROWS = 2, 4


def main():
    if not os.path.exists(SRC):
        print(f"[ERROR] 找不到 {SRC}，请把表情包大图放到 assets/cat_emojis.png")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    img = Image.open(SRC).convert("RGBA")
    w, h = img.size
    cell_w, cell_h = w // COLS, h // ROWS

    names = ["cry", "smug", "confused", "stare",
             "shock", "key", "cow", "happy"]

    idx = 0
    for r in range(ROWS):
        for c in range(COLS):
            box = (c * cell_w, r * cell_h, (c + 1) * cell_w, (r + 1) * cell_h)
            cell = img.crop(box)
            # 裁掉边缘灰色背景，保留透明
            out = os.path.join(OUT_DIR, f"{names[idx]}.png")
            cell.save(out)
            print(f"saved {out}")
            idx += 1

    print(f"\n切分完成，共 {idx} 张，输出到 {OUT_DIR}/")


if __name__ == "__main__":
    main()
