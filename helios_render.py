"""Cinematic 3D viewport for the Helios QML dashboard.

Why a QPainter renderer instead of Qt3D
---------------------------------------
The scene is ~60 rigid facets plus a bus, a boom, a dish, a projected ground
grid and a lens flare.  Rendering it with ``QQuickPaintedItem`` keeps the
dependency set to PySide6-Essentials (Qt3D lives in the ~200 MB Addons wheel
and is unreliable under the Metal RHI on macOS), gives per-face control over
the shading model, and costs a few milliseconds per frame at 30 fps.  The item
still participates fully in QML: it is a registered QML type with bindable
properties, so ``sunAzimuth`` / ``sunElevation`` / ``thetaDeg`` come straight
from the PyTorch backend.

Lighting model
--------------
Every facet carries an outward normal.  The sun direction is the same unit
vector the optimizer sees, so what the eye sees and what the solver sees cannot
drift apart:

    diffuse  = max(0, n . sun)
    specular = max(0, n . half)^48            (Blinn-Phong, half = sun + eye)
    rim      = (1 - |n . view|)^3

Cells are dark indigo when unlit and teal when lit, with a white-cyan specular
spike and a thin cyan rim, which is what makes the fold read as polished
hardware rather than flat polygons.  The lens flare is projected from the same
sun vector, clamped to the viewport edge so it slides across the frame as the
operator dials the sun around the satellite.
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import Property, QPointF, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtQuick import QQuickPaintedItem

# Miura facet coupling used by the physics model (cos of the crease half angle).
COS_ALPHA = math.cos(math.radians(45.0))

# Satellite floor: the whole craft (bus, boom, dish, radiator and wing) rides
# on this positive Z offset so it floats ~22% higher above the reflective
# grid plane instead of intersecting the bottom telemetry charts.
SCENE_LIFT = 0.52

Vec3 = tuple


def _norm(v):
    m = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / m, v[1] / m, v[2] / m)


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _mix(c0, c1, t):
    return (
        c0[0] + (c1[0] - c0[0]) * t,
        c0[1] + (c1[1] - c0[1]) * t,
        c0[2] + (c1[2] - c0[2]) * t,
    )


class _Face:
    """A flat polygon with an outward normal and a material colour."""

    __slots__ = ("points", "normal", "base", "kind")

    def __init__(self, points, normal, base, kind="panel") -> None:
        self.points = points
        self.normal = _norm(normal)
        self.base = base
        self.kind = kind


class SatelliteView(QQuickPaintedItem):
    """Interactive, sun-lit 3D portrait of the origami array satellite."""

    sunAzimuthChanged = Signal()
    sunElevationChanged = Signal()
    thetaChanged = Signal()
    spinChanged = Signal()

    # ------------------------------------------------------------------ #
    # Bindable state
    # ------------------------------------------------------------------ #

    def _get_sun_azimuth(self) -> float:
        return self._sun_azimuth

    def _set_sun_azimuth(self, value: float) -> None:
        value = float(value) % 360.0
        if value == self._sun_azimuth:
            return
        self._sun_azimuth = value
        self._refresh_sun()
        self.sunAzimuthChanged.emit()
        self.update()

    def _get_sun_elevation(self) -> float:
        return self._sun_elevation

    def _set_sun_elevation(self, value: float) -> None:
        value = max(0.0, min(90.0, float(value)))
        if value == self._sun_elevation:
            return
        self._sun_elevation = value
        self._refresh_sun()
        self.sunElevationChanged.emit()
        self.update()

    def _get_theta(self) -> float:
        return self._theta_deg

    def _set_theta(self, value: float) -> None:
        value = max(0.0, min(90.0, float(value)))
        if abs(value - self._theta_deg) < 1e-6:
            return
        self._theta_deg = value
        self.thetaChanged.emit()
        self.update()

    def _get_spin(self) -> bool:
        return self._spin

    def _set_spin(self, value: bool) -> None:
        value = bool(value)
        if value == self._spin:
            return
        self._spin = value
        self.spinChanged.emit()

    sunAzimuth = Property(float, _get_sun_azimuth, _set_sun_azimuth, notify=sunAzimuthChanged)
    sunElevation = Property(float, _get_sun_elevation, _set_sun_elevation, notify=sunElevationChanged)
    thetaDeg = Property(float, _get_theta, _set_theta, notify=thetaChanged)
    spin = Property(bool, _get_spin, _set_spin, notify=spinChanged)

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAntialiasing(True)
        self.setOpaquePainting(False)
        self.setClip(True)

        self._sun_azimuth = 35.0
        self._sun_elevation = 46.0
        self._theta_deg = 12.0
        self._spin = True
        self._yaw_deg = -34.0
        self._pitch_deg = 31.0
        self._unseen_ticks = 0
        self._time_s = 0.0
        self._refresh_sun()

        rng = random.Random(20261028)
        self._stars = [
            (
                rng.random(),
                rng.random(),
                0.5 + rng.random() * 1.5,
                0.10 + rng.random() * 0.75,
                rng.random() * math.tau,
                0.4 + rng.random() * 1.4,
            )
            for _ in range(150)
        ]
        self._nebula = [
            (0.18, 0.24, 0.55, QColor(38, 74, 160, 46)),
            (0.82, 0.16, 0.42, QColor(96, 40, 150, 34)),
            (0.62, 0.86, 0.50, QColor(16, 96, 130, 26)),
        ]

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    # ------------------------------------------------------------------ #
    # Camera / interaction
    # ------------------------------------------------------------------ #

    def _refresh_sun(self) -> None:
        az = math.radians(self._sun_azimuth)
        el = math.radians(self._sun_elevation)
        self._sun = _norm(
            (math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el))
        )

    def _advance(self) -> None:
        if self._unseen_ticks > 0:
            self._unseen_ticks -= 1
        elif self._spin:
            self._yaw_deg += 0.085
        self._time_s += 0.033
        self.update()

    @Slot(float, float)
    def orbit(self, dx: float, dy: float) -> None:
        """Mouse drag handler: yaw/pitch the camera and pause the idle spin."""
        self._yaw_deg -= float(dx) * 0.32
        self._pitch_deg = max(-6.0, min(62.0, self._pitch_deg + float(dy) * 0.24))
        self._unseen_ticks = 120
        self.update()

    @Slot()
    def resume_spin(self) -> None:
        self._unseen_ticks = 40

    def _camera(self, w: float, h: float) -> dict:
        yaw = math.radians(self._yaw_deg)
        pitch = math.radians(self._pitch_deg)
        target = (0.30, 0.0, 0.04 + SCENE_LIFT * 0.55)
        distance = 4.65
        offset = (
            math.cos(pitch) * math.sin(yaw),
            -math.cos(pitch) * math.cos(yaw),
            math.sin(pitch),
        )
        eye = _add(target, _mul(offset, distance))
        forward = _norm(_sub(target, eye))
        right = _norm(_cross(forward, (0.0, 0.0, 1.0)))
        up = _cross(right, forward)
        return {
            "eye": eye,
            "forward": forward,
            "right": right,
            "up": up,
            "f": 1.24 * h,
            "cx": w * 0.5,
            "cy": h * 0.48,  # recentered: satellite floats mid-frame, above the dock
        }

    def _project(self, point, cam: dict):
        v = _sub(point, cam["eye"])
        z = _dot(v, cam["forward"])
        if z <= 0.08:
            return None
        x = _dot(v, cam["right"])
        y = _dot(v, cam["up"])
        return QPointF(cam["cx"] + cam["f"] * x / z, cam["cy"] - cam["f"] * y / z)

    def _project_polygon(self, points, cam: dict):
        out = QPolygonF()
        for p in points:
            q = self._project(p, cam)
            if q is None:
                return None, 1e9
            out.append(q)
        depth = sum(_dot(_sub(p, cam["eye"]), cam["forward"]) for p in points) / len(points)
        return out, depth

    # ------------------------------------------------------------------ #
    # Scene construction
    # ------------------------------------------------------------------ #

    def _box(self, center, size, base, kind="bus"):
        cx, cy, cz = center
        sx, sy, sz = (s / 2.0 for s in size)
        c = [
            (cx - sx, cy - sy, cz - sz),
            (cx + sx, cy - sy, cz - sz),
            (cx + sx, cy + sy, cz - sz),
            (cx - sx, cy + sy, cz - sz),
            (cx - sx, cy - sy, cz + sz),
            (cx + sx, cy - sy, cz + sz),
            (cx + sx, cy + sy, cz + sz),
            (cx - sx, cy + sy, cz + sz),
        ]
        quads = [
            ((0, 3, 2, 1), (0, 0, -1)),
            ((4, 5, 6, 7), (0, 0, 1)),
            ((0, 1, 5, 4), (0, -1, 0)),
            ((2, 3, 7, 6), (0, 1, 0)),
            ((1, 2, 6, 5), (1, 0, 0)),
            ((3, 0, 4, 7), (-1, 0, 0)),
        ]
        return [_Face([c[i] for i in idx], n, base, kind) for idx, n in quads]

    def _wing(self, theta_rad: float) -> list:
        """Miura-ori wing: 9 x 3 facets whose mean normal is the physics normal."""
        psi = math.atan2(COS_ALPHA * math.sin(theta_rad), math.cos(theta_rad))
        normal = (math.sin(psi), 0.0, math.cos(psi))
        along = (math.cos(psi), 0.0, -math.sin(psi))
        across = (0.0, 1.0, 0.0)

        hinge = (-0.30, 0.0, 0.26 + SCENE_LIFT)
        length, width = 2.18, 1.32
        nx, ny = 9, 3
        lift = 0.075 * math.sin(psi)

        grid = []
        for i in range(nx + 1):
            row = []
            for j in range(ny + 1):
                sign = 1.0 if (i + j) % 2 == 0 else -1.0
                p = _add(
                    hinge,
                    _add(
                        _mul(along, length * i / nx),
                        _add(
                            _mul(across, width * (j / ny - 0.5)),
                            _mul(normal, lift * sign),
                        ),
                    ),
                )
                row.append(p)
            grid.append(row)

        faces = []
        for i in range(nx):
            for j in range(ny):
                a, b = grid[i][j], grid[i + 1][j]
                c, d = grid[i + 1][j + 1], grid[i][j + 1]
                n = _cross(_sub(b, a), _sub(d, a))
                if _dot(n, normal) < 0:
                    n = _mul(n, -1.0)
                faces.append(_Face([a, b, c, d], n, (0, 0, 0), "cell"))
        return faces

    def _wing_outline(self, theta_rad: float) -> list:
        """Four gold structural rails around the wing perimeter (3D polylines)."""
        psi = math.atan2(COS_ALPHA * math.sin(theta_rad), math.cos(theta_rad))
        normal = (math.sin(psi), 0.0, math.cos(psi))
        along = (math.cos(psi), 0.0, -math.sin(psi))
        across = (0.0, 1.0, 0.0)
        hinge = (-0.30, 0.0, 0.26 + SCENE_LIFT)
        length, width = 2.18, 1.32
        nx, ny = 9, 3
        lift = 0.075 * math.sin(psi)
        lines = []
        for edge_j in (0, ny):
            pts = []
            for i in range(nx + 1):
                sign = 1.0 if (i + edge_j) % 2 == 0 else -1.0
                pts.append(
                    _add(
                        hinge,
                        _add(
                            _mul(along, length * i / nx),
                            _add(
                                _mul(across, width * (edge_j / ny - 0.5)),
                                _mul(normal, lift * sign),
                            ),
                        ),
                    )
                )
            lines.append(pts)
        for edge_i in (0, nx):
            pts = []
            for j in range(ny + 1):
                sign = 1.0 if (edge_i + j) % 2 == 0 else -1.0
                pts.append(
                    _add(
                        hinge,
                        _add(
                            _mul(along, length * edge_i / nx),
                            _add(
                                _mul(across, width * (j / ny - 0.5)),
                                _mul(normal, lift * sign),
                            ),
                        ),
                    )
                )
            lines.append(pts)
        return lines

    def _dish(self) -> list:
        center = (-1.02, 0.0, 0.52 + SCENE_LIFT)
        axis = _norm((0.30, -0.26, 0.92))
        ref = _norm(_cross(axis, (1.0, 0.0, 0.0)))
        ref2 = _cross(axis, ref)
        radius = 0.17
        ring = []
        for k in range(28):
            a = math.tau * k / 28
            ring.append(
                _add(center, _add(_mul(ref, radius * math.cos(a)), _mul(ref2, radius * math.sin(a))))
            )
        return [_Face(ring, axis, (0, 0, 0), "dish")]

    def _scene(self, theta_rad: float) -> list:
        faces = []
        faces += self._box((-0.95, 0.0, 0.0 + SCENE_LIFT), (0.88, 0.76, 0.62), (0, 0, 0), "bus")
        faces += self._box((-0.95, 0.0, 0.315 + SCENE_LIFT), (0.52, 0.44, 0.012), (0, 0, 0), "gold")
        faces += self._box((-0.60, 0.0, 0.26 + SCENE_LIFT), (0.62, 0.075, 0.075), (0, 0, 0), "boom")
        faces += self._box((-1.35, 0.0, 0.0 + SCENE_LIFT), (0.06, 0.62, 0.5), (0, 0, 0), "radiator")
        faces += self._dish()
        faces += self._wing(theta_rad)
        return faces

    # ------------------------------------------------------------------ #
    # Painting
    # ------------------------------------------------------------------ #

    def _shade(self, face: _Face, cam: dict, sun: Vec3) -> QColor:
        n = face.normal
        to_eye = _norm(_sub(cam["eye"], face.points[0]))
        facing = _dot(n, to_eye)
        light = max(0.0, _dot(n, sun))

        if face.kind == "cell":
            if facing < 0.0:
                return QColor(8, 14, 24)
            half = _norm(_add(sun, to_eye))
            spec = max(0.0, _dot(n, half)) ** 48
            rim = (1.0 - min(1.0, abs(facing))) ** 3
            base = _mix((9, 24, 42), (30, 150, 178), 0.16 + 0.84 * light)
            base = _mix(base, (150, 245, 255), min(1.0, spec * 0.75))
            base = _mix(base, (60, 190, 220), rim * 0.35)
            return QColor(int(base[0]), int(base[1]), int(base[2]))
        if face.kind == "rail":
            base = _mix((120, 96, 40), (232, 196, 96), 0.22 + 0.78 * light)
            return QColor(int(base[0]), int(base[1]), int(base[2]))
        if face.kind == "gold":
            base = _mix((70, 54, 20), (208, 168, 74), 0.22 + 0.78 * light)
            return QColor(int(base[0]), int(base[1]), int(base[2]))
        if face.kind == "dish":
            base = _mix((70, 78, 88), (206, 214, 226), 0.20 + 0.80 * light)
            return QColor(int(base[0]), int(base[1]), int(base[2]))
        if face.kind == "radiator":
            base = _mix((12, 18, 30), (48, 66, 92), 0.25 + 0.75 * light)
            return QColor(int(base[0]), int(base[1]), int(base[2]))
        # Structural bus panels.
        base = _mix((36, 44, 56), (150, 164, 182), 0.22 + 0.78 * light)
        if facing < 0.0:
            base = _mix(base, (16, 20, 28), 0.55)
        return QColor(int(base[0]), int(base[1]), int(base[2]))

    def _draw_grid(self, painter: QPainter, cam: dict) -> None:
        """Sun-kissed floor grid with exponential fog toward the bottom edge.

        Lines fade out with distance to the camera plane so the far edges of
        the floor dissolve into space instead of truncating with hard clips.
        """
        z = -1.45
        extent, step = 6.5, 0.65
        # mid_y tracks the fog gradient vertical; use viewport centre height.
        h_center = float(self.height()) * 0.5
        h_bottom = float(self.height())
        pen = QPen(QColor(0, 229, 255, 34), 1.0)
        painter.setPen(pen)
        i = -extent
        while i <= extent + 1e-9:
            a = self._project((-extent, i, z), cam)
            b = self._project((extent, i, z), cam)
            c = self._project((i, -extent, z), cam)
            d = self._project((i, extent, z), cam)
            if a and b:
                # Exponential fog: alpha decays with the line's distance below
                # the frame centre so the near/floor clip melts into the glass.
                mid_y = 0.5 * (a.y() + b.y())
                depth = max(0.0, (mid_y - h_center) / max(1.0, h_bottom - h_center))
                alpha = int(34 * math.exp(-4.5 * depth * depth))
                fogged = QColor(0, 229, 255, alpha)
                fog_pen = QPen(fogged, 1.0)
                painter.setPen(fog_pen)
                painter.drawLine(a, b)
            if c and d:
                # Depth-running lines carry varying screen-space height, so
                # split each into segments and fog every segment separately.
                segments = 14
                for s in range(segments):
                    t0, t1 = s / segments, (s + 1) / segments
                    p0 = QPointF(
                        c.x() + (d.x() - c.x()) * t0,
                        c.y() + (d.y() - c.y()) * t0,
                    )
                    p1 = QPointF(
                        c.x() + (d.x() - c.x()) * t1,
                        c.y() + (d.y() - c.y()) * t1,
                    )
                    depth_v = max(
                        0.0,
                        (0.5 * (p0.y() + p1.y()) - h_center)
                        / max(1.0, h_bottom - h_center),
                    )
                    alpha_v = int(34 * math.exp(-4.5 * depth_v * depth_v))
                    pen_v = QPen(QColor(0, 229, 255, alpha_v), 1.0)
                    painter.setPen(pen_v)
                    painter.drawLine(p0, p1)
            i += step

    def _draw_space(self, painter: QPainter, w: float, h: float) -> None:
        for fx, fy, rad, color in self._nebula:
            center = QPointF(w * fx, h * fy)
            r = max(w, h) * rad
            grad = QRadialGradient(center, r)
            grad.setColorAt(0.0, color)
            grad.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(grad)
            painter.drawEllipse(center, r, r)

        t = self._time_s
        for fx, fy, size, alpha, phase, speed in self._stars:
            twinkle = 0.65 + 0.35 * math.sin(t * speed + phase)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(215, 236, 255, int(255 * alpha * twinkle)))
            painter.drawEllipse(QPointF(w * fx, h * fy), size, size)

    def _draw_flare(self, painter: QPainter, cam: dict, w: float, h: float) -> None:
        """Anamorphic lens flare anchored to the projected sun direction."""
        sun_point = self._project(_add(cam["eye"], _mul(self._sun, 60.0)), cam)
        if sun_point is None:
            return
        facing = max(0.0, _dot(self._sun, cam["forward"]))
        if facing <= 0.0:
            return
        margin = h * 0.12
        sx = max(-margin, min(w + margin, sun_point.x()))
        sy = max(-margin, min(h + margin, sun_point.y()))
        visible = 1.0 - min(1.0, max(0.0, (abs(sx - w * 0.5) - w * 0.5) / (w * 0.5 + margin)))
        strength = facing ** 0.6 * max(0.25, visible)

        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        painter.setPen(Qt.PenStyle.NoPen)

        core = QPointF(sx, sy)
        glow_r = h * 0.55
        glow = QRadialGradient(core, glow_r)
        glow.setColorAt(0.00, QColor(255, 236, 196, int(200 * strength)))
        glow.setColorAt(0.12, QColor(255, 206, 128, int(90 * strength)))
        glow.setColorAt(0.42, QColor(120, 190, 255, int(38 * strength)))
        glow.setColorAt(1.00, QColor(0, 0, 0, 0))
        painter.setBrush(glow)
        painter.drawEllipse(core, glow_r, glow_r)

        streak_w = w * 0.95
        streak = QLinearGradient(core.x() - streak_w / 2, 0, core.x() + streak_w / 2, 0)
        streak.setColorAt(0.0, QColor(0, 0, 0, 0))
        streak.setColorAt(0.5, QColor(190, 235, 255, int(120 * strength)))
        streak.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(streak)
        painter.drawRect(QRectF(core.x() - streak_w / 2, core.y() - 1.4, streak_w, 2.8))

        center = QPointF(w * 0.5, h * 0.5)
        ghosts = (
            (-0.42, 0.085, QColor(0, 229, 255, 34)),
            (0.28, 0.055, QColor(255, 180, 90, 28)),
            (0.66, 0.115, QColor(120, 90, 255, 26)),
            (1.18, 0.070, QColor(0, 255, 170, 22)),
        )
        for t, radius, color in ghosts:
            gx = core.x() + (center.x() - core.x()) * t
            gy = core.y() + (center.y() - core.y()) * t
            r = h * radius
            ghost = QRadialGradient(QPointF(gx, gy), r)
            ghost.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), color.alpha()))
            ghost.setColorAt(0.70, QColor(color.red(), color.green(), color.blue(), color.alpha() // 3))
            ghost.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
            painter.setBrush(ghost)
            painter.drawEllipse(QPointF(gx, gy), r, r)
        painter.restore()

    def _draw_hud(self, painter: QPainter, w: float, h: float) -> None:
        painter.save()
        pen = QPen(QColor(0, 229, 255, 60), 1.2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        arm = 26.0
        inset = 8.0
        for cx, cy, dx, dy in (
            (inset, inset, 1, 1),
            (w - inset, inset, -1, 1),
            (inset, h - inset, 1, -1),
            (w - inset, h - inset, -1, -1),
        ):
            painter.drawLine(QPointF(cx, cy), QPointF(cx + arm * dx, cy))
            painter.drawLine(QPointF(cx, cy), QPointF(cx, cy + arm * dy))
        painter.restore()

    def paint(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        w, h = float(self.width()), float(self.height())
        if w < 8 or h < 8:
            return

        cam = self._camera(w, h)
        self._draw_space(painter, w, h)
        self._draw_grid(painter, cam)

        theta = math.radians(self._theta_deg)
        faces = self._scene(theta)
        projected = []
        for face in faces:
            poly, depth = self._project_polygon(face.points, cam)
            if poly is None:
                continue
            projected.append((depth, face, poly))
        projected.sort(key=lambda item: -item[0])

        painter.setPen(Qt.PenStyle.NoPen)
        for depth, face, poly in projected:
            color = self._shade(face, cam, self._sun)
            painter.setBrush(color)
            painter.drawPolygon(poly)
            edge = QColor(color)
            edge.setAlpha(46 if face.kind == "cell" else 30)
            painter.setPen(QPen(edge, 0.8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(poly)
            painter.setPen(Qt.PenStyle.NoPen)

        # Wing perimeter rails sit above the cells so the array reads as a
        # framed structure rather than a loose pile of polygons.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(226, 190, 104, 190), 1.4))
        for line in self._wing_outline(theta):
            path = QPainterPath()
            first = True
            for point in line:
                q = self._project(point, cam)
                if q is None:
                    first = True
                    continue
                if first:
                    path.moveTo(q)
                    first = False
                else:
                    path.lineTo(q)
            painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)

        self._draw_flare(painter, cam, w, h)
        self._draw_hud(painter, w, h)
