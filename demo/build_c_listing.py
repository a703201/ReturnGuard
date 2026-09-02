# -*- coding: utf-8 -*-
"""Rebuild GROUP C as a coherent '同款 + 图文承诺' demo:
- product_image = a realistic LISTING image (T-shirt photo + overlaid 承诺文字)
- returned_image = the same clean T-shirt photo
→ similarity stays high (same item) AND OCR extracts the promise from the listing.
"""
import os
from PIL import Image, ImageDraw, ImageFont

UP = os.path.join(os.path.dirname(__file__), "uploads")
TSHIRT = os.path.join(UP, "live_tshirt.png")
OUT = os.path.join(UP, "live_tshirt_listing.png")

FONT = r"C:\Windows\Fonts\msyh.ttc"
try:
    f_t = ImageFont.truetype(FONT, 34)
    f_h = ImageFont.truetype(FONT, 46)
except Exception:
    f_t = ImageFont.load_default()
    f_h = ImageFont.load_default()

W, H = 1080, 1500
canvas = Image.new("RGB", (W, H), (255, 255, 255))
d = ImageDraw.Draw(canvas)

# top: T-shirt photo (resized to fit, centered)
ts = Image.open(TSHIRT).convert("RGB")
ts_ratio = ts.width / ts.height
box_w = 860
box_h = int(box_w / ts_ratio)
ts2 = ts.resize((box_w, box_h))
canvas.paste(ts2, ((W - box_w) // 2, 40))

# bottom: promise block (simulating a real listing's 卖点/承诺文字)
d.line([(60, 40 + box_h + 30), (W - 60, 40 + box_h + 30)], fill=(210, 210, 210), width=2)
title = "Lumio Studio · 纯棉印花 T 恤【官方正品】"
d.text((70, 40 + box_h + 50), title, font=f_h, fill=(20, 20, 20))
promises = [
    "材质：100% 新疆长绒棉 · 亲肤透气",
    "服务：七天无理由退货 · 运费险全覆盖",
    "尺码：S / M / L / XL 标准版型",
    "物流：圆通包邮 · 48 小时发货",
    "认证：OEKO-TEX Standard 100",
    "客服：400-888-1314（9:00-21:00）",
]
y = 40 + box_h + 120
for p in promises:
    d.text((80, y), "· " + p, font=f_t, fill=(60, 60, 60))
    y += 54

canvas.save(OUT, "PNG")
print("[build] ->", OUT, canvas.size)
