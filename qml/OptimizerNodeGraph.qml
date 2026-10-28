// OptimizerNodeGraph — structural forward/backward pass diagram.
//
// Pure-QML structural view: four capsule nodes (SUN VECTOR → MIURA GEOMETRY
// → ADAM STEP → θ COMMAND) wired by cyan connectors, with a dashed backward
// edge (the gradient) flowing the other way. Connector pulses mirror the
// optimizer's live state: the forward pulses stop when the loop settles and
// thicken/tint orange under manual authority, so the *graph itself* is a
// live telemetry surface rather than a static decoration.
import QtQuick
import "Theme.js" as Theme

Item {
    id: root

    width: 266
    height: 150

    // Node payloads: label + tiny mono caption.
    property var nodes: [
        ["SUN VECTOR", "sun \u00E2  LVLH"],
        ["MIURA GEOMETRY", "dP/d\u03B8"],
        ["ADAM STEP", "z \u00E2 \u03B8"],
        ["\u03B8 COMMAND", "array"
        ]
    ]

    function flowColor() {
        if (!backend.autopilot) return "#FFB454"          // manual: orange
        if (optimizer.settled) return "#4FB6A8"           // settled: muted teal
        return "#00E5FF"                                  // descending: cyan
    }

    Column {
        id: nodeCol
        anchors.fill: parent
        spacing: 4

        Repeater {
            model: root.nodes

            Item {
                width: nodeCol.width
                height: 26

                // Forward connector (below the node except for the last).
                Rectangle {
                    visible: index < root.nodes.length - 1
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    width: 2
                    height: nodeCol.spacing + 2
                    color: root.flowColor()
                    opacity: 0.55

                    SequentialAnimation on opacity {
                        loops: Animation.Infinite
                        running: backend.autopilot && !optimizer.settled
                        NumberAnimation { from: 0.2; to: 0.95; duration: 700 }
                        NumberAnimation { from: 0.95; to: 0.2; duration: 700 }
                    }
                }

                Rectangle {
                    id: capsule
                    anchors.verticalCenter: parent.verticalCenter
                    x: 14
                    width: parent.width - 62
                    height: 24
                    radius: 12
                    color: "#140F1E30"
                    border.color: root.flowColor()
                    border.width: 1

                    Text {
                        x: 10
                        anchors.verticalCenter: parent.verticalCenter
                        color: "#D9ECF7"
                        font.family: "SF Pro Display"
                        font.pixelSize: 10
                        font.letterSpacing: 1.6
                        text: modelData[0]
                    }

                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        color: "#62798F"
                        font.family: "SF Mono"
                        font.pixelSize: 9
                        text: modelData[1]
                    }
                }

                // Index badge.
                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 2
                    anchors.verticalCenter: parent.verticalCenter
                    color: "#3D5468"
                    font.family: "SF Mono"
                    font.pixelSize: 9
                    text: index
                }

                // Backward (gradient) edge stub on the right: direction shown
                // by a small chevron pointing UP (backward pass).
                Text {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    color: "#FF8A4D"
                    font.family: "SF Mono"
                    font.pixelSize: 11
                    text: index === 0 ? "\u2571" : (index === root.nodes.length - 1 ? "\u2572" : "\u2191")
                }
            }
        }
    }

    // Backward-edge rail: a dashed vertical line linking each stub.
    Rectangle {
        anchors.right: parent.right
        anchors.rightMargin: 8
        y: 10
        width: 1
        height: parent.height - 20
        color: "#33FF8A4D"
    }

    Text {
        anchors.right: parent.right
        anchors.rightMargin: 14
        anchors.top: parent.top
        color: "#66FF8A4D"
        font.family: "SF Mono"
        font.pixelSize: 8
        font.letterSpacing: 1.4
        text: "BACKWARD PASS"
    }
}
