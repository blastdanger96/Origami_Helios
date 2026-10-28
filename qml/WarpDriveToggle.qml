// WarpDriveToggle — ORBITAL DRIVE on/off (Keplerian LVLH sun drive).
//
// Mirrors the autopilot toggle in the telemetry view so both panels read
// as one design language. Binds to backend.orbitMode; the toggle animates
// on the GUI thread and the worker applies the mode via a queued slot.
import QtQuick

Item {
    id: root

    width: 266
    height: 26

    Text {
        anchors.verticalCenter: parent.verticalCenter
        color: "#9FB6CC"
        font.family: "SF Pro Display"
        font.pixelSize: 10
        font.letterSpacing: 2.0
        text: "ORBITAL DRIVE"
    }

    Rectangle {
        id: driveTrack
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: 44
        height: 24
        radius: 12
        color: backend.orbitMode ? "#2E00E5FF" : "#2EFFFFFF"
        border.color: backend.orbitMode ? "#6600E5FF" : "#33FFFFFF"
        border.width: 1

        Rectangle {
            x: backend.orbitMode ? driveTrack.width - width - 3 : 3
            anchors.verticalCenter: parent.verticalCenter
            width: 18
            height: 18
            radius: 9
            color: backend.orbitMode ? "#EAF6FF" : "#8FA6BC"

            Behavior on x { NumberAnimation { duration: 120 } }
        }

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: backend.orbitMode = !backend.orbitMode
        }
    }
}
