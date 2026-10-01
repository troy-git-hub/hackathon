"""
把 assets/cat_emojis.jpg/png（2列 x 4行 = 8张表情包）切成 8 张独立透明 PNG。
输出到 assets/emojis/ 目录。
"""
import os
from PIL import Image

SRC_CANDIDATES = [
    os.path.join("assets", "cat_emojis.jpg"),
    os.path.join("assets", "cat_emojis.png"),
]
OUT_DIR = os.path.join("assets", "emojis")
COLS, ROWS = 2, 4

NAMES = ["cry", "smug", "confused", "stare",
         "shock", "key", "cow", "happy"]


def make_transparent(img):
    """把灰色菱格背景变透明。
    判定：RGB 三通道差异小（灰色）且亮度在 90~200 之间。
    """
    img = img.convert("RGBA")
    pixels = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            # 灰色判定：三通道接近
            if abs(r - g) < 25 and abs(g - b) < 25 and abs(r - b) < 25:
                # 亮度在背景灰范围内
                if 90 <= r <= 205:
                    pixels[x, y] = (r, g, b, 0)
    return img


def main():
    src = None
    for c in SRC_CANDIDATES:
        if os.path.exists(c):
            src = c
            break

    if src is None:
        print(f"[ERROR] 找不到表情包图，请放到 assets/cat_emojis.jpg 或 .png")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    img = Image.open(src)
    w, h = img.size
    cell_w, cell_h = w // COLS, h // ROWS

    idx = 0
    for r in range(ROWS):
        for c in range(COLS):
            box = (c * cell_w, r * cell_h, (c + 1) * cell_w, (r + 1) * cell_h)
            cell = img.crop(box)
            cell = make_transparent(cell)
            out = os.path.join(OUT_DIR, f"{NAMES[idx]}.png")
            cell.save(out)
            print(f"saved {out}")
            idx += 1

    print(f"\n切分完成，共 {idx} 张，输出到 {OUT_DIR}/")


if __name__ == "__main__":
    main()
