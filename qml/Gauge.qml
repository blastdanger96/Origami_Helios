// Spaceship-HUD radial gauge: 270 deg donut arc with a glow shadow on the
// value sweep, a white capture tick at the arc head, and a big thin number in
// the hole.  `value` is clamped 0..1; `text` is whatever the caller formats.
import QtQuick

Item {
    id: g

    property real value: 0
    property string valueText: "--"
    property string caption: ""
    property color tint: "#00E5FF"

    width: 118
    height: width + 30

    onValueChanged: arc.requestPaint()
    onTintChanged: arc.requestPaint()

    Canvas {
        id: arc
        width: g.width
        height: g.width
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var cx = width / 2
            var cy = height / 2
            var r = width / 2 - 9
            var start = Math.PI * 0.75
            var sweep = Math.PI * 1.5

            ctx.lineWidth = 7
            ctx.lineCap = "round"
            ctx.strokeStyle = "rgba(255, 255, 255, 0.07)"
            ctx.beginPath()
            ctx.arc(cx, cy, r, start, start + sweep)
            ctx.stroke()

            var v = Math.max(0, Math.min(1, g.value))
            if (v > 0.004) {
                var grad = ctx.createLinearGradient(0, 0, width, height)
                grad.addColorStop(0, "" + g.tint)
                grad.addColorStop(1, "#9BF3FF")

                ctx.shadowColor = Qt.rgba(g.tint.r, g.tint.g, g.tint.b, 0.55)
                ctx.shadowBlur = 12
                ctx.strokeStyle = grad
                ctx.beginPath()
                ctx.arc(cx, cy, r, start, start + sweep * v)
                ctx.stroke()
                ctx.shadowBlur = 0

                var head = start + sweep * v
                ctx.fillStyle = "rgba(240, 252, 255, 0.95)"
                ctx.beginPath()
                ctx.arc(cx + r * Math.cos(head), cy + r * Math.sin(head), 2.6, 0, Math.PI * 2)
                ctx.fill()
            }
        }
    }

    Text {
        anchors.centerIn: arc
        anchors.verticalCenterOffset: -2
        color: "#E8F2FC"
        font.family: "SF Mono"
        font.weight: Font.Thin
        font.pixelSize: 22
        text: g.valueText
    }

    Text {
        anchors.horizontalCenter: arc.horizontalCenter
        anchors.top: arc.verticalCenter
        anchors.topMargin: 12
        color: "#62798F"
        font.family: "SF Pro Display"
        font.pixelSize: 8
        font.letterSpacing: 2.2
        text: g.caption
    }
}
