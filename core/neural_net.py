"""
Neural-network centrepiece for the HUD.

A slowly turning 3-D mesh of neurons (two lobes, like a brain) joined by
synapses. Impulses travel along the synapses as glowing pulses and cascade
from neuron to neuron, and every one of them is caused by something real:

  * what you type or say      -> bursts fired from the left (input) lobe
  * what the assistant answers -> bursts fired from the right (output) lobe,
                                   one per word, so long replies light it up
  * the live audio level       -> mic level feeds the input lobe while
                                   listening, the voice feeds the output lobe
                                   while speaking
  * THINKING / PROCESSING      -> the core fires fast, amber, in the middle
  * errors                     -> red discharge across the whole mesh

Software QPainter only, same budget as the reactor core: one batched draw for
the resting synapses, additive glow sprites for the living parts.
"""
from __future__ import annotations

import math
import random

from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPen, QPixmap, QRadialGradient,
)


def _qc(col: QColor, a: float) -> QColor:
    c = QColor(col)
    c.setAlpha(max(0, min(255, int(a))))
    return c


def _mix(col: QColor, bg: QColor, k: float) -> QColor:
    """Pre-mix onto the background so Qt can take its fast opaque path."""
    k = max(0.0, min(1.0, k))
    return QColor(int(bg.red() + (col.red() - bg.red()) * k),
                  int(bg.green() + (col.green() - bg.green()) * k),
                  int(bg.blue() + (col.blue() - bg.blue()) * k))


class NeuralCore:
    N = 128             # neurons
    K = 3               # nearest-neighbour synapses per neuron
    MAX_PULSES = 260

    def __init__(self, seed: int = 11):
        self._rnd = random.Random()
        rnd = random.Random(seed)

        # ── neurons: rejection-sampled into two lobes with a fissure ────────
        pts: list[tuple[float, float, float]] = []
        tries = 0
        while len(pts) < self.N and tries < 40000:
            tries += 1
            x, y, z = rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1)
            if x * x + y * y + z * z > 1.0:
                continue
            if abs(x) < 0.07:
                continue
            hx = x * 1.22 + (0.08 if x > 0 else -0.08)
            p = (hx, y * 0.84 - 0.06 * (1 - x * x), z * 0.95)
            if any((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2
                   < 0.036 for q in pts):
                continue
            pts.append(p)
        self.pts = pts
        n = len(pts)
        self.hub = [rnd.random() < 0.12 for _ in range(n)]

        # ── synapses: k-nearest plus a few long-range commissures ───────────
        edges: set[tuple[int, int]] = set()
        for i, a in enumerate(pts):
            d = sorted(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2, j)
                       for j, b in enumerate(pts) if j != i)
            for _, j in d[:self.K + (1 if self.hub[i] else 0)]:
                edges.add((min(i, j), max(i, j)))
            if rnd.random() < 0.07:
                j = d[rnd.randint(8, min(40, len(d) - 1))][1]
                edges.add((min(i, j), max(i, j)))
        self.edges = sorted(edges)
        self.elen = [math.dist(pts[a], pts[b]) for a, b in self.edges]
        self.adj: list[list[tuple[int, int]]] = [[] for _ in range(n)]
        for e, (a, b) in enumerate(self.edges):
            self.adj[a].append((e, b))
            self.adj[b].append((e, a))

        self.region = {
            "in":  [i for i, p in enumerate(pts) if p[0] < -0.30],
            "out": [i for i, p in enumerate(pts) if p[0] > 0.30],
            "mid": [i for i, p in enumerate(pts) if abs(p[0]) < 0.55],
            "all": list(range(n)),
        }

        # ── live state ──────────────────────────────────────────────────────
        self.act   = [0.0] * n
        self.refr  = [0.0] * n
        self.nkind = ["sys"] * n
        self.heat  = [0.0] * len(self.edges)
        self.ekind = ["sys"] * len(self.edges)
        self.pulses: list[list] = []      # [edge, dir, prog, speed, kind, strength]
        self.sched:  list[tuple[float, str, str, float]] = []
        self.waves:  list[list] = []      # [age, kind]

        self.t = 0.0
        self.yaw = 0.6
        self._spont = 0.0
        self._speed = 1.0
        self._fires = 0
        self._rate = 0.0
        self._hist: list[float] = [0.0] * 90
        self._hist_t = 0.0
        self._flash = 0.0
        self._amp = 0.0
        self._sprites: dict[tuple, QPixmap] = {}
        self._proj: list[tuple[float, float, float, float]] = []

    # ── stimulation ─────────────────────────────────────────────────────────
    def busy(self) -> bool:
        return bool(self.pulses or self.sched or self.waves)

    def stimulate(self, kind: str, words: int = 1) -> None:
        """Queue a burst. kind: in | out | think | sys | err."""
        if kind == "in":
            count, gap, region, s = min(18, 4 + words), 0.07, "in", 1.0
        elif kind == "out":
            count, gap, region, s = min(28, 4 + words), 0.055, "out", 1.0
        elif kind == "err":
            count, gap, region, s = 10, 0.03, "all", 1.0
        elif kind == "think":
            count, gap, region, s = 6, 0.05, "mid", 0.9
        else:
            count, gap, region, s = 2, 0.12, "all", 0.65
        t0 = self.t
        if self.sched:
            t0 = max(t0, self.sched[-1][0])
        for k in range(count):
            self.sched.append((t0 + k * gap, region, kind, s))
        self.waves.append([0.0, kind])
        if len(self.waves) > 6:
            self.waves.pop(0)
        self._flash = max(self._flash, 0.8 if kind != "sys" else 0.3)

    def _fire(self, i: int, kind: str, strength: float) -> None:
        if self.refr[i] > 0.0:
            return
        rnd = self._rnd
        self.act[i] = max(self.act[i], 0.45 + 0.55 * strength)
        self.refr[i] = 0.16
        self.nkind[i] = kind
        self._fires += 1
        for e, j in self.adj[i]:
            if len(self.pulses) >= self.MAX_PULSES:
                break
            if rnd.random() < 0.35 + 0.4 * strength:
                d = 1 if self.edges[e][0] == i else -1
                spd = (1.1 + rnd.random() * 0.9) * self._speed / max(0.12, self.elen[e])
                self.pulses.append([e, d, 0.0, spd, kind, strength])

    def _pick(self, region: str) -> int:
        r = self.region.get(region) or self.region["all"]
        return r[self._rnd.randrange(len(r))]

    # ── simulation ──────────────────────────────────────────────────────────
    def step(self, dt: float, amp: float, *, state: str = "",
             speaking: bool = False, muted: bool = False) -> None:
        dt = max(0.0, min(0.1, dt))
        self.t += dt
        self._amp = amp
        thinking = state in ("THINKING", "PROCESSING")

        self._speed = 1.9 if thinking else (1.45 if speaking else 0.9)
        if muted:
            self._speed = 0.5
        self.yaw += dt * (0.32 if thinking else 0.17 if speaking else 0.09)

        da = math.exp(-dt * 3.0)
        dh = math.exp(-dt * 1.7)
        self.act = [a * da for a in self.act]
        self.heat = [h * dh for h in self.heat]
        self.refr = [r - dt for r in self.refr]
        self._flash *= math.exp(-dt * 2.5)

        # scheduled bursts (conversation)
        while self.sched and self.sched[0][0] <= self.t:
            _, region, kind, s = self.sched.pop(0)
            self._fire(self._pick(region), kind, s)

        # spontaneous activity — the state and the live audio
        if muted:
            rate, region, kind = 0.25, "all", "sys"
        elif thinking:
            rate, region, kind = 7.0, "mid", "think"
        elif speaking:
            rate, region, kind = 2.0 + amp * 22.0, "out", "out"
        elif state == "LISTENING":
            rate, region, kind = 1.2 + amp * 18.0, "in", ("in" if amp > 0.05 else "sys")
        else:
            rate, region, kind = 1.2, "all", "sys"
        self._spont += rate * dt
        while self._spont >= 1.0:
            self._spont -= 1.0
            self._fire(self._pick(region), kind,
                       0.75 + 0.25 * min(1.0, amp * 2) if kind != "sys" else 0.55)

        # pulses travel; arrivals excite and may cascade
        rnd = self._rnd
        alive = []
        arrivals = []
        for pl in self.pulses:
            pl[2] += pl[3] * dt
            self.heat[pl[0]] = max(self.heat[pl[0]], 0.55 * pl[5] + 0.25)
            self.ekind[pl[0]] = pl[4]
            if pl[2] >= 1.0:
                arrivals.append(pl)
            else:
                alive.append(pl)
        self.pulses = alive
        for e, d, _, _, kind, s in arrivals:
            j = self.edges[e][1] if d == 1 else self.edges[e][0]
            self.act[j] = max(self.act[j], 0.35 + 0.5 * s)
            self.nkind[j] = kind
            if s > 0.3 and rnd.random() < 0.5:
                self._fire(j, kind, s * 0.72)

        for w in self.waves:
            w[0] += dt * 0.7
        self.waves = [w for w in self.waves if w[0] < 1.0]

        # firing-rate readout
        self._hist_t += dt
        if self._hist_t >= 0.1:
            inst = self._fires / self._hist_t
            self._fires = 0
            self._hist_t = 0.0
            self._rate += (inst - self._rate) * 0.3
            self._hist.append(self._rate)
            if len(self._hist) > 90:
                self._hist.pop(0)

    # ── painting ────────────────────────────────────────────────────────────
    def _sprite(self, col: QColor) -> QPixmap:
        key = (col.red(), col.green(), col.blue())
        pm = self._sprites.get(key)
        if pm is None:
            if len(self._sprites) > 48:
                self._sprites.clear()
            pm = QPixmap(64, 64)
            pm.fill(Qt.GlobalColor.transparent)
            g = QRadialGradient(32, 32, 32)
            g.setColorAt(0.00, _qc(col, 255))
            g.setColorAt(0.18, _qc(col, 170))
            g.setColorAt(0.45, _qc(col, 55))
            g.setColorAt(1.00, _qc(col, 0))
            sp = QPainter(pm)
            sp.setPen(Qt.PenStyle.NoPen)
            sp.setBrush(QBrush(g))
            sp.drawEllipse(QRectF(0, 0, 64, 64))
            sp.end()
            self._sprites[key] = pm
        return pm

    def paint(self, p: QPainter, cx: float, cy: float, r: float,
              cols: dict, W: float, H: float, name: str = "") -> None:
        main: QColor = cols["main"]
        white: QColor = cols["white"]
        bg: QColor = cols.get("bg", QColor(0, 0, 0))
        kc = {k: cols.get(k, main) for k in ("in", "out", "think", "sys", "err")}
        t = self.t
        amp = self._amp
        src = QRectF(0, 0, 64, 64)

        # 1. atmosphere
        p.setPen(Qt.PenStyle.NoPen)
        g = QRadialGradient(cx, cy, r * 0.95)
        g.setColorAt(0.0, _qc(main, 46 + 60 * self._flash + 40 * amp))
        g.setColorAt(0.5, _qc(main, 14 + 20 * self._flash))
        g.setColorAt(1.0, _qc(main, 0))
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(cx, cy), r * 0.95, r * 0.95)
        p.setBrush(Qt.BrushStyle.NoBrush)

        # 2. frame: corner brackets, rings, graduations, rotating arcs
        if W > 40 and H > 40:
            m, arm = min(W, H) * 0.035, min(W, H) * 0.055
            p.setPen(QPen(_qc(main, 110), 1.4))
            for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                x = cx + sx * (W / 2 - m)
                y = cy + sy * (H / 2 - m)
                p.drawLine(QLineF(x, y, x - sx * arm, y))
                p.drawLine(QLineF(x, y, x, y - sy * arm))

        p.setPen(QPen(_qc(main, 70), 1))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(QPen(_qc(main, 35), 1))
        p.drawEllipse(QPointF(cx, cy), r * 0.965, r * 0.965)

        major, minor = [], []
        rot = t * 4.0
        for i in range(120):
            a = math.radians(i * 3.0 + rot)
            ca, sa = math.cos(a), math.sin(a)
            if i % 10 == 0:
                major.append(QLineF(cx + ca * r * 1.015, cy + sa * r * 1.015,
                                    cx + ca * r * 1.06, cy + sa * r * 1.06))
            else:
                minor.append(QLineF(cx + ca * r * 1.015, cy + sa * r * 1.015,
                                    cx + ca * r * 1.032, cy + sa * r * 1.032))
        p.setPen(QPen(_mix(main, bg, 0.55), 1.3))
        p.drawLines(major)
        p.setPen(QPen(_mix(main, bg, 0.22), 1))
        p.drawLines(minor)

        act_col = cols.get("acc", main)
        spd = 1.0 + 2.5 * min(1.0, self._rate / 30.0)
        for k, (rr, span, cnt, dirn, a, wd) in enumerate((
                (0.985, 70, 3, +1, 170, 2.0),
                (1.09, 24, 6, -1, 110, 1.4),
                (1.12, 140, 1, +1, 70, 1.0))):
            rad = r * rr
            box = QRectF(cx - rad, cy - rad, rad * 2, rad * 2)
            base = (t * spd * (14 + k * 9) * dirn) % 360.0
            p.setPen(QPen(_qc(act_col if k == 0 else main, a), wd))
            for s in range(cnt):
                p.drawArc(box, int((base + s * 360.0 / cnt) * 16), int(span * 16))

        # shockwaves — one per conversational event
        for age, kind in self.waves:
            rad = r * (0.15 + 0.9 * age)
            p.setPen(QPen(_qc(kc.get(kind, main), 150 * (1 - age) ** 1.5), 1.5))
            p.drawEllipse(QPointF(cx, cy), rad, rad)

        # 3. ghost name behind the mesh
        if name:
            fsz = max(10, int(min(r * 0.22, r * 1.6 / max(1, len(name)))))
            f = QFont("Courier New", fsz, QFont.Weight.Bold)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, fsz * 0.35)
            p.setFont(f)
            p.setPen(QPen(_qc(main, 26 + 40 * self._flash + 30 * amp), 1))
            p.drawText(QRectF(cx - r, cy - fsz, r * 2, fsz * 2),
                       Qt.AlignmentFlag.AlignCenter, name)

        # 4. project the mesh
        R = r * 0.76
        cyw, syw = math.cos(self.yaw), math.sin(self.yaw)
        pitch = 0.30 + 0.06 * math.sin(t * 0.27)
        cp, sp_ = math.cos(pitch), math.sin(pitch)
        breathe = 1.0 + 0.012 * math.sin(t * 1.3) + 0.05 * amp
        proj = []
        for x, y, z in self.pts:
            x1 = x * cyw + z * syw
            z1 = -x * syw + z * cyw
            y2 = y * cp - z1 * sp_
            z2 = y * sp_ + z1 * cp
            s = 3.2 / (3.2 + z2) * breathe
            depth = max(0.0, min(1.0, (1.0 - z2) / 2.0))
            proj.append((cx + x1 * R * s, cy + y2 * R * s, depth, s))
        self._proj = proj

        # 5. synapses — resting ones batched by depth, hot ones individually
        back, front = [], []
        hot = []
        for e, (a, b) in enumerate(self.edges):
            pa, pb = proj[a], proj[b]
            ln = QLineF(pa[0], pa[1], pb[0], pb[1])
            (front if pa[2] + pb[2] > 1.0 else back).append(ln)
            if self.heat[e] > 0.06:
                hot.append((e, ln, (pa[2] + pb[2]) / 2))
        p.setPen(QPen(_mix(main, bg, 0.13), 1))
        p.drawLines(back)
        p.setPen(QPen(_mix(main, bg, 0.26), 1))
        p.drawLines(front)
        for e, ln, dep in hot:
            h = self.heat[e]
            p.setPen(QPen(_qc(kc.get(self.ekind[e], main), 40 + 190 * h * (0.5 + 0.5 * dep)),
                          0.8 + 1.6 * h))
            p.drawLine(ln)

        # 6. impulses — trail + additive glow head
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        for e, d, prog, _, kind, s in self.pulses:
            a, b = self.edges[e]
            if d == -1:
                a, b = b, a
            pa, pb = proj[a], proj[b]
            hx = pa[0] + (pb[0] - pa[0]) * prog
            hy = pa[1] + (pb[1] - pa[1]) * prog
            tp = max(0.0, prog - 0.35)
            tx = pa[0] + (pb[0] - pa[0]) * tp
            ty = pa[1] + (pb[1] - pa[1]) * tp
            dep = pa[2] + (pb[2] - pa[2]) * prog
            col = kc.get(kind, main)
            p.setPen(QPen(_qc(col, 90 + 140 * s * (0.4 + 0.6 * dep)), 1.4 + dep))
            p.drawLine(QLineF(tx, ty, hx, hy))
            sz = (4.0 + 7.0 * s) * (0.6 + 0.6 * dep) * r / 260.0
            p.drawPixmap(QRectF(hx - sz, hy - sz, sz * 2, sz * 2), self._sprite(col), src)

        # 7. neurons — back to front; active ones bloom
        order = sorted(range(len(proj)), key=lambda i: proj[i][2])
        for i in order:
            a = self.act[i]
            if a < 0.05:
                continue
            x, y, dep, s = proj[i]
            col = kc.get(self.nkind[i], main)
            sz = (6.0 + 22.0 * a) * (0.55 + 0.6 * dep) * (1.3 if self.hub[i] else 1.0) * r / 260.0
            p.drawPixmap(QRectF(x - sz, y - sz, sz * 2, sz * 2), self._sprite(col), src)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        p.setPen(Qt.PenStyle.NoPen)
        for i in order:
            x, y, dep, s = proj[i]
            a = self.act[i]
            rad = (1.0 + 1.7 * dep) * (1.7 if self.hub[i] else 1.0) * max(0.7, r / 260.0)
            k = min(1.0, a * 1.3)
            base = _qc(main, 70 + 150 * dep)
            c = QColor(int(base.red() + (white.red() - base.red()) * k),
                       int(base.green() + (white.green() - base.green()) * k),
                       int(base.blue() + (white.blue() - base.blue()) * k),
                       int(base.alpha() + (255 - base.alpha()) * k))
            p.setBrush(c)
            p.drawEllipse(QPointF(x, y), rad, rad)
            if self.hub[i]:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(_qc(main, 50 + 120 * max(dep * 0.5, a)), 0.8))
                p.drawEllipse(QPointF(x, y), rad * 2.3, rad * 2.3)
                p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        # 8. readouts
        self._paint_readouts(p, cx, cy, r, cols, W, H, name)

    def _paint_readouts(self, p, cx, cy, r, cols, W, H, name):
        main, dim = cols["main"], cols.get("dim", cols["main"])
        if W < 360 or H < 200:
            return
        f = QFont("Courier New", 8)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        p.setFont(f)
        x0 = cx - W / 2 + min(W, H) * 0.06
        y0 = cy - H / 2 + min(W, H) * 0.06
        active = sum(1 for h in self.heat if h > 0.15)
        lines = (
            (f"MALHA NEURAL // {name.upper() or 'NÚCLEO'}", main, 200),
            (f"NÓS {len(self.pts):>4}   SINAPSES {len(self.edges):>4}", dim, 255),
            (f"IMPULSOS/S {self._rate:6.1f}", main, 230),
            (f"SINAPSES ATIVAS {active:>4}", main, 230),
            (f"EM TRÂNSITO {len(self.pulses):>5}", dim, 255),
        )
        for k, (txt, col, a) in enumerate(lines):
            p.setPen(QPen(_qc(col, a), 1))
            p.drawText(QPointF(x0, y0 + 12 + k * 13), txt)

        # right side: lobe activity meters
        def lobe(reg):
            idx = self.region[reg]
            return sum(self.act[i] for i in idx) / max(1, len(idx))
        xr = cx + W / 2 - min(W, H) * 0.06 - 128
        for k, (lbl, reg, ck) in enumerate((("ENTRADA", "in", "in"),
                                            ("NÚCLEO ", "mid", "think"),
                                            ("SAÍDA  ", "out", "out"))):
            v = min(1.0, lobe(reg) * 3.5)
            y = y0 + 12 + k * 15
            p.setPen(QPen(_qc(dim, 255), 1))
            p.drawText(QPointF(xr, y), lbl)
            bx, bw = xr + 60, 68
            p.setPen(QPen(_qc(main, 70), 1))
            p.drawRect(QRectF(bx, y - 7, bw, 6))
            p.fillRect(QRectF(bx + 1, y - 6, (bw - 2) * v, 4), _qc(cols.get(ck, main), 220))

        # sparkline of firing rate, bottom-left
        hist = self._hist
        if len(hist) > 2:
            sw, sh = min(170.0, W * 0.25), 26.0
            sx = x0
            sy = cy + H / 2 - min(W, H) * 0.05
            mx = max(10.0, max(hist))
            p.setPen(QPen(_qc(main, 50), 1))
            p.drawLine(QLineF(sx, sy, sx + sw, sy))
            pts = [QPointF(sx + sw * i / (len(hist) - 1), sy - sh * v / mx)
                   for i, v in enumerate(hist)]
            p.setPen(QPen(_qc(cols.get("acc", main), 200), 1.2))
            p.drawPolyline(pts)
            p.setPen(QPen(_qc(dim, 255), 1))
            p.drawText(QPointF(sx, sy - sh - 4), "ATIVIDADE SINÁPTICA")
