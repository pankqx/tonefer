"""Draws build/tonefer.ico (multi-size) for the Windows app and installer."""
from pathlib import Path
from PIL import Image, ImageDraw

out = Path(__file__).resolve().parents[2] / "build"
out.mkdir(exist_ok=True)
S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.ellipse((8, 8, S - 8, S - 8), fill=(39, 149, 149, 255))
c = (247, 246, 244, 255)
d.line((64, 96, 182, 96), fill=c, width=18)
d.polygon([(160, 66), (198, 96), (160, 126)], fill=c)
d.line((74, 160, 192, 160), fill=c, width=18)
d.polygon([(96, 130), (58, 160), (96, 190)], fill=c)
img.save(out / "tonefer.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(out / "tonefer.ico")
