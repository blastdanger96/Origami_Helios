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

    // Latest sampleReady payload, shared by the orbital and AI views.
    property var lastSample: null

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

        // ---- View 1: Orbital Mechanics --------------------------------- //
        Item {
            id: viewOrbit
            anchors.fill: parent
            opacity: windowRoot.viewState === 1 ? 1 : 0
            visible: opacity > 0.01

            Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

            EarthOrbitView {
                id: orbitView
                anchors.fill: parent
                sunEci: windowRoot.lastSample ? windowRoot.lastSample.sun_eci : [1.0, 0.0, 0.0]
                anomalyDeg: windowRoot.lastSample ? windowRoot.lastSample.true_anom_deg : 0.0
                eclipse: windowRoot.lastSample ? windowRoot.lastSample.eclipse : false
            }

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton | Qt.RightButton

                property real lastX: 0
                property real lastY: 0

                onPressed: { lastX = mouse.x; lastY = mouse.y }
                onPositionChanged: {
                    if (!pressed) return
                    var dx = mouse.x - lastX
                    var dy = mouse.y - lastY
                    if (mouse.buttons & Qt.RightButton) orbitView.pan(dx, dy)
                    else orbitView.orbit(dx, dy)
                    lastX = mouse.x
                    lastY = mouse.y
                }
                onWheel: (wheel) => orbitView.zoom(wheel.angleDelta.y)
            }
        }

        // ---- View 2: AI Optimizer -------------------------------------- //
        Item {
            id: viewAI
            anchors.fill: parent
            opacity: windowRoot.viewState === 2 ? 1 : 0
            visible: opacity > 0.01

            Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

            OptimizerSurfaceView {
                id: surfaceView
                anchors.fill: parent
                landscape: windowRoot.lastSample ? windowRoot.lastSample.landscape : []
                thetaDeg: backend.theta
                stepSizeDeg: optimizer.stepSize !== 0 ? optimizer.stepSize * 180 / Math.PI : backend.theta
            }

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton | Qt.RightButton

                property real lastX: 0
                property real lastY: 0

                onPressed: { lastX = mouse.x; lastY = mouse.y }
                onPositionChanged: {
                    if (!pressed) return
                    var dx = mouse.x - lastX
                    var dy = mouse.y - lastY
                    if (mouse.buttons & Qt.RightButton) surfaceView.pan(dx, dy)
                    else surfaceView.orbit(dx, dy)
                    lastX = mouse.x
                    lastY = mouse.y
                }
                onWheel: (wheel) => surfaceView.zoom(wheel.angleDelta.y)
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
            windowRoot.lastSample = sample
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

    // ------------------------------------------------------------------ //
    // ORBITAL MECHANICS panels — slide in only on viewState === 1
    // ------------------------------------------------------------------ //
    GlassPanel {
        id: orbitLeftPanel
        anchors.top: header.bottom
        anchors.left: parent.left
        anchors.topMargin: 16
        width: 298
        height: orbitTelemetryCol.implicitHeight + 34
        z: 15

        opacity: windowRoot.viewState === 1 ? 1.0 : 0.0
        Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
        anchors.leftMargin: windowRoot.viewState === 1 ? 16 : -340
        Behavior on anchors.leftMargin { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }

        Column {
            id: orbitTelemetryCol
            width: parent.width
            spacing: 12

            SectionLabel { text: "ORBITAL TELEMETRY" }

            TelemetryCell {
                label: "ALTITUDE"
                text: (windowRoot.lastSample ? windowRoot.lastSample.alt_km : 0).toFixed(2) + " km"
                tint: "#9BF3FF"
            }

            TelemetryCell {
                label: "VELOCITY"
                text: ((windowRoot.lastSample ? windowRoot.lastSample.speed_kms : 0) * 1000.0).toFixed(0) + " m/s"
            }

            TelemetryCell {
                label: "ORBITAL PERIOD"
                text: ((windowRoot.lastSample ? windowRoot.lastSample.period_s : 0) / 60.0).toFixed(2) + " min"
            }

            TelemetryCell {
                label: "TRUE ANOMALY \u03BD"
                text: ((windowRoot.lastSample ? windowRoot.lastSample.true_anom_deg : 0) % 360).toFixed(1) + "\u00B0"
                tint: "#9BF3FF"
            }

            TelemetryCell {
                label: "NEXT ECLIPSE IN"
                text: {
                    if (!windowRoot.lastSample) return "\u2014"
                    var s = windowRoot.lastSample.next_eclipse_s
                    return s >= 0 ? (s / 60.0).toFixed(1) + " min" : "NO ECLIPSE WINDOW"
                }
            }

            LivePill {
                label: (windowRoot.lastSample && windowRoot.lastSample.eclipse)
                       ? "ECLIPSE \u2014 POWER DROP"
                       : "SUNLIT \u2014 FULL IRRADIANCE"
                active: !(windowRoot.lastSample && windowRoot.lastSample.eclipse)
            }

            TerminatorMap {
                width: parent.width
                height: 138
                sunEci: windowRoot.lastSample ? windowRoot.lastSample.sun_eci : [1, 0, 0]
                anomalyDeg: windowRoot.lastSample ? windowRoot.lastSample.true_anom_deg : 0
            }
        }
    }

    GlassPanel {
        id: orbitRightPanel
        anchors.top: header.bottom
        anchors.right: parent.right
        anchors.topMargin: 16
        width: 298
        height: sunTrackCol.implicitHeight + 34
        z: 15

        opacity: windowRoot.viewState === 1 ? 1.0 : 0.0
        Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
        anchors.rightMargin: windowRoot.viewState === 1 ? 16 : -340
        Behavior on anchors.rightMargin { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }

        Column {
            id: sunTrackCol
            width: parent.width
            spacing: 13

            SectionLabel { text: "SUN TRACKING" }

            HorizonChart {
                width: parent.width
                height: 158
                projection: windowRoot.lastSample ? windowRoot.lastSample.projection : []
            }

            TelemetryCell {
                label: "INCIDENCE NOW  cos\u03B8"
                text: backend.incidence.toFixed(3)
                tint: "#9BF3FF"
            }

            GlassSlider {
                width: parent.width
                from: 1; to: 100
                label: "TIME WARP"
                valueLabel: value.toFixed(0) + "\u00D7"
                tint: "#FFC24D"
                Component.onCompleted: value = backend.timeWarp
                onSliderMoved: (val) => backend.timeWarp = val
            }

            WarpDriveToggle {
            }
        }
    }

    Connections {
        target: optimizer

        function onLrChanged() { if (!lrSlider.pressed) lrSlider.value = Math.log10(optimizer.lr) }
        function onBeta1Changed() { if (!beta1Slider.pressed) beta1Slider.value = optimizer.beta1 }
        function onBeta2Changed() { if (!beta2Slider.pressed) beta2Slider.value = optimizer.beta2 }
        function onEpsChanged() { if (!epsSlider.pressed) epsSlider.value = Math.log10(optimizer.epsilon) }
    }

    // ------------------------------------------------------------------ //
    // AI OPTIMIZER panels — slide in only on viewState === 2
    // ------------------------------------------------------------------ //
    GlassPanel {
        id: aiLeftPanel
        anchors.top: header.bottom
        anchors.left: parent.left
        anchors.topMargin: 16
        width: 298
        height: aiStateCol.implicitHeight + 34
        z: 15

        opacity: windowRoot.viewState === 2 ? 1.0 : 0.0
        Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
        anchors.leftMargin: windowRoot.viewState === 2 ? 16 : -340
        Behavior on anchors.leftMargin { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }

        Column {
            id: aiStateCol
            width: parent.width
            spacing: 12

            SectionLabel { text: "OPTIMIZATION STATE" }

            OptimizerNodeGraph {
                width: parent.width
                height: 152
            }

            TelemetryCell {
                label: "LEARNING RATE"
                text: optimizer.sci(optimizer.lr)
                tint: "#00E5FF"
            }

            TelemetryCell {
                label: "GRADIENT  dP/d\u03B8"
                text: optimizer.sci(Math.abs(optimizer.thetaGrad)) + " W/rad"
            }

            TelemetryCell {
                label: "ADAM MOMENTUM  |m|"
                text: optimizer.momentum.toFixed(4)
                tint: "#9BF3FF"
            }

            TelemetryCell {
                label: "ADAM VARIANCE  \u221Av"
                text: Math.sqrt(Math.max(0, optimizer.variance)).toExponential(2)
            }

            TelemetryCell {
                label: "STEP  d\u03B8/cmd"
                text: optimizer.fmtDeg(optimizer.stepSize) + "\u00B0"
                tint: "#9BF3FF"
            }

            LivePill {
                label: optimizer.settled ? "SETTLED \u2014 ZERO GRADIENT" :"DESCENDING GRADIENT"
                active: !optimizer.settled
            }
        }
    }

    GlassPanel {
        id: aiRightPanel
        anchors.top: header.bottom
        anchors.right: parent.right
        anchors.topMargin: 16
        width: 298
        height: hyperCol.implicitHeight + 34
        z: 15

        opacity: windowRoot.viewState === 2 ? 1.0 : 0.0
        Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
        anchors.rightMargin: windowRoot.viewState === 2 ? 16 : -340
        Behavior on anchors.rightMargin { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }

        Column {
            id: hyperCol
            width: parent.width
            spacing: 13

            SectionLabel { text: "HYPERPARAMETERS" }

            GlassSlider {
                id: lrSlider
                width: parent.width
                from: -6; to: 0
                label: "LEARNING RATE \u03B7"
                valueLabel: Math.pow(10, value).toExponential(1)
                tint: "#00E5FF"
                Component.onCompleted: value = Math.log10(optimizer.lr)
                onSliderMoved: (val) => optimizer.setLearningRate(Math.pow(10, val))
            }

            GlassSlider {
                id: beta1Slider
                width: parent.width
                from: 0; to: 0.99
                label: "BETA 1  \u03B2\u2081"
                valueLabel: value.toFixed(4)
                tint: "#00E5FF"
                Component.onCompleted: value = optimizer.beta1
                onSliderMoved: (val) => optimizer.setBeta1(val)
            }

            GlassSlider {
                id: beta2Slider
                width: parent.width
                from: 0.9; to: 0.999
                label: "BETA 2  \u03B2\u2082"
                valueLabel: value.toFixed(5)
                tint: "#00E5FF"
                Component.onCompleted: value = optimizer.beta2
                onSliderMoved: (val) => optimizer.setBeta2(val)
            }

            GlassSlider {
                id: epsSlider
                width: parent.width
                from: -12; to: -1
                label: "EPSILON  \u03B5"
                valueLabel: Math.pow(10, value).toExponential(1)
                tint: "#00E5FF"
                Component.onCompleted: value = Math.log10(Math.max(optimizer.epsilon, 1e-12))
                onSliderMoved: (val) => optimizer.setEpsilon(Math.pow(10, val))
            }

            TelemetryCell {
                label: "LIVE  \u03B7"
                text: optimizer.sci(optimizer.lr)
            }
        }
    }
}
