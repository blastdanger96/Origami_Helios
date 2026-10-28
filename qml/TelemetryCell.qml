// Label / value readout row used under the gauges.
import QtQuick

Row {
    id: cell

    property alias label: lab.text
    property alias text: val.text
    property color tint: "#E8F2FC"

    spacing: 8

    Text {
        id: lab
        color: "#6E869E"
        font.family: "SF Pro Display"
        font.pixelSize: 9
        font.letterSpacing: 1.6
        text: "LABEL"
    }

    Text {
        id: val
        color: cell.tint
        font.family: "SF Mono"
        font.pixelSize: 11
        text: "--"
    }
}
