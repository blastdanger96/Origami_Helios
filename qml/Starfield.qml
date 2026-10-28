// Full-window deep-space backdrop: three soft nebulas and a twinkling
// starfield.  Painted once per 160 ms only (twinkle tick) — it sits under the
// glass panels, so it must stay cheap.
import QtQuick

Canvas {
    id: root

    property int starCount: 170
    property real twinkle: 0.0
    property var stars: []

    onStarCountChanged: rebuild()
    onWidthChanged: rebuild()
    onHeightChanged: rebuild()
    onStarsChanged: requestPaint()

    Component.onCompleted: rebuild()

    function rebuild() {
        var list = []
        var seed = 20261028
        var rnd = function() {
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            return seed / 0x7fffffff
        }
        for (var i = 0; i < starCount; ++i) {
            list.push({
                x: rnd(),
                y: rnd(),
                r: 0.4 + 1.6 * rnd(),
                a: 0.12 + 0.72 * rnd(),
                p: rnd() * Math.PI * 2,
                sp: 0.3 + 1.6 * rnd()
            })
        }
        stars = list
    }

    Timer {
        interval: 160
        running: true
        repeat: true
        onTriggered: {
            root.twinkle += 0.16
            root.requestPaint()
        }
    }

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        ctx.clearRect(0, 0, width, height)

        var nebulas = [
            [0.16, 0.22, 0.50, "rgba(38, 74, 160, 0.13)"],
            [0.85, 0.12, 0.40, "rgba(96, 40, 150, 0.10)"],
            [0.62, 0.88, 0.45, "rgba(16, 96, 130, 0.08)"]
        ]
        for (var n = 0; n < nebulas.length; ++n) {
            var cx = width * nebulas[n][0]
            var cy = height * nebulas[n][1]
            var rad = Math.max(width, height) * nebulas[n][2]
            var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, rad)
            g.addColorStop(0, nebulas[n][3])
            g.addColorStop(1, "rgba(0, 0, 0, 0)")
            ctx.fillStyle = g
            ctx.fillRect(0, 0, width, height)
        }

        ctx.fillStyle = "#D7ECFF"
        for (var i = 0; i < stars.length; ++i) {
            var st = stars[i]
            var tw = 0.65 + 0.35 * Math.sin(root.twinkle * st.sp + st.p)
            ctx.globalAlpha = st.a * tw
            ctx.beginPath()
            ctx.arc(st.x * width, st.y * height, st.r, 0, Math.PI * 2)
            ctx.fill()
        }
        ctx.globalAlpha = 1
    }
}
