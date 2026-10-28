// Pulsing status pill, e.g. "AUTOPILOT ENGAGED" (cyan) vs "MANUAL CONTROL"
// (red).  The blinking dot is the only animation here — cheap and legible.
import QtQuick

Rectangle {
    id: pill

    property alias label: txt.text
    property bool active: true
    property color tint: active ? "#00E5FF" : "#FF4D6A"

    width: row.implicitWidth + 24
    height: 22
    radius: 11
    color: Qt.rgba(tint.r, tint.g, tint.b, 0.12)
    border.color: Qt.rgba(tint.r, tint.g, tint.b, 0.45)
    border.width: 1

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 7

        Rectangle {
            width: 6
            height: 6
            radius: 3
            color: pill.tint
            anchors.verticalCenter: parent.verticalCenter

            SequentialAnimation on opacity {
                loops: Animation.Infinite
                NumberAnimation { from: 1.0; to: 0.2; duration: 650 }
                NumberAnimation { from: 0.2; to: 1.0; duration: 650 }
            }
        }

        Text {
            id: txt
            color: pill.tint
            font.family: "SF Pro Display"
            font.pixelSize: 9
            font.letterSpacing: 1.8
            text: "LIVE"
        }
    }
}
