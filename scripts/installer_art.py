"""Render Echo's own vector-like installation artwork; no third-party artwork."""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
S = 2
W, H = 330, 560
image = Image.new("RGB", (W*S, H*S))
pixels = image.load()
for y in range(H*S):
    for x in range(W*S):
        glow = max(0, 1-math.hypot(x/S-190, y/S-320)/240)
        t = y/(H*S)
        pixels[x,y] = (int(15-4*t+6*glow), int(38-16*t+17*glow), int(39-12*t+13*glow))
d = ImageDraw.Draw(image)
def line(points, fill, width=1):
    d.line([(int(x*S),int(y*S)) for x,y in points], fill=fill, width=width*S, joint="curve")
def text(position, value, size, color, bold=False):
    font_path = Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc")
    face = ImageFont.truetype(str(font_path), size*S)
    d.text((position[0]*S,position[1]*S), value, font=face, fill=color, spacing=9*S)
for j in range(5):
    line([(x, 345 + j*19 + 15*math.sin(x/52+j*.6)) for x in range(-20,W+20)], "#244A49")
for radius in (88,115,143):
    d.arc(((168-radius)*S,(334-radius*.68)*S,(168+radius)*S,(334+radius*.68)*S), 196, 350, fill="#305854", width=S)
text((29,31), "ECHO / STUDY COMPANION", 10, "#92B6AD")
text((27,66), "Echo", 47, "#D9F6E7", True)
text((29,143), "把这节课，\n听进心里。", 25, "#F4F3E9", True)
# An open notebook and Echo's signature listening cat.
d.rounded_rectangle((63*S,265*S,267*S,408*S), 20*S, fill="#173C39", outline="#3B6A5D", width=S)
line([(164,279),(164,391)], "#42685B")
for yy in (294,310,326):
    line([(79,yy),(139,yy)], "#6B8D78")
line([(184,299),(201,286),(232,308),(246,290)], "#A9DDBD", 2)
cat = [(111,338),(105,282),(143,305),(177,305),(215,282),(208,338)]
line(cat, "#B7EDCE", 4)
d.arc((109*S,307*S,210*S,397*S), 0, 180, fill="#B7EDCE", width=4*S)
d.arc((127*S,324*S,147*S,342*S), 188, 350, fill="#B7EDCE", width=3*S)
d.arc((171*S,324*S,191*S,342*S), 188, 350, fill="#B7EDCE", width=3*S)
line([(151,352),(159,359),(168,352)], "#B7EDCE", 3)
d.ellipse((234*S,242*S,262*S,270*S), fill="#F3BB63")
for xx, height in ((234,8),(241,15),(248,19),(255,11)):
    line([(xx,431-height/2),(xx,431+height/2)], "#A9DDBD", 2)
text((29,440), "听见  /  理解  /  留下回响", 11, "#92B6AD")
text((29,530), "MADE FOR YOUR NEXT AHA.", 8, "#678A80")
target = ROOT / "installer/assets/setup-brand.bmp"
target.parent.mkdir(parents=True, exist_ok=True)
image.save(target)
print(target)
