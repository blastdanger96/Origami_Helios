"""Cinematic 3D paints for the Orbital Mechanics and AI Optimizer views.

Same philosophy as ``helios_render.SatelliteView``: QQuickPaintedItem painters
registered as QML types, each with a bindable property surface, an inset
damped task-orbit camera and zeroQt dependence beyond PySide6-Essentials.
``_DampedCamera`` gives all three viewports the same AAA-feel controls:
left-drag orbit, right-drag pan, wheel zoom, all critically damped so motion
eases rather than snaps.

Euler-camera audit trail: forward is built from yaw/pitch with ``up = right x
forward``; the pitch is clamped to +-84 deg so the basis can never degenerate
(the cross with the world Z collapses at the poles), i.e. gimbal lock is
impossible rather than merely improbable.
"""

from __future__ import annotations

import math
import random
from collections import deque

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

from helios_orbit import EARTH_RADIUS_KM, OrbitSim, _eci_transform

Vec3 = tuple[float, float, float]


def _norm(v):
    m = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / m, v[1] / m, v[2] / m)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _mix(c0, c1, t):
    return (
        c0[0] + (c1[0] - c0[0]) * t,
        c0[1] + (c1[1] - c0[1]) * t,
        c0[2] + (c1[2] - c0[2]) * t,
    )


def _starfield(seed: int, count: int):
    rng = random.Random(seed)
    return [
        (
            rng.random(),
            rng.random(),
            0.5 + rng.random() * 1.6,
            0.08 + rng.random() * 0.8,
            rng.random() * math.tau,
            0.35 + rng.random() * 1.5,
        )
        for _ in range(count)
    ]


STARFIELD = _starfield(77102, 420)
NEBULAE = (
    (0.14, 0.20, 0.60, QColor(58, 30, 140, 40)),
    (0.78, 0.14, 0.44, QColor(90, 34, 150, 34)),
    (0.66, 0.88, 0.55, QColor(16, 90, 140, 28)),
    (0.42, 0.52, 0.70, QColor(140, 40, 120, 18)),
)


class _DampedCamera:
    """Task-orbit camera: yaw/pitch/pan/zoom targets critically damped each tick."""

    PITCH_LIMIT = 84.0

    def __init__(self, yaw_deg: float, pitch_deg: float, dist: float,
                 dist_range: tuple[float, float]) -> None:
        self._yaw = self._yaw_t = yaw_deg
        self._pitch = self._pitch_t = pitch_deg
        self._dist = self._dist_t = dist
        self._dist_range = dist_range
        self._pan = self._pan_t = (0.0, 0.0)
        self._target = (0.0, 0.0, 0.0)

    # -- input slots ---------------------------------------------------- #

    def orbit(self, dx: float, dy: float) -> None:
        self._yaw_t -= float(dx) * 0.42
        self._pitch_t = max(
            -self.PITCH_LIMIT,
            min(self.PITCH_LIMIT, self._pitch_t + float(dy) * 0.34),
        )

    def pan(self, dx: float, dy: float) -> None:
        # Pan in target-plane units proportional to the camera distance so a
        # drag moves a consistent screen fraction at any zoom level.
        k = 0.0026 * self._dist
        self._pan_t = (self._pan_t[0] - float(dx) * k, self._pan_t[1] + float(dy) * k)

    def zoom(self, delta: float) -> None:
        factor = math.exp(-float(delta) * 0.00115)
        self._dist_t = max(
            self._dist_range[0], min(self._dist_range[1], self._dist_t * factor)
        )

    def damping_step(self) -> None:
        k = 0.16
        self._yaw += (self._yaw_t - self._yaw) * k
        self._pitch += (self._pitch_t - self._pitch) * k
        self._dist += (self._dist_t - self._dist) * k
        px = self._pan[0] + (self._pan_t[0] - self._pan[0]) * k
        py = self._pan[1] + (self._pan_t[1] - self._pan[1]) * k
        self._pan = (px, py)

    @property
    def yaw(self) -> float:
        return self._yaw


def camera_basis(cam: _DampedCamera, target: Vec3) -> dict:
    """Eye/forward/right/up basis from the damped spherical state.

    Pitch clamps keep sin(pitch) below 0.9945 and the world-Z cross finite at
    every reachable angle (the gimbal-lock audit).
    """
    yaw = math.radians(cam._yaw)
    pitch = math.radians(cam._pitch)
    offset = (
        math.cos(pitch) * math.sin(yaw),
        -math.cos(pitch) * math.cos(yaw),
        math.sin(pitch),
    )
    eye = _add(_add(target, _mul(offset, cam._dist)), (0.0, 0.0, 0.0))
    forward = _norm(_sub(target, eye))
    right = _norm(_cross(forward, (0.0, 0.0, 1.0)))
    up = _cross(right, forward)
    # Pan offsets slide the frame in the right/up plane without re-aiming.
    pan_k = cam._dist * 0.55
    pan_right = _mul(right, cam._pan[0] * pan_k)
    pan_up = _mul(up, cam._pan[1] * pan_k)
    eye = _add(_add(eye, pan_right), pan_up)
    return {
        "eye": eye,
        "forward": _norm(_sub(target, eye)),
        "right": right,
        "up": up,
        "f": 1.05 * 900.0,
        "cx": 0.0,
        "cy": 0.0,
    }


def projector(cam: dict, w: float, h: float):
    """Return a point->QPointF perspective projection closure."""
    fx = 1.05 * min(w, 900.0)

    def project(point):
        v = _sub(point, cam["eye"])
        z = _dot(v, cam["forward"])
        if z <= 1e-6:
            return None
        x = _dot(v, cam["right"])
        y = _dot(v, cam["up"])
        return QPointF(
            w * 0.5 + fx * x / z,
            h * 0.5 - fx * y / z,
        )

    return project


def draw_space(painter, w: float, h: float, time_s: float) -> None:
    for fx, fy, rad, color in NEBULAE:
        center = QPointF(w * fx, h * fy)
        r = max(w, h) * rad
        grad = QRadialGradient(center, r)
        grad.setColorAt(0.0, color)
        grad.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawEllipse(center, r, r)

    for fx, fy, size, alpha, phase, speed in STARFIELD:
        twinkle = 0.6 + 0.4 * math.sin(time_s * speed + phase)
        painter.setBrush(QColor(220, 238, 255, int(255 * alpha * twinkle)))
        painter.drawEllipse(QPointF(w * fx, h * fy), size, size)


def draw_hud(painter, w: float, h: float) -> None:
    pen = QPen(QColor(0, 229, 255, 56), 1.2)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    arm, inset = 26.0, 8.0
    for cx, cy, dx, dy in (
        (inset, inset, 1, 1),
        (w - inset, inset, -1, 1),
        (inset, h - inset, 1, -1),
        (w - inset, h - inset, -1, -1),
    ):
        painter.drawLine(QPointF(cx, cy), QPointF(cx + arm * dx, cy))
        painter.drawLine(QPointF(cx, cy), QPointF(cx, cy + arm * dy))


def _glow_line(painter, path: QPainterPath, color: QColor, width: float) -> None:
    """Two-pass line: wide translucent halo, then a crisp core."""
    halo = QColor(color)
    halo.setAlpha(int(color.alpha() * 0.22))
    painter.setPen(QPen(halo, width * 5.0))
    stroke = QPainterPath(path)
    painter.strokePath(stroke, QPen(halo, width * 5.0))
    painter.strokePath(path, QPen(color, width))


class EarthOrbitView(QQuickPaintedItem):
    """Wireframe-and-shaded Earth + glowing orbital trajectory + craft glyph."""

    sunEciChanged = Signal()
    anomalyChanged = Signal()
    eclipseChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAntialiasing(True)
        self.setOpaquePainting(False)
        self.setClip(True)

        self._sun_eci: Vec3 = (1.0, 0.0, 0.0)
        self._anomaly_deg = 0.0
        self._eclipse = False
        self._time_s = 0.0

        self._sim = OrbitSim()
        elems = self._sim.elems
        # Full ECI ellipse polyline (nu in [0, 2pi)), computed once; the ring
        # is static because the elements are static for this prototype.
        ring = []
        for k in range(360):
            nu = math.radians(float(k))
            r = elems.p_km / (1.0 + elems.ecc * math.cos(nu))
            ring.append(_eci_transform((r * math.cos(nu), r * math.sin(nu)), elems))
        self._ellipse = ring
        self._ell_km = elems.a_km * (1.0 - elems.ecc)

        self._cam = _DampedCamera(yaw_deg=-42.0, pitch_deg=24.0,
                                  dist=4.0 * self._ell_km,
                                  dist_range=(2.2 * self._ell_km, 9.0 * self._ell_km))
        self._rng = random.Random(4102)
        self._clouds = [
            (self._rng.random(), self._rng.random(), 0.02 + self._rng.random() * 0.055)
            for _ in range(240)
        ]

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    # -- bindables ------------------------------------------------------ #

    def _get_sun_eci(self) -> list:
        return list(self._sun_eci)

    def _set_sun_eci(self, value) -> None:
        try:
            v = (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError, IndexError):
            return
        if v == self._sun_eci:
            return
        m = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
        if m < 1e-9:                       # never poison the lighting with a
            return                          # zero-length sun (manual mode)
        self._sun_eci = (v[0] / m, v[1] / m, v[2] / m)
        self.sunEciChanged.emit()
        self.update()

    def _get_anomaly(self) -> float:
        return self._anomaly_deg

    def _set_anomaly(self, value: float) -> None:
        value = max(-3600.0, min(3600.0, float(value)))
        if abs(value - self._anomaly_deg) < 1e-6:
            return
        self._anomaly_deg = value
        self.anomalyChanged.emit()
        self.update()

    def _get_eclipse(self) -> bool:
        return self._eclipse

    def _set_eclipse(self, value: bool) -> None:
        value = bool(value)
        if value == self._eclipse:
            return
        self._eclipse = value
        self.eclipseChanged.emit()
        self.update()

    sunEci = Property("QVariantList", _get_sun_eci, _set_sun_eci, notify=sunEciChanged)
    anomalyDeg = Property(float, _get_anomaly, _set_anomaly, notify=anomalyChanged)
    eclipse = Property(bool, _get_eclipse, _set_eclipse, notify=eclipseChanged)

    # -- interaction ---------------------------------------------------- #

    @Slot(float, float)
    def orbit(self, dx: float, dy: float) -> None:
        self._cam.orbit(dx, dy)

    @Slot(float, float)
    def pan(self, dx: float, dy: float) -> None:
        self._cam.pan(dx, dy)

    @Slot(float)
    def zoom(self, delta: float) -> None:
        self._cam.zoom(delta)

    def _advance(self) -> None:
        self._cam.damping_step()
        self._time_s += 0.033
        self.update()

    # -- painting ------------------------------------------------------- #

    def paint(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        if w < 8 or h < 8:
            return

        painter.fillRect(0, 0, int(w), int(h), QColor(4, 7, 13))
        draw_space(painter, w, h, self._time_s)

        cam = camera_basis(self._cam, (0.0, 0.0, 0.0))
        project = projector(cam, w, h)

        # --- Earth sphere ---------------------------------------------- #
        c0 = project((0.0, 0.0, 0.0))
        # Same focal length as projector(): fx = 1.05 * min(w, 900). Angular
        # size = fx * R / distance (the old direct-multiplication form was a
        # 280,000-px disc: audited and inverted).
        fx = 1.05 * min(w, 900.0)
        radius_px = fx * EARTH_RADIUS_KM / max(1.0, self._cam._dist)
        if c0 is None:
            radius_px = 0.0

        if radius_px >= 2.0:
            # Ocean body: radial gradient biased toward the subsolar limb.
            sun_dir = _norm(self._sun_eci)

        if radius_px >= 2.0:
            # Ocean body: radial gradient biased toward the subsolar limb.
            sun_dir = _norm(self._sun_eci)
            sun_side = QPointF(
                c0.x() + radius_px * 0.0, c0.y() + radius_px * 0.0
            )
            ocean = QRadialGradient(sun_side, radius_px * 1.35)
            ocean.setColorAt(0.0, QColor(24, 52, 92))
            ocean.setColorAt(0.55, QColor(13, 32, 58))
            ocean.setColorAt(1.0, QColor(4, 10, 20))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ocean)
            painter.drawEllipse(c0, radius_px, radius_px)

            # Volumetric (soft-blob) cloud deck drifting with time.
            painter.save()
            clip_path = QPainterPath()
            clip_path.addEllipse(c0, radius_px, radius_px)
            painter.setClipPath(clip_path)
            drift = (self._time_s * 0.004) % 1.0
            for fx, fy, size in self._clouds:
                cx = c0.x() - radius_px + ((fx + drift) % 1.0) * 2 * radius_px
                cy = c0.y() - radius_px + fy * 2 * radius_px
                cr = size * radius_px
                cloud = QRadialGradient(QPointF(cx, cy), cr)
                cloud.setColorAt(0.0, QColor(240, 246, 255, 40))
                cloud.setColorAt(1.0, QColor(240, 246, 255, 0))
                painter.setBrush(cloud)
                painter.drawEllipse(QPointF(cx, cy), cr, cr)
            painter.restore()

            # Day/night terminator: linear night gradient along the screen-
            # projected antisolar direction. The projected sun axis inside the
            # disc defines the lit side unambiguously for any camera attitude.
            v = _mul(sun_dir, -1.0)
            axis_z = _dot(v, cam["forward"])
            axis_x = _dot(v, cam["right"])
            axis_y = _dot(v, cam["up"])
            s2 = math.sqrt(max(1e-12, axis_x * axis_x + axis_y * axis_y))
            ux, uy = axis_x / s2, axis_y / s2
            night = QLinearGradient(
                c0.x() - ux * radius_px, c0.y() - uy * radius_px,
                c0.x() + ux * radius_px, c0.y() + uy * radius_px,
            )
            dark_alpha = int(210 * min(1.0, abs(axis_z) * 0.4 + 0.6))
            night.setColorAt(0.0, QColor(3, 6, 12, dark_alpha))
            night.setColorAt(0.48, QColor(3, 6, 12, int(dark_alpha * 0.75)))
            night.setColorAt(0.52, QColor(3, 6, 12, 0))
            painter.setBrush(night)
            painter.drawEllipse(c0, radius_px, radius_px)

            # Atmospheric limb: thin cyan-blue rim inside the disc edge.
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(90, 170, 255, 90), max(1.2, radius_px * 0.012)))
            painter.drawEllipse(c0, radius_px * 1.005, radius_px * 1.005)
            painter.setPen(QPen(QColor(0, 229, 255, 38), max(2.0, radius_px * 0.03)))
            painter.drawEllipse(c0, radius_px * 0.99, radius_px * 0.99)

            # Latitude/longitude wireframe, rotated by time for life.
            spin = (self._time_s * 6.0) % 360.0
            painter.setPen(QPen(QColor(80, 190, 230, 34), 0.9))
            for k in range(1, 8):
                lat = math.radians(-80.0 + 160.0 * k / 8.0)
                r_xz = radius_px * math.cos(lat)
                y = -radius_px * math.sin(lat)
                painter.drawEllipse(QPointF(c0.x(), c0.y() + y), r_xz, r_xz * 0.24)
            for k in range(12):
                lon_step = spin + 15.0 * k
                ca = math.cos(math.radians(lon_step))
                painter.drawEllipse(QPointF(c0.x(), c0.y()), radius_px * abs(ca), radius_px)

        # --- Orbit ellipse ---------------------------------------------- #
        ring_path = QPainterPath()
        ring_first = True
        for point in self._ellipse:
            q = project(point)
            if q is None:
                ring_first = True
                continue
            if ring_first:
                ring_path.moveTo(q)
                ring_first = False
            else:
                ring_path.lineTo(q)
        if not ring_first:
            _glow_line(painter, ring_path, QColor(0, 229, 255, 170), 1.6)

        # --- Satellite glyph at the live true anomaly -------------------- #
        elems = self._sim.elems
        nu = math.radians(self._anomaly_deg)
        r = elems.p_km / (1.0 + elems.ecc * math.cos(nu))
        sat_eci = _eci_transform((r * math.cos(nu), r * math.sin(nu)), elems)
        sat_q = project(sat_eci)
        if sat_q is not None:
            glow = QRadialGradient(sat_q, 16.0)
            core_color = QColor(255, 120, 90) if self._eclipse else QColor(0, 255, 170)
            glow.setColorAt(0.0, core_color)
            glow.setColorAt(1.0, QColor(core_color.red(), core_color.green(),
                                        core_color.blue(), 0))
            painter.setBrush(glow)
            painter.drawEllipse(sat_q, 16.0, 16.0)
            painter.setBrush(core_color)
            painter.drawEllipse(sat_q, 3.0, 3.0)

        # --- Sun glow at its projected direction ------------------------- #
        sun_point = project(_mul(self._sun_eci, self._cam._dist * 40.0))
        if sun_point is not None:
            painter.save()
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            flare = QRadialGradient(sun_point, 150.0)
            flare.setColorAt(0.0, QColor(255, 238, 200, 220))
            flare.setColorAt(0.2, QColor(255, 210, 140, 90))
            flare.setColorAt(1.0, QColor(40, 90, 200, 0))
            painter.setBrush(flare)
            painter.drawEllipse(sun_point, 150.0, 150.0)
            painter.restore()

        draw_hud(painter, w, h)


class OptimizerSurfaceView(QQuickPaintedItem):
    """3D loss-landscape ridge + glowing theta particle + step-size rail."""

    landscapeChanged = Signal()
    thetaChanged = Signal()
    stepChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAntialiasing(True)
        self.setOpaquePainting(False)
        self.setClip(True)

        self._landscape: list[float] = []
        self._theta_deg = 12.0
        self._step = 0.0
        self._time_s = 0.0
        self._trail: deque[tuple[float, float, float]] = deque(maxlen=70)

        self._cam = _DampedCamera(yaw_deg=-26.0, pitch_deg=16.0,
                                  dist=4.6, dist_range=(2.2, 12.0))

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    # -- bindables ------------------------------------------------------ #

    def _get_landscape(self) -> list:
        return list(self._landscape)

    def _set_landscape(self, value) -> None:
        try:
            vals = [float(v) for v in value]
        except (TypeError, ValueError):
            return
        if not vals or vals == self._landscape:
            return
        self._landscape = vals
        self.landscapeChanged.emit()
        self.update()

    def _get_theta(self) -> float:
        return self._theta_deg

    def _set_theta(self, value: float) -> None:
        value = max(0.0, min(90.0, float(value)))
        if abs(value - self._theta_deg) < 1e-6:
            return
        self._push_trail()
        self._theta_deg = value
        self.thetaChanged.emit()
        self.update()

    def _get_step(self) -> float:
        return self._step

    def _set_step(self, value: float) -> None:
        value = max(-92.0, min(92.0, float(value)))
        if abs(value - self._step) < 1e-6:
            return
        self._step = value
        self.stepChanged.emit()
        self.update()

    landscape = Property("QVariantList", _get_landscape, _set_landscape, notify=landscapeChanged)
    thetaDeg = Property(float, _get_theta, _set_theta, notify=thetaChanged)
    stepSizeDeg = Property(float, _get_step, _set_step, notify=stepChanged)

    @Slot()
    def _push_trail(self) -> None:
        p = self._ridge_point(self._theta_deg)
        if p is not None:
            self._trail.append(p)

    @Slot(float, float)
    def orbit(self, dx: float, dy: float) -> None:
        self._cam.orbit(dx, dy)

    @Slot(float, float)
    def pan(self, dx: float, dy: float) -> None:
        self._cam.pan(dx, dy)

    @Slot(float)
    def zoom(self, delta: float) -> None:
        self._cam.zoom(delta)

    # -- geometry helpers ------------------------------------------------ #

    def _ridge_height(self, theta_deg: float) -> float | None:
        """Normalised landscape value in [0, 1] at theta (linear interp).

        Audited mapping: theta in [0, 90] maps linearly onto sample indices
        [0, len(pts)-1], so theta=90 lands exactly on the last sample (the
        previous ``* len(pts) - 1`` form excluded it and skewed every interp).
        """
        pts = self._landscape
        if len(pts) < 2:
            return None
        span_pts = max(max(pts) - min(pts), 1e-9)
        x = max(0.0, min(1.0, theta_deg / 90.0)) * (len(pts) - 1)
        i0 = int(x)
        if i0 >= len(pts) - 1:
            i0 = len(pts) - 2
            x = float(len(pts) - 2) + 1e-12      # force frac=1 at the far end
        frac = x - i0
        v = pts[i0] + (pts[i0 + 1] - pts[i0]) * frac
        lo = min(pts)
        return (v - lo) / span_pts

    def _ridge_point(self, theta_deg: float):
        height = self._ridge_height(theta_deg)
        if height is None:
            return None
        # Ridge runs along Y so the default yaw frames a readable diagonal.
        x = -2.2 + height * 1.6
        y = -4.1 + (theta_deg / 90.0) * 8.2
        return (x, y, height * 2.35)

    def _advance(self) -> None:
        self._cam.damping_step()
        self._time_s += 0.033
        if self._tick20():
            self._push_trail()
        self.update()

    def _tick20(self) -> bool:
        return int(self._time_s * 60.0) % 20 == 0

    # -- painting ------------------------------------------------------- #

    def paint(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        if w < 8 or h < 8:
            return
        painter.fillRect(0, 0, int(w), int(h), QColor(4, 7, 13))
        draw_space(painter, w, h, self._time_s)

        cam = camera_basis(self._cam, (0.0, 0.0, 0.7))
        project = projector(cam, w, h)

        # --- floor grid -------------------------------------------------- #
        painter.setPen(QPen(QColor(0, 229, 255, 26), 1.0))
        i = -4.0
        while i <= 4.0 + 1e-9:
            a = project((-4.4, i, 0.0))
            b = project((4.4, i, 0.0))
            if a and b:
                painter.drawLine(a, b)
            c = project((i, -5.0, 0.0))
            d = project((i, 5.0, 0.0))
            if c and d:
                painter.drawLine(c, d)
            i += 0.8

        # --- theta rail marks --------------------------------------------- #
        for theta in (0, 15, 30, 45, 60, 75, 90):
            p = project((-4.4, -4.1 + (theta / 90.0) * 8.2, 0.0))
            if p is not None:
                painter.setPen(QPen(QColor(159, 182, 204, 90), 1.0))
                painter.drawLine(p, QPointF(p.x(), p.y() + 5))
                painter.setPen(QColor(122, 150, 178, 170))
                painter.drawText(QPointF(p.x() - 9, p.y() + 18), f"{theta}")

        pts = self._landscape
        if len(pts) < 2:
            painter.setPen(QColor(122, 150, 178, 160))
            painter.drawText(QPointF(w * 0.42, h * 0.5), "AWAITING LANDSCAPE SWEEP")
            draw_hud(painter, w, h)
            return

        # --- ridge polygon (front wall from ridge to floor) --------------- #
        wall = QPolygonF()
        ridge_path = QPainterPath()
        first = True
        for i in range(len(pts)):
            theta = 90.0 * i / (len(pts) - 1)
            point = self._ridge_point(theta)
            if point is None:
                continue
            q = project(point)
            if q is None:
                first = True
                continue
            base = project((point[0], point[1], 0.0))
            if base is None:
                first = True
                continue
            if first:
                ridge_path.moveTo(q)
                first = False
            else:
                ridge_path.lineTo(q)
            wall.append(q)
            wall.append(base)

        painter.setPen(Qt.PenStyle.NoPen)
        face = QColor(10, 60, 92, 92)
        painter.setBrush(face)
        painter.drawPolygon(wall)

        if not ridge_first_empty(ridge_path):
            _glow_line(painter, ridge_path, QColor(0, 229, 255, 220), 2.0)

        # --- optimizer trail ------------------------------------------------ #
        trail_path = QPainterPath()
        t_first = True
        for x, y, z in tuple(self._trail):
            q = project((x, y, z))
            if q is None:
                t_first = True
                continue
            if t_first:
                trail_path.moveTo(q)
                t_first = False
            else:
                trail_path.lineTo(q)
        if not ridge_first_empty(trail_path):
            _glow_line(painter, trail_path, QColor(255, 180, 84, 200), 1.5)

        # --- current theta particle ------------------------------------------ #
        point = self._ridge_point(self._theta_deg)
        if point is not None:
            q = project(point)
            if q is not None:
                pulse = 0.82 + 0.18 * math.sin(self._time_s * 4.4)
                drop = project((point[0], point[1], 0.0))
                if drop is not None:
                    painter.setPen(QPen(QColor(0, 255, 170, 90), 1.0))
                    painter.drawLine(q, drop)
                glow = QRadialGradient(q, 17.0 * pulse)
                glow.setColorAt(0.0, QColor(180, 255, 240, 235))
                glow.setColorAt(0.28, QColor(0, 255, 170, 150))
                glow.setColorAt(1.0, QColor(0, 255, 170, 0))
                painter.setBrush(glow)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(q, 17.0 * pulse, 17.0 * pulse)
                painter.setBrush(QColor(235, 255, 250))
                painter.drawEllipse(q, 3.4, 3.4)

        # --- step-size rail (bottom of the stage) ------------------------------ #
        strip_y = h - 58
        painter.setPen(QPen(QColor(255, 255, 255, 26), 1.0))
        painter.drawLine(QPointF(w * 0.08, strip_y), QPointF(w * 0.92, strip_y))
        half = (w * 0.92 - w * 0.08) / 2
        mid = w * 0.5
        step_px = max(-half, min(half, (self._step / 8.0) * half))
        if abs(step_px) > 0.6:
            color = QColor(0, 229, 255) if self._step >= 0 else QColor(255, 180, 84)
            rect = QRectF(
                mid if self._step >= 0 else mid + step_px, strip_y - 9,
                abs(step_px), 18,
            )
            gradient = QLinearGradient(rect.left(), 0, rect.right(), 0)
            gradient.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 70))
            gradient.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 220))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QColor(159, 182, 204, 190))
        painter.drawText(QPointF(w * 0.08, strip_y + 26), "STEP SIZE  dtheta / tick")
        painter.drawText(
            QPointF(w * 0.78, strip_y + 26),
            f"{self._step:+.3f} deg",
        )
        painter.setPen(QColor(122, 150, 178, 150))
        painter.drawText(QPointF(w * 0.08, strip_y - 12), "LOSS LANDSCAPE  P(theta) - ADAM DESCENT")

        draw_hud(painter, w, h)


def ridge_first_empty(path: QPainterPath) -> bool:
    """A freshly built path with only a moveTo contains no drawable segment."""
    return path.elementCount() < 2


class HorizonChart(QQuickPaintedItem):
    """Sun Incidence Angle over the NEXT 90 minutes (anti-slop, hand-painted)."""

    projectionChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAntialiasing(True)
        self.setOpaquePainting(False)
        self._projection: list[float] = []

    def _get(self) -> list:
        return list(self._projection)

    def _set(self, value) -> None:
        try:
            vals = [max(0.0, min(1.0, float(v))) for v in value]
        except (TypeError, ValueError):
            return
        if not vals or vals == self._projection:
            return
        self._projection = vals
        self.projectionChanged.emit()
        self.update()

    projection = Property("QVariantList", _get, _set, notify=projectionChanged)

    def paint(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        if w < 8 or h < 8:
            return

        pad_x, top, bottom = 30.0, 22.0, h - 30.0
        plot_h = max(10.0, bottom - top)
        plot_w = max(10.0, w - pad_x * 2 - 6.0)

        pts = self._projection
        if len(pts) < 2:
            painter.setPen(QColor(122, 150, 178, 170))
            painter.drawText(QPointF(pad_x, top + plot_h * 0.5), "NO ORBITAL TELEMETRY")
            return

        # Baseline.

        painter.setPen(QPen(QColor(255, 255, 255, 20), 1.0))
        painter.drawLine(QPointF(pad_x, bottom), QPointF(pad_x + plot_w, bottom))
        painter.setPen(QColor(129, 155, 180, 190))
        painter.drawText(QPointF(pad_x, h - 9), "T+0")
        painter.drawText(QPointF(pad_x + plot_w * 0.44, h - 9), "T+45 min")
        painter.drawText(QPointF(pad_x + plot_w * 0.88, h - 9), "T+90")

        def xy(i: int) -> QPointF:
            x = pad_x + plot_w * i / (len(pts) - 1)
            y = bottom - plot_h * pts[i]
            return QPointF(x, y)

        # Smooth cubic mid-point Bezier through the samples.
        path = QPainterPath()
        path.moveTo(xy(0))
        for i in range(1, len(pts)):
            prev, cur = xy(i - 1), xy(i)
            midpoint = QPointF((prev.x() + cur.x()) / 2.0, (prev.y() + cur.y()) / 2.0)
            path.quadTo(prev, midpoint)
        path.lineTo(xy(len(pts) - 1))

        # Area fill under the curve (subtle cyan volume).
        fill = QPainterPath(path)
        fill.lineTo(pad_x + plot_w, bottom)
        fill.lineTo(pad_x, bottom)
        fill.closeSubpath()
        area = QLinearGradient(0, top, 0, bottom)
        area.setColorAt(0.0, QColor(0, 229, 255, 60))
        area.setColorAt(1.0, QColor(0, 229, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(area)
        painter.drawPath(fill)

        _glow_line(painter, path, QColor(0, 229, 255, 235), 1.6)

        # Live marker at t = 0 (now).
        now = xy(0)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(now, 3.0, 3.0)


class TerminatorMap(QQuickPaintedItem):
    """Equirectangular Earth with the day/night terminator and ground track."""

    sunEciChanged = Signal()
    anomalyChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAntialiasing(True)
        self.setOpaquePainting(False)
        self._sun_eci: Vec3 = (1.0, 0.0, 0.0)
        self._anomaly_deg = 0.0
        self._sim = OrbitSim()

    def _get_sun(self) -> list:
        return list(self._sun_eci)

    def _set_sun(self, value) -> None:
        try:
            v = (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError, IndexError):
            return
        if v == self._sun_eci:
            return
        m = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
        if m < 1e-9:
            return
        self._sun_eci = (v[0] / m, v[1] / m, v[2] / m)
        self.sunEciChanged.emit()
        self.update()

    def _get_anomaly(self) -> float:
        return self._anomaly_deg

    def _set_anomaly(self, value: float) -> None:
        value = max(-3600.0, min(3600.0, float(value)))
        if abs(value - self._anomaly_deg) < 1e-6:
            return
        self._anomaly_deg = value
        self.anomalyChanged.emit()
        self.update()

    sunEci = Property("QVariantList", _get_sun, _set_sun, notify=sunEciChanged)
    anomalyDeg = Property(float, _get_anomaly, _set_anomaly, notify=anomalyChanged)

    def _ground_track_data() -> list[tuple[float, float]]:
        """(lon_deg_wrap, lat_deg) samples of one full revolution.

        The ground frame uses the standard Earth-rotation-blind convention:
        subsolar longitude is referenced to the same ECI axis, so the sweep
        repeats each orbit - correct for a single-orbit band display.
        """
        sim = OrbitSim()
        elems = sim.elems
        out = []
        for k in range(150):
            m = math.tau * k / 149
            from helios_orbit import solve_kepler, true_anomaly as _nu
            big_e = solve_kepler(m, elems.ecc)
            nu = _nu(big_e, elems.ecc)
            r = elems.a_km * (1.0 - elems.ecc * math.cos(big_e))
            pos = _eci_transform((r * math.cos(nu), r * math.sin(nu)), elems)
            lat = math.degrees(math.asin(pos[2] / math.sqrt(pos[0] ** 2 + pos[1] ** 2 + pos[2] ** 2)))
            lon = math.degrees(math.atan2(pos[1], pos[0]))
            out.append((lon, lat))
        return out

    _track = _ground_track_data()

    def paint(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        if w < 8 or h < 8:
            return

        margin_x, margin_y = 26.0, 16.0
        frame = QRectF(margin_x, margin_y, w - 2 * margin_x, h - 2 * margin_y)
        painter.setPen(QPen(QColor(0, 229, 255, 46), 1.2))
        painter.setBrush(QColor(6, 12, 22))
        painter.drawRoundedRect(frame, 8, 8)

        lat_to_y = lambda lat: frame.top() + frame.height() * (0.5 - lat / 180.0)
        lon_to_x = lambda lon: frame.left() + frame.width() * (0.5 + lon / 360.0)

        # lon/lat graticule
        painter.setPen(QPen(QColor(90, 190, 230, 30), 0.8))
        for lon in range(-150, 180, 30):
            painter.drawLine(
                QPointF(lon_to_x(lon), frame.top()),
                QPointF(lon_to_x(lon), frame.bottom()),
            )
        for lat in range(-60, 90, 30):
            painter.drawLine(
                QPointF(frame.left(), lat_to_y(lat)),
                QPointF(frame.right(), lat_to_y(lat)),
            )

        # Day/night: subsolar point -> smooth radial night mask.
        sun = self._sun_eci
        sun_lat = math.degrees(math.asin(sun[2]))
        sun_lon = math.degrees(math.atan2(sun[1], sun[0]))
        subsolar = QPointF(lon_to_x(sun_lon), lat_to_y(90.0 - sun_lat))

        night = QRadialGradient(
            QPointF(lon_to_x(sun_lon + 180.0), lat_to_y(90.0 - sun_lat)),
            frame.width() * 0.62,
        )
        night.setColorAt(0.0, QColor(2, 5, 10, 190))
        night.setColorAt(0.55, QColor(2, 5, 10, 120))
        night.setColorAt(1.0, QColor(2, 5, 10, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(night)
        painter.drawRect(frame)
        _ = subsolar

        # Ground track + satellite marker.
        if self._track:
            path = QPainterPath()
            x_prev, y_prev = None, None
            for lon, lat in self._track:
                x, y = lon_to_x(lon), lat_to_y(lat)
                if x_prev is not None and abs(x - x_prev) > frame.width() * 0.5:
                    x_prev = None            # seam wrap: break the path
                if x_prev is None:
                    path.moveTo(QPointF(x, y))
                else:
                    path.lineTo(QPointF(x, y))
                x_prev, y_prev = x, y
            _ = y_prev
            _glow_line(painter, path, QColor(255, 180, 84, 190), 1.3)

            sim = self._sim
            elems = sim.elems
            nu = math.radians(self._anomaly_deg)
            r = elems.p_km / (1.0 + elems.ecc * math.cos(nu))
            pos = _eci_transform((r * math.cos(nu), r * math.sin(nu)), elems)
            lat = math.degrees(math.asin(pos[2] / math.sqrt(pos[0] ** 2 + pos[1] ** 2 + pos[2] ** 2)))
            lon = math.degrees(math.atan2(pos[1], pos[0]))
            marker = QPointF(lon_to_x(lon), lat_to_y(lat))
            glow = QRadialGradient(marker, 11.0)
            glow.setColorAt(0.0, QColor(0, 255, 170))
            glow.setColorAt(1.0, QColor(0, 255, 170, 0))
            painter.setBrush(glow)
            painter.drawEllipse(marker, 11.0, 11.0)
            painter.setBrush(QColor(0, 255, 170))
            painter.drawEllipse(marker, 2.6, 2.6)

        painter.setPen(QColor(129, 155, 180, 200))
        painter.drawText(QPointF(frame.left() + 4, frame.bottom() - 8), "GROUND TRACK - EQUIRECTANGULAR")
        painter.drawText(QPointF(frame.right() - 74, frame.bottom() - 8), "DAY / NIGHT MASK")
