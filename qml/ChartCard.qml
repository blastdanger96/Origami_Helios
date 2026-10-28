// Chart card for the bottom dock: glass tile + small-caps title + the custom
// transparent LiveChart painted item from helios_charts.py.
import QtQuick
import Helios 1.0

Rectangle {
    id: card

    property string kind: "power"
    property string note: ""
    property alias title: titleText.text
    property alias chart: chartItem

    radius: 12
    color: "#590F141E"
    border.color: "#14FFFFFF"
    border.width: 1

    Text {
        id: titleText
        x: 12
        y: 9
        color: "#9FB6CC"
        font.family: "SF Pro Display"
        font.pixelSize: 9
        font.letterSpacing: 2.0
        text: "CHART"
    }

    Text {
        id: noteText
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.top: parent.top
        anchors.topMargin: 9
        color: "#62798F"
        font.family: "SF Mono"
        font.pixelSize: 8
        text: card.note
    }

    LiveChart {
        id: chartItem
        kind: card.kind
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.topMargin: 24
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 6
        anchors.leftMargin: 6
        anchors.rightMargin: 6
    }
}
