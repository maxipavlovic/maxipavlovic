#!/usr/bin/env python3
"""Draws the profile sheets in assets/ from build/data.json.

    python build/build.py            # redraw from data.json
    python build/build.py --fetch    # refresh the numbers first (PyPI, crates.io)

Every sheet is written twice, light and dark; README.md picks one with <picture>.
Fonts are subset per sheet and embedded, so the SVGs look the same in every browser.
"""
import argparse
import base64
import datetime
import io
import json
import math
import urllib.request
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "build" / "fonts"
ASSETS = ROOT / "assets"
DATA = ROOT / "build" / "data.json"

THEMES = {
    "light": dict(paper="#ecebe7", ink="#0e0e0d", ink2="#57564f",
                  rule="#0e0e0d", rule2="#bdbcb5", sig="#f0561a", sigink="#b23d08"),
    "dark": dict(paper="#0b0b0a", ink="#ecebe6", ink2="#aaa8a0",
                 rule="#d9d8d2", rule2="#55544e", sig="#ff6a2b", sigink="#ff8a55"),
}

FACES = {
    "disp": ("Archivo[wdth,wght].ttf", {"wdth": 125, "wght": 100}),
    "text": ("Inter[opsz,wght].ttf", {"opsz": 14, "wght": 400}),
    "bold": ("Inter[opsz,wght].ttf", {"opsz": 14, "wght": 600}),
    "mono": ("MartianMono[wdth,wght].ttf", {"wdth": 100, "wght": 400}),
}


# ---------------------------------------------------------------- fonts

class Face:
    def __init__(self, key):
        file, loc = FACES[key]
        var = TTFont(FONTS / file, recalcTimestamp=False)
        self.font = instancer.instantiateVariableFont(var, loc)
        self.cmap = self.font.getBestCmap()
        self.hmtx = self.font["hmtx"]
        self.upm = self.font["head"].unitsPerEm
        self.key = key

    def width(self, s, size, ls=0.0):
        adv = sum(self.hmtx[self.cmap.get(ord(c), ".notdef")][0] for c in s)
        return adv / self.upm * size + ls * size * len(s)

    def woff2(self, chars):
        buf = io.BytesIO()
        self.font.recalcTimestamp = False
        self.font.save(buf)
        buf.seek(0)
        font = TTFont(buf, recalcTimestamp=False)
        opts = subset.Options()
        opts.layout_features = ["kern"]
        opts.name_IDs = [1, 2]
        opts.hinting = False
        opts.desubroutinize = True
        opts.notdef_outline = True
        sub = subset.Subsetter(opts)
        sub.populate(text="".join(sorted(chars)))
        sub.subset(font)
        font.flavor = "woff2"
        out = io.BytesIO()
        font.save(out)
        return out.getvalue()


FACE = {}


def face(key):
    if key not in FACE:
        FACE[key] = Face(key)
    return FACE[key]


def width(s, key, size, ls=0.0):
    return face(key).width(s, size, ls)


# ---------------------------------------------------------------- sheets

CSS = """
.paper{fill:var(--paper)}
.ink{fill:var(--ink)}.ink2{fill:var(--ink2)}.sig{fill:var(--sig)}.sigink{fill:var(--sigink)}
.h,.h2{fill:none;stroke-width:var(--hw);vector-effect:non-scaling-stroke}
.h{stroke:var(--rule)}.h2{stroke:var(--rule2)}
.c{shape-rendering:crispEdges}
.cl{stroke-dasharray:18 3 2 3}
.f-disp{font-family:F-disp}.f-text{font-family:F-text}
.f-bold{font-family:F-bold}.f-mono{font-family:F-mono}
text{font-kerning:normal}
@media (min-resolution:2dppx){svg{--hw:.5}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes draw{from{stroke-dasharray:1;stroke-dashoffset:1}to{stroke-dasharray:1;stroke-dashoffset:0}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.2}}
@keyframes rise{from{opacity:0;transform:translateY(6px)}}
.spin{animation:spin 160s linear infinite}
.draw{animation:draw 1.6s cubic-bezier(.6,0,.2,1) backwards}
.pulse{animation:pulse 2.4s ease-in-out infinite}
.rise{animation:rise .9s cubic-bezier(.2,.7,.2,1) backwards}
@media (prefers-reduced-motion:reduce){.spin,.pulse,.draw,.rise{animation:none}}
"""


class Sheet:
    def __init__(self, name, w, h, title, paper=True, margin=(0, 0)):
        self.name, self.w, self.h, self.title = name, w, h, title
        self.margin = margin
        self.body = []
        self.used = defaultdict(set)
        if paper:
            self.raw(f'<rect class="paper" width="{w}" height="{h}"/>')
            self.rect(0, 0, w, h)

    def raw(self, s):
        self.body.append(s)

    def text(self, x, y, s, key="text", size=13, cls="ink", anchor="start", ls=0.0, extra=""):
        self.used[key].update(s)
        a = f' text-anchor="{anchor}"' if anchor != "start" else ""
        spacing = f' letter-spacing="{ls * size:.2f}"' if ls else ""
        self.raw(f'<text x="{x:.1f}" y="{y:.1f}" class="f-{key} {cls}" font-size="{size}"'
                 f'{a}{spacing}{extra}>{escape(s)}</text>')
        return x + width(s, key, size, ls)

    def line(self, x1, y1, x2, y2, cls="h", extra=""):
        crisp = " c" if x1 == x2 or y1 == y2 else ""
        self.raw(f'<path class="{cls}{crisp}" d="M{x1:.2f} {y1:.2f}L{x2:.2f} {y2:.2f}"{extra}/>')

    def rect(self, x, y, w, h, cls="h"):
        self.raw(f'<rect class="{cls} c" x="{x}" y="{y}" width="{w}" height="{h}"/>')

    def circle(self, cx, cy, r, cls="h", extra=""):
        self.raw(f'<circle class="{cls}" cx="{cx:.2f}" cy="{cy:.2f}" r="{r}"{extra}/>')

    def path(self, d, cls="h", extra=""):
        self.raw(f'<path class="{cls}" d="{d}"{extra}/>')

    def render(self, theme):
        fonts = []
        for key, chars in sorted(self.used.items()):
            data = base64.b64encode(face(key).woff2(chars)).decode()
            fonts.append(f"@font-face{{font-family:F-{key};src:url(data:font/woff2;base64,{data}) format('woff2')}}")
        palette = ";".join(f"--{k}:{v}" for k, v in THEMES[theme].items())
        left, right = self.margin
        full = self.w + left + right
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{full:g}" height="{self.h}" '
                f'viewBox="{-left:g} 0 {full:g} {self.h}" role="img" aria-label="{escape(self.title)}">'
                f"<title>{escape(self.title)}</title>"
                f"<style>svg{{{palette};--hw:1}}{''.join(fonts)}{CSS}</style>"
                + "".join(self.body) + "</svg>\n")

    def save(self):
        for theme in THEMES:
            (ASSETS / f"{self.name}-{theme}.svg").write_text(self.render(theme))


def cells(s, y, h, items, x0=0, x1=None, pad=14):
    """A row of hairline cells. Items: dicts with text (one line) or label+value (two lines).

    One item may set flex=True to take the space left over; the rest size to their content.
    """
    x1 = s.w if x1 is None else x1
    for it in items:
        if "label" in it:
            it["w"] = max(width(it["label"], "mono", 9.5, .08), width(it["value"], it.get("face", "text"), 13)) + 2 * pad
        elif not it.get("flex"):
            it["w"] = width(it["text"], "mono", 10, .08) + 2 * pad + (12 if it.get("dot") else 0)
    fixed = sum(it.get("w", 0) for it in items if not it.get("flex"))
    for it in items:
        if it.get("flex"):
            it["w"] = x1 - x0 - fixed
    x = x0
    s.line(x0, y + h, x1, y + h)
    for i, it in enumerate(items):
        tx = x + pad
        if "label" in it:
            s.text(tx, y + 18, it["label"], "mono", 9.5, "ink2", ls=.08)
            s.text(tx, y + 38, it["value"], it.get("face", "text"), 13, it.get("cls", "ink"))
        elif it.get("text"):
            if it.get("dot"):
                s.circle(tx + 3.5, y + h / 2, 3.5, "sig pulse")
                tx += 12
            s.text(tx, y + h / 2 + 3.6, it["text"], "mono", 10, it.get("cls", "ink"), ls=.08)
        x += it["w"]
        if i < len(items) - 1:
            s.line(x, y, x, y + h)


def ruler(s, y, h=12, step=6):
    for i, x in enumerate(range(step, s.w, step)):
        major = i % 25 == 24
        tick = h - 2 if major else (6 if i % 5 == 4 else 3)
        s.line(x, y, x, y + tick, "h" if major else "h2")
    s.line(0, y + h, s.w, y + h)


def kfmt(n):
    return f"{n / 1000:.1f}K" if n >= 1000 else str(n)


# ---------------------------------------------------------------- hero

def hero(d):
    W, H = 840, 440
    s = Sheet("hero", W, H, "Max Kolyubyakin. Engineering director who still ships. "
              "Platforms: CloudBlue, Managed.com. Libraries: django-rql, django-cqrs. "
              "Tools for coding agents: agent-eye.")
    cells(s, 0, 30, [
        {"text": "MK–1", "cls": "sigink"},
        {"text": "PERSONAL DATA SHEET"},
        {"text": "BARCELONA  41.39° N  2.17° E"},
        {"flex": True},
        {"text": "SHIPPING", "dot": True},
        {"text": "REV " + d["updated"].replace("-", ".")},
    ])
    ruler(s, 30)

    top, bottom = 42, H - 56
    cx, cy = 690, (top + bottom) / 2

    # name, fitted to the space left of the drawing
    name_w = width("Kolyubyakin", "disp", 1)
    size = min(66, (cx - 124 - 32 - 24) / name_w)
    y1 = top + 30 + size * .78
    s.text(32, y1, "Max", "disp", round(size, 1), extra=' style="letter-spacing:-.01em"')
    s.text(32, y1 + size * 1.04, "Kolyubyakin", "disp", round(size, 1), extra=' style="letter-spacing:-.01em"')
    s.text(32, y1 + size * 1.04 + 40, "Engineering director who still ships.", "text", 17, "ink2")

    # FIG. 1: what I build, from the widest ring in to the pupil
    rings = [100, 62, 26]
    s.line(cx - 132, cy, cx + 132, cy, "h2 cl")
    s.line(cx, cy - 122, cx, cy + 122, "h2 cl")
    for i, r in enumerate(rings):
        s.circle(cx, cy, r, "h draw", f' pathLength="1" transform="rotate(-90 {cx} {cy})"'
                 f' style="animation-delay:{.15 * i:.2f}s"')
    s.circle(cx, cy, 9, "sig rise", ' style="animation-delay:.9s"')

    ticks = []
    for deg in range(0, 360, 5):
        a = math.radians(deg)
        r0, r1 = (105, 117) if deg % 30 == 0 else (108, 113)
        ticks.append(f"M{r0 * math.cos(a):.2f} {r0 * math.sin(a):.2f}L{r1 * math.cos(a):.2f} {r1 * math.sin(a):.2f}")
    s.raw(f'<g transform="translate({cx} {cy})"><g class="spin"><path class="h2" d="{"".join(ticks)}"/>'
          f'<circle class="sig" cx="0" cy="-121" r="2"/></g></g>')

    # diameter, over the tick ring: the joke from the old README, kept
    dy, r = top + 42, 117
    s.line(cx - r, cy - 6, cx - r, dy - 5, "h2")
    s.line(cx + r, cy - 6, cx + r, dy - 5, "h2")
    s.line(cx - r, dy, cx + r, dy)
    for x, sgn in ((cx - r, 1), (cx + r, -1)):
        s.path(f"M{x} {dy}l{7 * sgn} -2.2v4.4z", "ink")
    s.text(cx, dy - 7, "Ø 3.(428571)", "mono", 10, "ink", "middle", .04)

    # callouts with leaders to the rings
    rows = [("A", "Platforms", "CloudBlue, Managed.com", rings[0], 158, 556),
            ("B", "Libraries", "django-rql, django-cqrs", rings[1], 136, 602),
            ("C", "Tools for coding agents", "agent-eye", rings[2], 112, 640)]
    for i, (k, what, which, r, deg, shoulder) in enumerate(rows):
        y = bottom - 74 + i * 25
        s.text(32, y, k, "mono", 10, "sigink")
        x = s.text(52, y, what, "bold", 13.5)
        x = s.text(x + 8, y, which, "text", 13.5, "ink2")
        a = math.radians(deg)
        tx, ty = cx + r * math.cos(a), cy + r * math.sin(a)
        ly = y - 4.5
        s.path(f"M{x + 12:.2f} {ly:.2f}H{shoulder}L{tx:.2f} {ty:.2f}", "h draw",
               f' pathLength="1" style="animation-delay:{.6 + .15 * i:.2f}s"')
        s.circle(tx, ty, 2.2, "ink rise", f' style="animation-delay:{1.2 + .15 * i:.2f}s"')
    s.text(cx, bottom - 12, "FIG. 1 — MK–1, WHAT I BUILD", "mono", 9.5, "ink2", "middle", .08)

    cells(s, bottom, H - bottom, [
        {"label": "ROLE", "value": "Engineering director, CloudBlue", "flex": True},
        {"label": "WRITES", "value": "Python, Rust"},
        {"label": "SPEAKS", "value": "English, Español, Русский"},
        {"label": "ON GITHUB", "value": "Since " + d["github_since"]},
        {"label": "SHEET", "value": "01 / 01"},
    ])
    s.line(0, bottom, W, bottom)
    s.save()


# ---------------------------------------------------------------- links

HEAD_W, GAP, ROW_H = 84, 4, 48


def link_rows(d):
    """Rows of link cells under the hero: a header cell, then links sharing the rest.

    Each cell is its own SVG so README.md can wrap it in <a>. README.md sizes them as
    percentages of 840 (header 10%, the rest split evenly); the gap lives in the margins.
    """
    pkg = d["pypi"]
    rows = {
        "libs": ("LIBS", [("agent-eye", "RUST  ·  V" + d["agent_eye"]["version"], "agent-eye"),
                          ("django-rql", f'PYPI {kfmt(pkg["django-rql"])} / MO', "django-rql"),
                          ("django-cqrs", f'PYPI {kfmt(pkg["django-cqrs"])} / MO', "django-cqrs"),
                          ("sixseven", "ALEXA SKILL", "sixseven")]),
    }
    for row, (head, links) in rows.items():
        slots = [HEAD_W] + [(840 - HEAD_W) / len(links)] * len(links)
        for i, slot in enumerate(slots):
            margin = (0 if i == 0 else GAP / 2, 0 if i == len(slots) - 1 else GAP / 2)
            w = slot - sum(margin)
            if i == 0:
                s = Sheet(f"{row}-head", w, ROW_H, head, margin=margin)
                s.text(14, 29, head, "mono", 10, "sigink", ls=.08)
            else:
                key, label, value = links[i - 1]
                s = Sheet(f"{row}-{key}", w, ROW_H, f"{label}: {value}", margin=margin)
                s.text(14, 18, label, "mono", 9.5, "ink2", ls=.08)
                s.text(14, 37, value, "text", 13)
                s.text(w - 14, 31, "↗", "text", 15, "sigink", "end")
            s.save()


# ---------------------------------------------------------------- data

def get(url):
    headers = {"User-Agent": "maxipavlovic-profile (+https://github.com/maxipavlovic/maxipavlovic)",
               "Accept": "application/json"}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
        return json.load(r)


def fetch(d):
    """Refreshes the numbers in place. A source that fails keeps its last value."""
    new = json.loads(json.dumps(d))
    for pkg in new["pypi"]:
        try:
            new["pypi"][pkg] = get(f"https://pypistats.org/api/packages/{pkg}/recent")["data"]["last_month"]
        except Exception as e:  # noqa: BLE001
            print(f"keep {pkg}: {e}")
    try:
        new["agent_eye"]["version"] = get("https://crates.io/api/v1/crates/agent-eye")["crate"]["max_stable_version"]
    except Exception as e:  # noqa: BLE001
        print(f"keep agent-eye version: {e}")
    if {k: v for k, v in new.items() if k != "updated"} != {k: v for k, v in d.items() if k != "updated"}:
        new["updated"] = datetime.date.today().isoformat()
    return new


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fetch", action="store_true", help="refresh the numbers before drawing")
    args = ap.parse_args()
    d = json.loads(DATA.read_text())
    if args.fetch:
        d = fetch(d)
        DATA.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    ASSETS.mkdir(exist_ok=True)
    hero(d)
    link_rows(d)


if __name__ == "__main__":
    main()
