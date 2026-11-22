#!/usr/bin/env python3
"""Draws the profile sheets in assets/ from build/data.json.

    python build/build.py            # redraw from data.json
    python build/build.py --fetch    # refresh the numbers first (GitHub, PyPI, crates.io)

Every sheet is written twice, light and dark; README.md picks one with <picture>.
Fonts are subset per sheet and embedded, so the SVGs look the same in every browser.
"""
import argparse
import base64
import datetime
import io
import json
import math
import os
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
LOGIN = "maxipavlovic"

THEMES = {
    "light": dict(paper="#ecebe7", lit="#f6f5f1", ink="#0e0e0d", ink2="#57564f",
                  rule="#0e0e0d", rule2="#bdbcb5", sig="#f0561a", sigink="#b23d08"),
    "dark": dict(paper="#0b0b0a", lit="#181816", ink="#ecebe6", ink2="#aaa8a0",
                 rule="#d9d8d2", rule2="#55544e", sig="#ff6a2b", sigink="#ff8a55"),
}

FACES = {
    "disp": ("Archivo[wdth,wght].ttf", {"wdth": 125, "wght": 100}),
    "label": ("Archivo[wdth,wght].ttf", {"wdth": 125, "wght": 500}),
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
.paper{fill:var(--paper)}.lit{fill:var(--lit)}
.ink{fill:var(--ink)}.ink2{fill:var(--ink2)}.sig{fill:var(--sig)}.sigink{fill:var(--sigink)}
.h,.h2,.hs{fill:none;stroke-width:var(--hw);vector-effect:non-scaling-stroke}
.h{stroke:var(--rule)}.h2{stroke:var(--rule2)}.hs{stroke:var(--sig)}
.c{shape-rendering:crispEdges}
.cl{stroke-dasharray:18 3 2 3}
.f-disp{font-family:F-disp}.f-label{font-family:F-label}.f-text{font-family:F-text}
.f-bold{font-family:F-bold}.f-mono{font-family:F-mono}
text{font-kerning:normal}
@media (min-resolution:2dppx){svg{--hw:.5}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes draw{from{stroke-dasharray:1;stroke-dashoffset:1}to{stroke-dasharray:1;stroke-dashoffset:0}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.2}}
@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}
@keyframes rise{from{opacity:0;transform:translateY(6px)}}
.spin{animation:spin 160s linear infinite}
.draw{animation:draw 1.6s cubic-bezier(.6,0,.2,1) backwards}
.pulse{animation:pulse 2.4s ease-in-out infinite}
.blink{animation:blink 1.1s steps(1) infinite}
.rise{animation:rise .9s cubic-bezier(.2,.7,.2,1) backwards}
@media (prefers-reduced-motion:reduce){.spin,.pulse,.blink,.draw,.rise{animation:none}}
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


def wrap(s, key, size, max_w):
    lines, cur = [], ""
    for word in s.split():
        nxt = f"{cur} {word}".strip()
        if cur and width(nxt, key, size) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = nxt
    return lines + [cur]


def kfmt(n):
    return f"{n / 1000:.1f}K" if n >= 1000 else str(n)


# ---------------------------------------------------------------- hero

def hero(d):
    W, H = 840, 440
    s = Sheet("hero", W, H, "Max Kolyubyakin. Engineering director who still ships. "
              "Platforms: CloudBlue, Managed.com. Libraries: django-rql, django-cqrs, lib-rql. "
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


# ---------------------------------------------------------------- section rules

def section(name, num, label, right):
    W, H, y = 840, 72, 57
    s = Sheet(name, W, H, f"{num} {label}", paper=False)
    s.text(0, y, num, "mono", 10.5, "sigink", ls=.06)
    x = s.text(34, y, label, "label", 12.5, "ink", ls=.14)
    rw = width(right, "mono", 10, .08)
    s.line(x + 16, y - 4, W - rw - 16, y - 4)
    s.text(W, y, right, "mono", 10, "ink2", "end", .08)
    s.save()


# ---------------------------------------------------------------- agent-eye

def agent_eye(d):
    W, H = 840, 252
    eye = d["agent_eye"]
    s = Sheet("agent-eye", W, H, "agent-eye: find, sort, resume and finish your coding-agent sessions, even overnight. "
              "brew install maxipavlovic/tap/agent-eye")
    cells(s, 0, 30, [
        {"text": "P/N AE–01", "cls": "sigink"},
        {"text": "AGENT-EYE"},
        {"text": "RUST"},
        {"text": "MACOS · LINUX"},
        {"flex": True},
        {"text": "MIT"},
        {"text": "V" + eye["version"]},
    ])

    s.text(32, 88, "agent-eye", "disp", 46, extra=' style="letter-spacing:-.01em"')
    s.text(32, 124, "Find, sort, resume and finish your coding-agent sessions.", "text", 16)
    s.text(32, 146, "Even overnight. A local index, a terminal picker and a board.", "text", 13.5, "ink2")
    cmd = "brew install maxipavlovic/tap/agent-eye"
    bw = width("$ " + cmd, "mono", 11, .02) + 28
    s.rect(32, 168, round(bw), 32)
    x = s.text(46, 188, "$ ", "mono", 11, "ink2", ls=.02)
    s.text(x, 188, cmd, "mono", 11, "ink", ls=.02)
    s.text(32, 228, "WORKS WITH  " + "  ·  ".join(eye["works_with"]), "mono", 9.5, "ink2", ls=.08)

    # FIG. 2: the picker, drawn
    x0, y0, w, h = 512, 48, 300, 184
    s.raw(f'<rect class="lit" x="{x0}" y="{y0}" width="{w}" height="{h}"/>')
    s.rect(x0, y0, w, h)
    s.text(x0 + 12, y0 + 15, "EYE", "mono", 9, "ink2", ls=.1)
    s.text(x0 + w - 12, y0 + 15, "FIG. 2 — PICKER", "mono", 9, "ink2", "end", .1)
    s.line(x0, y0 + 22, x0 + w, y0 + 22)
    s.text(x0 + 12, y0 + 42, "›", "text", 14, "sigink")
    q = "rql nested"
    qx = s.text(x0 + 26, y0 + 41, q, "text", 12.5)
    s.raw(f'<rect class="sig blink" x="{qx + 2:.1f}" y="{y0 + 31}" width="1.5" height="13"/>')
    s.line(x0, y0 + 50, x0 + w, y0 + 50)
    rows = [("need", "Fix RQL select on nested fields", "2m"),
            ("run", "lib-rql 2.0: nested lookups", "14m"),
            ("idle", "Docs: RQL ordering examples", "1h"),
            ("done", "Night run: bump django-rql deps", "9h"),
            ("done", "Review: RQL in CQRS replicas", "2d")]
    for i, (state, title, age) in enumerate(rows):
        ry = y0 + 50 + i * 22
        if i == 0:
            s.raw(f'<rect class="paper" x="{x0 + .5}" y="{ry + .5}" width="{w - 1}" height="21"/>')
            s.raw(f'<rect class="sig" x="{x0}" y="{ry}" width="2" height="22"/>')
        mx, my = x0 + 16, ry + 11
        if state == "need":
            s.circle(mx, my, 3.2, "sig pulse")
        elif state == "run":
            s.circle(mx, my, 3.2, "h")
            s.path(f"M{mx} {my - 3.2}A3.2 3.2 0 0 1 {mx + 3.2} {my}", "h")
        elif state == "idle":
            s.circle(mx, my, 3.2, "h2")
        else:
            s.circle(mx, my, 3.2, "ink")
        s.text(x0 + 28, ry + 15, title, "text", 11.5, "ink" if i == 0 else "ink2")
        s.text(x0 + w - 12, ry + 15, age, "mono", 9, "ink2", "end")
    s.line(x0, y0 + h - 24, x0 + w, y0 + h - 24, "h2")
    s.text(x0 + 12, y0 + h - 8, "ENTER RESUME   CTRL-F FORK   ESC", "mono", 8.5, "ink2", ls=.08)
    s.save()


# ---------------------------------------------------------------- parts

def drawing(s, kind, x, y):
    """Small one-line objects, centred on (x, y). Simple on purpose: rings and lines, no detail."""
    if kind == "funnel":
        for i, dx in enumerate((-24, -12, 0, 12, 24)):
            s.circle(x + dx, y - 40 + (i % 2) * 6, 2, "ink2")
        s.path(f"M{x - 36} {y - 24}H{x + 36}L{x + 8} {y + 8}V{y + 26}L{x - 8} {y + 34}V{y + 8}Z")
        s.circle(x, y + 46, 3, "sig")
    elif kind == "sync":
        for cx in (x - 26, x + 26):
            s.path(f"M{cx - 16} {y - 22}V{y + 22}A16 5 0 0 0 {cx + 16} {y + 22}V{y - 22}")
            s.raw(f'<ellipse class="h" cx="{cx}" cy="{y - 22}" rx="16" ry="5"/>')
            s.path(f"M{cx - 16} {y}A16 5 0 0 0 {cx + 16} {y}", "h2")
        s.line(x - 8, y - 6, x + 6, y - 6, "hs", ' stroke-dasharray="2 2"')
        s.path(f"M{x + 9} {y - 6}l-5 -2.5v5z", "sig")
        s.text(x - 26, y + 44, "W", "mono", 8.5, "ink2", "middle")
        s.text(x + 26, y + 44, "R", "mono", 8.5, "ink2", "middle")
    elif kind == "tree":
        nodes = {"a": (x, y - 34), "b": (x - 26, y - 4), "c": (x + 26, y - 4),
                 "d": (x + 10, y + 28), "e": (x + 42, y + 28)}
        for p, q in (("a", "b"), ("a", "c"), ("c", "d"), ("c", "e")):
            (x1, y1), (x2, y2) = nodes[p], nodes[q]
            s.line(x1, y1, x2, y2, "h2")
        for k, (nx, ny) in nodes.items():
            s.raw(f'<circle class="paper" cx="{nx}" cy="{ny}" r="5"/>')
            s.circle(nx, ny, 5, "h" if k != "e" else "hs")
        s.circle(*nodes["e"], 2, "sig")
        s.text(x - 26, y + 26, "and()", "mono", 8.5, "ink2", "middle")
    elif kind == "67":
        s.text(x - 8, y + 18, "67", "disp", 50, "ink", "middle")
        for i, r in enumerate((10, 18, 26)):
            a = math.radians(38)
            sx, sy = x + 30, y + 2
            s.path(f"M{sx + r * math.cos(-a):.2f} {sy + r * math.sin(-a):.2f}"
                   f"A{r} {r} 0 0 1 {sx + r * math.cos(a):.2f} {sy + r * math.sin(a):.2f}",
                   "hs" if i == 0 else "h2")


def part(d, p, column):
    W, H, gap = 412, 200, 2
    s = Sheet("part-" + p["name"], W, H, f'{p["name"]}: {p["desc"]}',
              margin=(0, gap) if column == 0 else (gap, 0))
    cells(s, 0, 28, [
        {"text": "P/N " + p["pn"], "cls": "sigink"},
        {"text": p["lang"]},
        {"flex": True},
        {"text": f'STARS {p["stars"]}'},
    ])
    s.text(20, 72, p["name"], "disp", 29, extra=' style="letter-spacing:-.01em"')
    for i, ln in enumerate(wrap(p["desc"], "text", 13.5, 250)):
        s.text(20, 100 + i * 19, ln, "text", 13.5, "ink2")
    drawing(s, p["drawing"], 348, 92)
    cells(s, H - 52, 52, [{**c, "face": "mono", "flex": i == 0} for i, c in enumerate(p["spec"])])
    s.line(0, H - 52, W, H - 52)
    s.save()


def parts(d):
    pkg = d["pypi"]
    repo = d["repos"]
    rql, cqrs, lib = repo["cloudblue/django-rql"], repo["cloudblue/django-cqrs"], repo["cloudblue/lib-rql"]
    return [
        {"name": "django-rql", "pn": "RQ–02", "lang": "PYTHON", "stars": rql["stars"], "drawing": "funnel",
         "desc": "RQL filtering for Django REST APIs: one query string, any filter.",
         "spec": [{"label": "PYPI / MONTH", "value": kfmt(pkg["django-rql"])},
                  {"label": "COMMITS", "value": str(rql["commits"])},
                  {"label": "ROLE", "value": "Author"}]},
        {"name": "django-cqrs", "pn": "CQ–03", "lang": "PYTHON", "stars": cqrs["stars"], "drawing": "sync",
         "desc": "Keeps read replicas in sync across Django services, from domain events.",
         "spec": [{"label": "PYPI / MONTH", "value": kfmt(pkg["django-cqrs"])},
                  {"label": "COMMITS", "value": str(cqrs["commits"])},
                  {"label": "ROLE", "value": "Author"}]},
        {"name": "lib-rql", "pn": "LR–04", "lang": "PYTHON", "stars": lib["stars"], "drawing": "tree",
         "desc": "The RQL parser and filter core that django-rql runs on.",
         "spec": [{"label": "PYPI / MONTH", "value": kfmt(pkg["lib-rql"])},
                  {"label": "POWERS", "value": "django-rql"},
                  {"label": "ROLE", "value": "Top contributor"}]},
        {"name": "sixseven", "pn": "SS–05", "lang": "PYTHON", "stars": repo["maxipavlovic/sixseven"]["stars"],
         "drawing": "67",
         "desc": "An Alexa skill that says Six Seven back. Because your kid won't stop saying it.",
         "spec": [{"label": "INPUT", "value": "Six Seven"},
                  {"label": "OUTPUT", "value": "Six Seven"},
                  {"label": "RUNS ON", "value": "Alexa"}]},
    ]


# ---------------------------------------------------------------- notes and links

# (text, is_link) runs; README.md wraps the rows that hold a link in <a>
NOTES = [
    [("Love programming in any language, but best at Python. Lately, Rust.", False)],
    [("Believe in small teams that ship, and in my current projects.", False)],
    [("Fluent in English, hablo español и по-русски могу :)", False)],
    [("Can’t live without music: ", False), ("playlist ↗", True)],
    [("3.(428571) software engineer (and director). Measured in FIG. 1.", False)],
    [("Wrote django-rql and django-cqrs by hand, before agents did the typing.", False)],
    [("Occasionally (= never) write ", False), ("on Medium ↗", True)],
    [("Have a surname that’s hard to pronounce.", False)],
]

LINKS = [("linkedin", "LINKEDIN", "in/mxms"), ("x", "X", "@maxalorian"), ("medium", "MEDIUM", "@maxipavlovic")]


def note(i, runs):
    W, H, y = 840, 40, 25
    s = Sheet(f"note-{i:02d}", W, H, "".join(t for t, _ in runs), paper=False)
    s.text(0, y, f"{i:02d}", "mono", 10.5, "sigink", ls=.06)
    x = 40
    for t, link in runs:
        end = s.text(x, y, t, "text", 16, "sigink" if link else "ink")
        if link:
            s.line(x, y + 4, end, y + 4, "hs")
        x = end
    s.line(0, H - .5, W, H - .5, "h2")
    s.save()


def link_cell(i, key, label, value, n=len(LINKS), total=840, gap=4):
    """One of n link cells that sit side by side at 100/n % each, with a gap between sheets."""
    w = (total - gap * (n - 1)) / n
    x, slot = i * (w + gap), total / n
    s = Sheet("link-" + key, w, 48, f"{label}: {value}",
              margin=(x - i * slot, (i + 1) * slot - x - w))
    s.text(14, 18, label, "mono", 9.5, "ink2", ls=.08)
    s.text(14, 37, value, "text", 13)
    s.text(w - 14, 31, "↗", "text", 15, "sigink", "end")
    s.save()


# ---------------------------------------------------------------- footer

def footer(d):
    W, H = 840, 56
    s = Sheet("footer", W, H, "End of sheet. Drawn by M. Kolyubyakin. This is the way.")
    cells(s, 0, H, [
        {"label": "DRAWN", "value": "M. Kolyubyakin", "flex": True},
        {"label": "CHECKED", "value": "Twice"},
        {"label": "APPROVED", "value": "This is the way"},
        {"label": "SCALE", "value": "1 : 1"},
        {"label": "REV", "value": d["updated"].replace("-", "."), "face": "mono"},
    ])
    s.save()


# ---------------------------------------------------------------- data

def get(url):
    headers = {"User-Agent": "maxipavlovic-profile (+https://github.com/maxipavlovic/maxipavlovic)",
               "Accept": "application/json"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
        return json.load(r)


def fetch(d):
    """Refreshes the numbers in place. A source that fails keeps its last value."""
    new = json.loads(json.dumps(d))
    for name, info in new["repos"].items():
        try:
            info["stars"] = get(f"https://api.github.com/repos/{name}")["stargazers_count"]
            if "commits" in info:
                people = get(f"https://api.github.com/repos/{name}/contributors?per_page=100")
                info["commits"] = next(p["contributions"] for p in people if p["login"] == LOGIN)
        except Exception as e:  # noqa: BLE001 - keep the old number, say why
            print(f"keep {name}: {e}")
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
    agent_eye(d)
    for i, p in enumerate(parts(d)):
        part(d, p, i % 2)
    libs = sum(d["pypi"].values())
    section("section-now", "02", "NOW SHIPPING", "1 PART")
    section("section-parts", "03", "PARTS LIST", f"OPEN SOURCE  ·  {kfmt(libs)} PYPI DOWNLOADS / MONTH")
    section("section-notes", "04", "GENERAL NOTES", "READ BEFORE USE")
    for i, runs in enumerate(NOTES, 1):
        note(i, runs)
    for i, link in enumerate(LINKS):
        link_cell(i, *link)
    footer(d)


if __name__ == "__main__":
    main()
