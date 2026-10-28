// Glowing glass slider: label row on top, 4 px groove with a cyan gradient
// fill, white handle with a tinted ring, and click-or-drag anywhere on the
// track.  Emits sliderMoved(value) while dragging; the two-way data flow
// (QML -> backend -> QML) is wired in Main.qml via Connections.
import QtQuick

Item {
    id: root

    property real from: 0
    property real to: 100
    property real value: from
    property string label: ""
    property string valueLabel: ""
    property color tint: "#00E5FF"
    readonly property bool pressed: area.pressed
    readonly property real fraction: to > from ? Math.max(0, Math.min(1, (value - from) / (to - from))) : 0

    signal sliderMoved(real val)

    width: 250
    height: 46

    function setFromX(x) {
        var f = Math.max(0, Math.min(1, x / track.width))
        var v = from + f * (to - from)
        if (Math.abs(v - value) > (to - from) * 1e-4) {
            value = v
            sliderMoved(v)
        }
    }

    Text {
        x: 1
        y: 0
        color: "#9FB6CC"
        font.family: "SF Pro Display"
        font.pixelSize: 10
        font.letterSpacing: 2.0
        text: root.label
    }

    Text {
        anchors.right: parent.right
        y: 0
        color: root.tint
        font.family: "SF Mono"
        font.pixelSize: 11
        text: root.valueLabel
    }

    Item {
        id: track
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 24

        Rectangle {
            id: groove
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            height: 4
            radius: 2
            color: "#14FFFFFF"
        }

        Rectangle {
            id: fill
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(2, root.fraction * track.width)
            height: 4
            radius: 2
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "#1200E5FF" }
                GradientStop { position: 1.0; color: root.tint }
            }
        }

        Rectangle {
            id: halo
            anchors.centerIn: handle
            width: 26
            height: 26
            radius: 13
            visible: root.pressed
            color: Qt.rgba(root.tint.r, root.tint.g, root.tint.b, 0.18)
        }

        Rectangle {
            id: handle
            anchors.verticalCenter: parent.verticalCenter
            x: root.fraction * (track.width - width)
            width: 15
            height: 15
            radius: 7.5
            color: "#EAF6FF"
            border.color: root.tint
            border.width: 2

            Behavior on x { NumberAnimation { duration: 60 } }
        }

        MouseArea {
            id: area
            anchors.fill: parent
            anchors.topMargin: -6
            anchors.bottomMargin: -6
            cursorShape: Qt.PointingHandCursor
            onPressed: root.setFromX(mouse.x)
            onPositionChanged: if (pressed) root.setFromX(mouse.x)
        }
    }
}
