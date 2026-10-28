// Project Helios — shared design tokens.
//
// QML color literals accept the #AARRGGBB form, so glassmorphism fills live
// here as strings instead of Qt.rgba calls (a `.pragma library` file has no
// access to the QML `Qt` global object).
.pragma library

// Accents
var cyan = "#00E5FF"
var green = "#00FF88"
var white = "#E8F2FC"
var dim = "#9FB6CC"
var dimmer = "#62798F"
var warn = "#FFB454"
var alert = "#FF4D6A"

// Glassmorphism: rgba(15, 20, 30, 0.60) + a 10% white border.
var glassFill = "#990F141E"
var glassFillDeep = "#B80A0E16"
var glassStroke = "#1AFFFFFF"
var glassHighlight = "#14FFFFFF"

// Typography — all caps + wide tracking for headers, SF Mono for numbers.
var sans = "SF Pro Display"
var mono = "SF Mono"

// Chart window / gauge normalisation.
var chartWindow = 60.0          // seconds of history
var maxPowerApprox = 4600.0     // 12 m^2 * 0.29 * 1361 W

function fmtW(w) {
    var v = Math.abs(w)
    if (v >= 1000)
        return (w / 1000).toFixed(2) + " kW"
    return Math.round(w) + " W"
}

function sci(v) {
    if (v <= 0)
        return "0"
    var e = Math.floor(Math.log(v) / Math.LN10)
    var m = v / Math.pow(10, e)
    return m.toFixed(2) + "e" + e
}

function fmtDeg(d) {
    return d.toFixed(1) + "\u00B0"
}

function fmtMet(sec) {
    var m = Math.floor(sec / 60)
    var s = Math.floor(sec % 60)
    var p = function(n) { return n < 10 ? "0" + n : "" + n }
    return "T+" + p(m) + ":" + p(s)
}
