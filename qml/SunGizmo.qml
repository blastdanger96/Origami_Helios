// Sun-vector orientation gizmo: a top-down orbit ring, the projected
// equator plane, a satellite glyph in the middle, and the sun bead on the
// ring at the operator's (azimuth, elevation).  Pure Canvas — no bindings
// heavier than two property repaints.
import QtQuick

Canvas {
    id: gizmo

    property real azimuth: 0        // degrees 0..360
    property real elevation: 30     // degrees 0..90
    property color sunTint: "#FFC24D"

    width: 220
    height: 132
    antialiasing: true

    onAzimuthChanged: requestPaint()
    onElevationChanged: requestPaint()
    onWidthChanged: requestPaint()

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        var cx = width / 2
        var cy = height / 2
        var R = Math.min(width, height) / 2 - 16

        // Reachable hemisphere ring.
        ctx.lineWidth = 1
        ctx.strokeStyle = "rgba(255, 255, 255, 0.13)"
        ctx.beginPath()
        ctx.arc(cx, cy, R, 0, Math.PI * 2)
        ctx.stroke()

        // Projected equator (elevation = 0 circle).
        ctx.strokeStyle = "rgba(0, 229, 255, 0.28)"
        ctx.beginPath()
        ctx.ellipse(cx, cy, R, R * 0.34, 0, 0, Math.PI * 2)
        ctx.stroke()

        // Satellite glyph (rotated square) at the origin.
        ctx.save()
        ctx.translate(cx, cy)
        ctx.rotate(Math.PI / 4)
        ctx.fillStyle = "rgba(20, 30, 44, 0.9)"
        ctx.strokeStyle = "rgba(230, 245, 255, 0.85)"
        ctx.lineWidth = 1.2
        ctx.beginPath()
        ctx.rect(-5, -5, 10, 10)
        ctx.fill()
        ctx.stroke()
        ctx.restore()

        // Sun vector bead: x = cos(el) sin(az), y = -sin(el); depth along the
        // view axis decides whether the bead renders in front of or behind
        // the ring (front = brighter + bigger).
        var az = azimuth * Math.PI / 180
        var el = elevation * Math.PI / 180
        var px = Math.cos(el) * Math.sin(az) * R
        var py = -Math.sin(el) * R
        var depth = Math.cos(el) * Math.cos(az)      // +1 = in front of page
        var front = depth >= 0

        ctx.setLineDash([3, 3])
        ctx.lineWidth = 1
        ctx.strokeStyle = Qt.rgba(sunTint.r, sunTint.g, sunTint.b, front ? 0.8 : 0.3)
        ctx.beginPath()
        ctx.moveTo(cx, cy)
        ctx.lineTo(cx + px, cy + py)
        ctx.stroke()
        ctx.setLineDash([])

        var radius = front ? 5.5 : 4.0
        var alpha = front ? 0.95 : 0.35
        ctx.fillStyle = Qt.rgba(sunTint.r, sunTint.g, sunTint.b, alpha)
        ctx.shadowColor = Qt.rgba(sunTint.r, sunTint.g, sunTint.b, alpha * 0.7)
        ctx.shadowBlur = 10
        ctx.beginPath()
        ctx.arc(cx + px, cy + py, radius, 0, Math.PI * 2)
        ctx.fill()
        ctx.shadowBlur = 0

        // Caption inside the ring.
        ctx.fillStyle = "rgba(110, 134, 158, 0.9)"
        ctx.font = "9px 'SF Pro Display'"
        ctx.textAlign = "left"
        ctx.fillText("SUN VECTOR", 10, height - 8)
        ctx.fillStyle = "rgba(255, 194, 77, 0.9)"
        ctx.textAlign = "right"
        ctx.fillText(elevation.toFixed(0) + "\u00B0 EL  /  " + ((azimuth % 360).toFixed(0)) + "\u00B0 AZ", width - 10, height - 8)
    }
}
