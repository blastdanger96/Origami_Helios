// PROJECT HELIOS — cinematic mission-control layout.
//
// Structure: full-window deep-space starfield; the satellite viewport below a
// glass top bar; floating "Mission Telemetry" (left) and "Control Authority"
// (right) glass panels; a three-chart glass dock across the bottom.  The
// viewport keeps rendering *behind* the panels so the glass reads as glass.
import QtQuick
import QtQuick.Window
import Helios 1.0
import "Theme.js" as Theme

Window {
    id: windowRoot

    visible: true
    title: "PROJECT HELIOS"
    width: 1440
    height: 880
    minimumWidth: 1180
    minimumHeight: 760
    color: "#04070D"

    // Mission view state: 0 = TELEMETRY, 1 = ORBITAL MECHANICS, 2 = AI OPTIMIZER.
    property int viewState: 0

    function switchView(to) {
        if (to === viewState) return
        viewState = to
    }

    // Left/right glass panels share one slide+fade transition driven by viewState.
    property real panelOpacity: viewState === -1 ? 0 : 1
    property real panelOffset: 0

    // ------------------------------------------------------------------ //
    // Deep space backdrop
    // ------------------------------------------------------------------ //
    Starfield {
        anchors.fill: parent
    }

    // ------------------------------------------------------------------ //
    // Top navigation bar
    // ------------------------------------------------------------------ //
    Rectangle {
        id: header
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 54
        color: "#660A0E16"
        border.width: 0

        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: "#1AFFFFFF"
        }

        // Logo: glowing chip with mono-caps wordmark.
        Rectangle {
            x: 22
            y: 12
            width: 208
            height: 31
            radius: 15
            color: "#1600E5FF"
            border.color: "#3D00E5FF"
            border.width: 1

            Text {
                anchors.centerIn: parent
                color: "#00E5FF"
                font.family: "SF Pro Display"
                font.pixelSize: 12
                font.letterSpacing: 3.6
                text: "\u25C9  PROJECT HELIOS"
            }
        }

        // Center nav — three working tabs switching the central view.
        property string activeTab: "TELEMETRY"

        Row {
            id: navRow
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            spacing: 28

            Repeater {
                model: ["TELEMETRY", "ORBITAL MECHANICS", "AI OPTIMIZER"]

                Item {
                    width: Math.max(linkText.width, 110)
                    height: 34

                    MouseArea {
                        id: navHit
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        hoverEnabled: true
                        onClicked: {
                            var idx = ["TELEMETRY", "ORBITAL MECHANICS", "AI OPTIMIZER"].indexOf(modelData)
                            windowRoot.switchView(idx)
                        }
                    }

                    Text {
                        id: linkText
                        color: {
                            var idx = ["TELEMETRY", "ORBITAL MECHANICS", "AI OPTIMIZER"].indexOf(modelData)
                            return idx === windowRoot.viewState
                                    ? "#00E5FF"
                                    : (navHit.containsMouse ? "#BFD9EE" : "#62798F")
                        }
                        font.family: "SF Pro Display"
                        font.pixelSize: 10
                        font.letterSpacing: 2.4
                        text: modelData
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Rectangle {
                        id: navUnderline
                        visible: ["TELEMETRY", "ORBITAL MECHANICS", "AI OPTIMIZER"].indexOf(modelData) === windowRoot.viewState
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.top: linkText.bottom
                        anchors.topMargin: 3
                        width: linkText.width + 8
                        height: 2
                        radius: 1
                        color: "#00E5FF"

                        // Glow halo under the active tab.
                        Rectangle {
                            visible: parent.visible
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width * 2
                            height: 8
                            radius: 4
                            color: "#2600E5FF"
                        }
                    }
                }
            }
        }

        // Simulated system status.
        Row {
            anchors.right: parent.right
            anchors.rightMargin: 22
            anchors.verticalCenter: parent.verticalCenter
            spacing: 18

            Repeater {
                model: ["PWR", "LINK", "THERM"]

                Row {
                    spacing: 6

                    Rectangle {
                        width: 7
                        height: 7
                        radius: 3.5
                        color: index === 2 ? "#FFB454" : "#00FF88"
                        anchors.verticalCenter: parent.verticalCenter

                        SequentialAnimation on opacity {
                            loops: Animation.Infinite
                            NumberAnimation { from: 1.0; to: 0.35; duration: 900 }
                            NumberAnimation { from: 0.35; to: 1.0; duration: 900 }
                        }
                    }

                    Text {
                        color: "#9FB6CC"
                        font.family: "SF Pro Display"
                        font.pixelSize: 9
                        font.letterSpacing: 1.6
                        text: modelData
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------------ //
    // Center stage: three swap views (telemetry is live; orbit & AI mount
    // their engines in Phases 2 and 3). Cross-fade instead of hard cutoff.
    // ------------------------------------------------------------------ //
    Item {
        id: viewport
        anchors.top: header.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: dock.top
        anchors.bottomMargin: 16

        // ---- View 0: Telemetry ----------------------------------------- //
        Item {
            id: viewTelemetry
            anchors.fill: parent
            opacity: windowRoot.viewState === 0 ? 1 : 0
            visible: opacity > 0.01
            scale: windowRoot.viewState === 0 ? 1.0 : 0.985

            Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
            Behavior on scale {
                NumberAnimation {
                    duration: 260
                    easing.type: Easing.OutCubic
                }
            }

            SatelliteView {
                id: sat
                objectName: "satelliteView"
                anchors.fill: parent
                sunAzimuth: backend.sunAzimuth
                sunElevation: backend.sunElevation
                thetaDeg: backend.theta
                spin: true
            }

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                property real lastX: 0
                property real lastY: 0
                onPressed: { lastX = mouse.x; lastY = mouse.y }
                onPositionChanged: {
                    if (pressed) {
                        sat.orbit(mouse.x - lastX, mouse.y - lastY)
                        lastX = mouse.x
                        lastY = mouse.y
                    }
                }
                onReleased: sat.resume_spin()
            }
        }

        // ---- View 1: Orbital Mechanics (Phase 2 engine mounts here) ----- //
        Item {
            id: viewOrbit
            anchors.fill: parent
            opacity: windowRoot.viewState === 1 ? 1 : 0
            visible: opacity > 0.01

            Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

            Rectangle {
                anchors.centerIn: parent
                width: 420
                height: 96
                radius: 16
                color: "#990F141E"
                border.color: "#1AFFFFFF"
                border.width: 1

                Column {
                    anchors.centerIn: parent
                    spacing: 6

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        color: "#00E5FF"
                        font.family: "SF Pro Display"
                        font.pixelSize: 13
                        font.letterSpacing: 3.0
                        text: "ORBITAL MECHANICS"
                    }

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        color: "#62798F"
                        font.family: "SF Mono"
                        font.pixelSize: 10
                        font.letterSpacing: 1.4
                        text: "KEPLERIAN ENGINE MOUNTS IN PHASE 2"
                    }
                }
            }
        }

        // ---- View 2: AI Optimizer (Phase 3 landscape mounts here) ------- //
        Item {
            id: viewAI
            anchors.fill: parent
            opacity: windowRoot.viewState === 2 ? 1 : 0
            visible: opacity > 0.01

            Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

            Rectangle {
                anchors.centerIn: parent
                width: 420
                height: 96
                radius: 16
                color: "#990F141E"
                border.color: "#1AFFFFFF"
                border.width: 1

                Column {
                    anchors.centerIn: parent
                    spacing: 6

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        color: "#00FF88"
                        font.family: "SF Pro Display"
                        font.pixelSize: 13
                        font.letterSpacing: 3.0
                        text: "AI OPTIMIZER"
                    }

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        color: "#62798F"
                        font.family: "SF Mono"
                        font.pixelSize: 10
                        font.letterSpacing: 1.4
                        text: "ADAM STATE VISUALIZER MOUNTS IN PHASE 3"
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------------ //
    // Left panel — Mission Telemetry / AI insights
    // ------------------------------------------------------------------ //
    GlassPanel {
        id: leftPanel
        objectName: "leftPanel"
        anchors.top: header.bottom
        anchors.left: parent.left
        anchors.topMargin: 16
        width: 298
        height: contentCol.implicitHeight + 34
        z: 15

        // Panel transitions: slide+fade on view changes (anchored via margin
        // so the anchor system and the animation system never disagree).
        opacity: windowRoot.viewState === 0 ? 1.0 : 0.0
        Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
        anchors.leftMargin: windowRoot.viewState === 0 ? 16 : -340
        Behavior on anchors.leftMargin { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }

        Column {
            id: contentCol
            width: parent.width
            spacing: 12

            SectionLabel { text: "MISSION TELEMETRY" }

            Row {
                spacing: 14

                Gauge {
                    value: Math.max(0, Math.min(1, backend.power / Theme.maxPowerApprox))
                    valueText: Theme.fmtW(backend.power)
                    caption: "OUTPUT POWER"
                    tint: "#00E5FF"
                }

                Gauge {
                    value: Math.max(0, Math.min(1, Math.abs(backend.advantage) / Theme.maxPowerApprox))
                    valueText: Theme.fmtW(backend.advantage)
                    caption: "AI ADVANTAGE"
                    tint: "#00FF88"
                }
            }

            SectionLabel { text: "OPTIMIZER" }

            TelemetryCell {
                label: "GRADIENT NORM"
                text: Theme.sci(backend.gradNorm)
            }

            TelemetryCell {
                label: "INCIDENCE  cos\u03B8"
                text: backend.incidence.toFixed(3)
                tint: "#9BF3FF"
            }

            TelemetryCell {
                label: "FACET TILT  \u03C8"
                text: Theme.fmtDeg(backend.psi)
            }

            TelemetryCell {
                label: "MISSION CLOCK"
                text: Theme.fmtMet(backend.met)
                tint: "#62798F"
            }

            LivePill {
                label: backend.autopilot ? "AUTOPILOT ENGAGED" : "MANUAL CONTROL"
                active: backend.autopilot
            }
        }
    }

    // ------------------------------------------------------------------ //
    // Right panel — Control Authority
    // ------------------------------------------------------------------ //
    GlassPanel {
        id: rightPanel
        objectName: "rightPanel"
        anchors.top: header.bottom
        anchors.right: parent.right
        anchors.topMargin: 16
        width: 298
        height: controlCol.implicitHeight + 34
        z: 15

        opacity: windowRoot.viewState === 0 ? 1.0 : 0.0
        Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
        anchors.rightMargin: windowRoot.viewState === 0 ? 16 : -340
        Behavior on anchors.rightMargin { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }

        Column {
            id: controlCol
            width: parent.width
            spacing: 13

            SectionLabel { text: "CONTROL AUTHORITY" }

            GlassSlider {
                id: azimuthSlider
                width: parent.width
                from: 0; to: 360
                label: "SUN AZIMUTH"
                valueLabel: Theme.fmtDeg(value)
                tint: "#FFC24D"
                Component.onCompleted: value = backend.sunAzimuth
                onSliderMoved: backend.sunAzimuth = val
            }

            GlassSlider {
                id: elevationSlider
                width: parent.width
                from: 0; to: 90
                label: "SUN ELEVATION"
                valueLabel: Theme.fmtDeg(value)
                tint: "#FFC24D"
                Component.onCompleted: value = backend.sunElevation
                onSliderMoved: backend.sunElevation = val
            }

            GlassSlider {
                id: foldSlider
                width: parent.width
                from: 0; to: 90
                label: "FOLD ANGLE  \u03B8"
                valueLabel: Theme.fmtDeg(value)
                tint: "#00E5FF"
                Component.onCompleted: value = backend.manualTheta
                onSliderMoved: backend.manualTheta = val
            }

            SunGizmo {
                width: parent.width
                height: 126
                azimuth: backend.sunAzimuth
                elevation: backend.sunElevation
            }

            // Autopilot toggle.
            Item {
                width: parent.width
                height: 26

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    color: "#9FB6CC"
                    font.family: "SF Pro Display"
                    font.pixelSize: 10
                    font.letterSpacing: 2.0
                    text: "AUTOPILOT"
                }

                Rectangle {
                    id: toggleTrack
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: 44
                    height: 24
                    radius: 12
                    color: backend.autopilot ? "#2E00E5FF" : "#2EFFFFFF"
                    border.color: backend.autopilot ? "#6600E5FF" : "#33FFFFFF"
                    border.width: 1

                    Rectangle {
                        x: backend.autopilot ? toggleTrack.width - width - 3 : 3
                        anchors.verticalCenter: parent.verticalCenter
                        width: 18
                        height: 18
                        radius: 9
                        color: backend.autopilot ? "#EAF6FF" : "#8FA6BC"

                        Behavior on x { NumberAnimation { duration: 120 } }
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: backend.autopilot = !backend.autopilot
                    }
                }
            }
        }
    }

    // Remote -> local sync: keep the sliders honest whenever the worker (or a
    // user click on the toggle) changes state, without fighting an in-flight
    // drag.  While on autopilot the fold slider mirrors the live solution.
    Connections {
        target: backend

        function onSunAzimuthChanged() {
            if (!azimuthSlider.pressed)
                azimuthSlider.value = backend.sunAzimuth
        }

        function onSunElevationChanged() {
            if (!elevationSlider.pressed)
                elevationSlider.value = backend.sunElevation
        }

        function onManualThetaChanged() {
            if (!foldSlider.pressed)
                foldSlider.value = backend.manualTheta
        }

        function onSampleReady(sample) {
            powerChart.chart.append(sample.t, sample.power_manual, sample.power)
            thetaChart.chart.append(sample.t, sample.theta_manual, sample.theta)
            gradChart.chart.append(sample.t, sample.grad, sample.grad)
        }
    }

    // ------------------------------------------------------------------ //
    // Bottom dock — three live charts
    // ------------------------------------------------------------------ //
    GlassPanel {
        id: dock
        objectName: "bottomDock"
        pad: 10

        anchors.bottom: parent.bottom
        anchors.left: leftPanel.right
        anchors.right: rightPanel.left
        anchors.bottomMargin: 16
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        height: 208
        z: 20

        Row {
            id: chartRow
            anchors.fill: parent
            spacing: 10

            ChartCard {
                id: powerChart
                objectName: "chartPower"
                kind: "power"
                note: "MANUAL vs AI"
                title: "POWER CAPTURE"
                width: (chartRow.width - 2 * chartRow.spacing) / 3
                height: chartRow.height
            }

            ChartCard {
                id: thetaChart
                objectName: "chartTheta"
                kind: "theta"
                note: "MANUAL vs AI"
                title: "FOLD ANGLE \u03B8"
                width: (chartRow.width - 2 * chartRow.spacing) / 3
                height: chartRow.height
            }

            ChartCard {
                id: gradChart
                objectName: "chartGrad"
                kind: "grad"
                note: "\u2016\u2207P\u2016  LOG SCALE"
                title: "GRADIENT NORM"
                width: (chartRow.width - 2 * chartRow.spacing) / 3
                height: chartRow.height
            }
        }
    }

    // The full telemetry pump (charts + slider sync) lives in the single
    // Connections block above, bound to backend.sampleReady at 10 Hz.
}
