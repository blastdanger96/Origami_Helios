"""Neon live charts for the Helios QML dock.

Why a custom QQuickPaintedItem instead of embedding pyqtgraph
-------------------------------------------------------------
The dashboard needs three charts that (a) composite over the glass panels with
true transparency, (b) draw a soft glow rather than a flat 1 px stroke and
(c) sit inside a QML layout.  A pyqtgraph ``PlotWidget`` is a QGraphicsView:
embedding it needs a QQuickWidget host, brings its own opaque background and
axis chrome, and fights the scene graph.  At 600 points per series the curves
here cost well under a millisecond to draw, so QPainter is the simpler and
faster path.

The charts own no timer: the backend pushes samples at 10 Hz and each push
repaints only that chart.  Nothing burns CPU while telemetry is quiet.

Styling follows the Helios HUD: no gridlines, a single faint baseline, a tiny
scale label, glowing cyan for the optimizer, a dashed soft-white manual
baseline, electric green for the gradient norm, and a translucent fill that
shows the watts the optimizer is recovering over the frozen human command.
"""

from __future__ import annotations

import math
from collections import deque

from PySide6.QtCore import Property, QPointF, QRectF, Qt, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtQuick import QQuickPaintedItem

WINDOW_SECONDS = 60.0

CYAN = QColor(0, 229, 255)
GREEN = QColor(0, 255, 136)
SOFT_WHITE = QColor(226, 240, 252)


class LiveChart(QQuickPaintedItem):
    """One scrolling telemetry chart: ``kind`` selects the scale and colours."""

    kindChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAntialiasing(True)
        self.setOpaquePainting(False)
        self.setClip(True)
        self.setFillColor(QColor(0, 0, 0, 0))
        self._kind = "power"
        self._data: deque[tuple[float, float, float]] = deque(maxlen=1000)
        self._font = QFont(QGuiApplication.font())
        self._font.setPixelSize(9)
        self._font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)

    # ------------------------------------------------------------------ #
    # QML interface
    # ------------------------------------------------------------------ #

    def _get_kind(self) -> str:
        return self._kind

    def _set_kind(self, value: str) -> None:
        value = str(value)
        if value == self._kind:
            return
        self._kind = value
        self._data.clear()
        self.kindChanged.emit()
        self.update()

    kind = Property(str, _get_kind, _set_kind, notify=kindChanged)

    @Slot(float, float, float)
    def append(self, t: float, manual: float, auto: float) -> None:
        """Add one sample; ``manual`` is the operator baseline."""
        if not all(math.isfinite(v) for v in (t, manual, auto)):
            return
        self._data.append((float(t), float(manual), float(auto)))
        self.update()

    @Slot()
    def clear(self) -> None:
        self._data.clear()
        self.update()

    # ------------------------------------------------------------------ #
    # Scales
    # ------------------------------------------------------------------ #

    def _range(self) -> tuple[float, float, str]:
        if self._kind == "theta":
            return 0.0, 90.0, "0 - 90 deg"
        if self._kind == "grad":
            return -10.0, 3.0, "1e-10 - 1e3"
        return 0.0, 4600.0, "0 - 4.6 kW"

    def _map_value(self, value: float) -> float:
        lo, hi, _ = self._range()
        if self._kind == "grad":
            value = math.log10(max(value, 1e-10))
        value = max(lo, min(hi, value))
        return (value - lo) / (hi - lo)

    # ------------------------------------------------------------------ #
    # Painting helpers
    # ------------------------------------------------------------------ #

    def _line(
        self,
        painter: QPainter,
        points: list,
        color: QColor,
        width: float,
        glow: bool,
    ) -> None:
        if len(points) < 2:
            return
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)

        if glow:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            for extra, alpha in ((5.5, 16), (3.0, 38)):
                halo = QColor(color)
                halo.setAlpha(alpha)
                pen = QPen(halo, width + extra)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        core = QColor(color)
        core.setAlpha(235)
        pen = QPen(core, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _endpoint(self, painter: QPainter, point: QPointF, color: QColor) -> None:
        glow = QRadialGradient(point, 9.0)
        glow.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 150))
        glow.setColorAt(0.45, QColor(color.red(), color.green(), color.blue(), 45))
        glow.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(point, 9.0, 9.0)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setBrush(QColor(240, 252, 255, 245))
        painter.drawEllipse(point, 2.1, 2.1)

    # ------------------------------------------------------------------ #
    # Paint
    # ------------------------------------------------------------------ #

    def paint(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        if w < 24.0 or h < 24.0 or not self._data:
            return

        left, right = 2.0, w - 5.0
        top, bottom = 15.0, h - 12.0
        plot_w, plot_h = right - left, bottom - top
        if plot_w <= 4.0 or plot_h <= 4.0:
            return

        data = list(self._data)
        t_last = data[-1][0]
        if t_last < WINDOW_SECONDS:
            t0, t1 = 0.0, WINDOW_SECONDS
        else:
            t0, t1 = t_last - WINDOW_SECONDS, t_last
        span = max(t1 - t0, 1e-6)

        def px(t: float) -> float:
            return left + max(0.0, min(1.0, (t - t0) / span)) * plot_w

        def py(v: float) -> float:
            return bottom - self._map_value(v) * plot_h

        visible = [row for row in data if row[0] >= t0 - 0.25]
        if not visible:
            return

        auto_points = [QPointF(px(t), py(auto)) for t, _, auto in visible]
        manual_points = [QPointF(px(t), py(manual)) for t, manual, _ in visible]

        painter.save()
        painter.setClipRect(QRectF(left, 0.0, plot_w + 2.0, h))
        painter.setFont(self._font)
        scale_text = self._range()[2]

        # --- baseline (not a gridline: the only axis chrome in the design) ---
        baseline = QLinearGradient(left, 0.0, right, 0.0)
        baseline.setColorAt(0.0, QColor(255, 255, 255, 8))
        baseline.setColorAt(0.55, QColor(255, 255, 255, 22))
        baseline.setColorAt(1.0, QColor(0, 229, 255, 46))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(baseline)
        painter.drawRect(QRectF(left, bottom + 1.0, plot_w, 1.0))

        # --- AI advantage band, drawn under the curves ---
        if self._kind == "power" and len(auto_points) >= 2:
            band = QPainterPath(auto_points[0])
            for point in auto_points[1:]:
                band.lineTo(point)
            for point in reversed(manual_points):
                band.lineTo(point)
            band.closeSubpath()
            fill = QLinearGradient(0.0, top, 0.0, bottom)
            fill.setColorAt(0.0, QColor(0, 229, 255, 30))
            fill.setColorAt(1.0, QColor(0, 229, 255, 4))
            painter.setBrush(fill)
            painter.drawPath(band)

        # --- manual baseline: dashed, deliberately quieter than the solver ---
        if self._kind != "grad":
            manual_pen = QPen(QColor(210, 226, 242, 120), 1.15)
            manual_pen.setStyle(Qt.PenStyle.DashLine)
            manual_pen.setDashPattern([3.0, 3.0])
            painter.setPen(manual_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath(manual_points[0])
            for point in manual_points[1:]:
                path.lineTo(point)
            painter.drawPath(path)

        accent = GREEN if self._kind == "grad" else CYAN
        self._line(painter, auto_points, accent, 1.6, glow=True)
        self._endpoint(painter, auto_points[-1], accent)

        # --- scale + window labels ---
        painter.setPen(QColor(150, 172, 194, 120))
        painter.drawText(QRectF(left, 1.0, plot_w, 11.0), Qt.AlignmentFlag.AlignLeft, scale_text)
        painter.setPen(QColor(140, 162, 184, 95))
        painter.drawText(
            QRectF(left, h - 11.0, 52.0, 10.0),
            Qt.AlignmentFlag.AlignLeft,
            "-60 s",
        )
        painter.setPen(QColor(0, 229, 255, 150))
        painter.drawText(
            QRectF(right - 52.0, h - 11.0, 52.0, 10.0),
            Qt.AlignmentFlag.AlignRight,
            "NOW",
        )
        painter.restore()
