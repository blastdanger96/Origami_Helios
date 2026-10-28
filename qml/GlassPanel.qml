// The single glassmorphism primitive: translucent dark fill, 1 px white-10%
// border, 16 px radius and a diagonal sheen that sells the "glass" without a
// real blur pass (no >-Essentials effect modules required).
import QtQuick

Rectangle {
    id: panel

    default property alias contentData: inner.data
    property real pad: 16

    radius: 16
    color: "#990F141E"                      // rgba(15, 20, 30, 0.60)
    border.color: "#1AFFFFFF"
    border.width: 1

    // Diagonal sheen: bright top-left, fading to nothing.
    Rectangle {
        anchors.fill: parent
        radius: panel.radius
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#10FFFFFF" }
            GradientStop { position: 0.28; color: "#04FFFFFF" }
            GradientStop { position: 0.6; color: "#00000000" }
            GradientStop { position: 1.0; color: "#33000000" }
        }
    }

    Item {
        id: inner
        anchors.fill: parent
        anchors.margins: panel.pad
    }
}
