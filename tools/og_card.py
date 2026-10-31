"""DEBRIS link card for LinkedIn and Open Graph, 1200x627, from the live bundles.

  python tools/og_card.py <fonts dir parent> <repo root> app/static/img/debris_card.png

Needs Pillow and the Montserrat and IBM Plex Mono TTFs in <dir>/fonts/."""
import json, math, sys
from PIL import Image, ImageDraw, ImageFont
S = sys.argv[1]; ROOT = sys.argv[2]; OUT = sys.argv[3]
K = 2; W, H = 1200 * K, 627 * K
BG, CARD, INK, BLUE, FG, MUTED, LINE, SOFT, TINT = "#F8F8F8", "#FFFFFF", "#2A3C78", "#385098", "#1C2238", "#5A6180", "#D6DAE6", "#E3E8F4", "#F0F3FA"
AMBER = "#C8872B"; GHOST = "#C9CEDC"
POLY = {"PS": "#2C8C86", "PE": "#B84C62", "PP": "#4F7CC4", "PET": "#C8872B", "PVC": "#6E5BA6", "PLA": "#7E9B3F", "PA": "#3F8F5A"}
def mont(size, weight):
    f = ImageFont.truetype(f"{S}/fonts/Montserrat.ttf", size * K)
    f.set_variation_by_axes([weight]); return f
mono = lambda size: ImageFont.truetype(f"{S}/fonts/PlexMono.ttf", size * K)
img = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(img)
k = lambda v: int(round(v * K))

# top rule, as the site header
d.rectangle([0, 0, W, k(8)], fill=BLUE)

# --- left: identity
x0 = 64
d.text((k(x0), k(52)), "ELORA THERAPEUTICS", font=mono(15), fill=MUTED, spacing=0)
d.text((k(x0 - 4), k(76)), "DEBRIS", font=mont(112, 800), fill=INK)
# backronym, initials in amber as on the site
y = k(218); x = k(x0)
words = [("D", "isease"), ("E", "vidence"), ("", "from"), ("B", "ioaccumulated"), ("", "plastic"),
         ("R", "esidues:"), ("I", "ndexed"), ("S", "tudies")]
f_b, f_r = mont(21, 800), mont(21, 500)
line_w = k(600)
for init, rest in words:
    w = d.textlength(init, font=f_b) + d.textlength(rest + " ", font=f_r)
    if x + w > k(x0) + line_w:
        x = k(x0); y += k(30)
    if init:
        d.text((x, y), init, font=f_b, fill=AMBER); x += d.textlength(init, font=f_b)
    d.text((x, y), rest, font=f_r, fill=FG); x += d.textlength(rest + " ", font=f_r)
y += k(48)
for line in ["Micro and nanoplastics in human disease:", "a DOI-verified, machine-tagged corpus,", "refreshed weekly."]:
    d.text((k(x0), y), line, font=mont(22, 400), fill=MUTED); y += k(31)

# stat tiles
meta = json.load(open(f"{ROOT}/app/static/data/meta.json"))
stats = [(f"{meta['verified_papers']:,}", "verified papers"), (f"{meta['relevant_papers']:,}", "on topic"),
         (f"{meta['pet_papers']:,}", "PET specific"), (f"{meta['human_papers']:,}", "human evidence")]
tx, ty, tw, th = x0, 470, 146, 82
for i, (v, lab) in enumerate(stats):
    bx = tx + i * (tw + 10)
    d.rectangle([k(bx), k(ty), k(bx + tw), k(ty + th)], fill=CARD, outline=LINE, width=k(1))
    d.rectangle([k(bx), k(ty), k(bx + tw), k(ty + 3)], fill=AMBER if lab == "PET specific" else BLUE)
    d.text((k(bx + 14), k(ty + 14)), v, font=mont(28, 700), fill=INK)
    d.text((k(bx + 14), k(ty + 54)), lab, font=mont(13, 500), fill=MUTED)
d.text((k(x0), k(578)), "debris.mdeller.com", font=mono(17), fill=BLUE)

# --- right: chamfered chart panel, the Rolling year as on the site
px0, py0, px1, py1 = 700, 52, 1140, 578
ch = 22
d.polygon([(k(px0), k(py0)), (k(px1 - ch), k(py0)), (k(px1), k(py0 + ch)), (k(px1), k(py1)), (k(px0), k(py1))],
          fill=CARD, outline=LINE)
d.text((k(px0 + 22), k(py0 + 20)), "CORPUS BY YEAR", font=mont(13, 700), fill=INK)
d.text((k(px0 + 22), k(py0 + 40)), "papers in the past 12 months, by polymer", font=mont(12, 400), fill=MUTED)
trend = [r for r in json.load(open(f"{ROOT}/app/static/data/atlas.json"))["trend"] if r["date"] >= "2016-01"]
n = len(trend)
cx0, cx1 = px0 + 30, px1 - 66
# strip: all papers
sy0, sy1 = py0 + 74, py0 + 170
tot = [r["n"] for r in trend]; tmax = max(tot)
pts = [(k(cx0 + (cx1 - cx0) * i / (n - 1)), k(sy1 - (sy1 - sy0) * v / tmax)) for i, v in enumerate(tot)]
d.polygon(pts + [(k(cx1), k(sy1)), (k(cx0), k(sy1))], fill=SOFT)
d.line(pts, fill=BLUE, width=k(2.4), joint="curve")
d.text((k(cx1 + 8), pts[-1][1] - k(10)), f"{tot[-1]:,}", font=mono(13), fill=BLUE)
d.text((k(cx0), k(sy0 - 4)), "All papers", font=mont(11, 600), fill=MUTED)
# polymers on a log axis
ly0, ly1 = py0 + 200, py1 - 52
lo, hi = math.log10(1), math.log10(1000)
for dec in (1, 10, 100, 1000):
    yy = ly1 - (ly1 - ly0) * (math.log10(dec) - lo) / (hi - lo)
    d.line([(k(cx0), k(yy)), (k(cx1), k(yy))], fill=TINT, width=k(1))
    d.text((k(cx0 - 26), k(yy - 8)), f"{dec:,}" if dec < 1000 else "1k", font=mono(10), fill=MUTED)
order = ["PS", "PE", "PP", "PVC", "PA", "PLA", "PET"]   # PET drawn last, on top
labels = []
for key in order:
    vals = [r["by"].get(key, 0) for r in trend]
    seg, pts = [], []
    for i, v in enumerate(vals):
        if v <= 0:
            if len(pts) > 1: seg.append(pts)
            pts = []; continue
        yy = ly1 - (ly1 - ly0) * (math.log10(v) - lo) / (hi - lo)
        pts.append((k(cx0 + (cx1 - cx0) * i / (n - 1)), k(yy)))
    if len(pts) > 1: seg.append(pts)
    w = 4.2 if key == "PET" else 2.2
    for s_ in seg: d.line(s_, fill=POLY[key], width=k(w), joint="curve")
    if vals[-1] > 0: labels.append([key, seg[-1][-1][1], vals[-1]])
# end labels, nudged apart
labels.sort(key=lambda l: l[1])
for i in range(1, len(labels)):
    if labels[i][1] - labels[i - 1][1] < k(15): labels[i][1] = labels[i - 1][1] + k(15)
for key, yy, v in labels:
    d.text((k(cx1 + 8), yy - k(8)), key, font=mont(12, 800 if key == "PET" else 600), fill=POLY[key])
# years
for yr in (2016, 2018, 2020, 2022, 2024, 2026):
    i = next((j for j, r in enumerate(trend) if r["date"].startswith(str(yr))), None)
    if i is None: continue
    xx = cx0 + (cx1 - cx0) * i / (n - 1)
    d.text((k(xx - 14), k(ly1 + 10)), str(yr), font=mono(11), fill=MUTED)

img = img.resize((1200, 627), Image.LANCZOS)
img.save(OUT, optimize=True)
print(OUT)
