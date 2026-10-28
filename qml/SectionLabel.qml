// Small-caps panel header with a cyan tick, e.g. "AI INSIGHTS".
import QtQuick

Row {
    id: root

    property alias text: label.text
    property color accent: "#00E5FF"

    spacing: 8

    Rectangle {
        width: 3
        height: 12
        radius: 1.5
        color: root.accent
        anchors.verticalCenter: parent.verticalCenter
    }

    Text {
        id: label
        color: "#9FB6CC"
        font.family: "SF Pro Display"
        font.pixelSize: 10
        font.letterSpacing: 2.6
        text: "SECTION"
    }
}
