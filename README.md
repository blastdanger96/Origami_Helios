# PROJECT HELIOS — Adaptive Origami Solar Array Optimizer

A real-time PyTorch control-loop prototype wrapped in a cinematic
glassmorphism mission-control dashboard (PySide6 + QML).  A LEO spacecraft
carries a deployable **Miura-ori** solar array; an Adam optimizer continuously
deploys the primary fold angle θ to maximize captured solar power as the
operator moves the sun.

![style: deep-space HUD · neon cyan #00E5FF · glass panels · lens flares]

## Project Helios in one sentence

The optimizer maximizes the optical power captured by a foldable aperture; the
dashboard proves it in real time — gauges for power and AI advantage, three
scrolling charts, a sun-lit 3D satellite with lens flares that track the same
sun vector the solver sees, and manual authority over the sun and fold angle.

## Quick start (macOS / Linux / Windows)

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

> Windows note: if `python` resolves to the Store shim, use `py -3 -m venv .venv`
> instead.  The app needs a desktop session (QML window); run the headless test
> below on servers.

## Headless verification

```bash
python test_backend.py
```

Proves the optimizer recovers the brute-force optimum (θ within 0.5 degrees,
power within 99.5 % of grid-search maximum) within 2.5 s of any abrupt sun
move, that the gradient norm spikes at the event, and that manual-mode
handover is bumpless.

## Layout

```
┌─ PROJECT HELIOS ─────────────── TELEMETRY · ORBITAL MECHANICS · AI OPTIMIZER · PWR LINK THERM ─┐
│                                                                                               │
│  MISSION TELEMETRY          [ 3D satellite: origami wing, sun-lit, lens flare ]   CONTROL AUTH │
│  ◔ Power gauge    ◔ AI gauge         (drag to orbit, idle auto-spin)        Sun Azimuth  ▬▬●  │
│  optimizer cells                                                                 Sun El   ▬▬● │
│                                                                              Fold θ     ▬▬●   │
│                                                        [ autopilot toggle · sun gizmo ]       │
│  ┌─ POWER CAPTURE ────┬─ FOLD ANGLE θ ────┬─ GRADIENT NORM (log) ──┐                           │
│  └─ scrolling live charts: optimized (cyan glow) vs manual (dashed) ──┘                         │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Files

| File | Role |
|---|---|
| `helios_physics.py` | Differentiable Miura-ori aperture: `A(θ)·max(0, n(θ)·s)·η·G`, facet kinematics `tan ψ = cos α · tan θ`, self-shading loss. |
| `helios_backend.py` | QThread worker: 10 Hz × 10 Adam steps on θ (lr 0.015, clamp 0–90°), manual baseline, AI-advantage telemetry, bumpless autopilot handover. |
| `helios_render.py` | Painter-based 3D viewport: 54-facet wing, bus/dish/radiator, Blinn-Phong shading from the *same* sun vector the solver sees, anamorphic lens flare, starfield HUD frame. |
| `helios_charts.py` | Transparent glowing `QQuickPaintedItem` charts: power (with AI-advantage band), θ, gradient norm (log). |
| `qml/*.qml` | Glassmorphism design system: `Theme.js`, glass panels, radial gauges, sliders, sun gizmo, starfield, `Main.qml` layout. |
| `main.py` | Entry point: registers QML types, exposes `backend`, runs the event loop. |
| `test_backend.py` | Phase-1 acceptance harness (headless). |

## Mission design

- **Objective.**  `P(θ) = A(θ) · max(0, n(θ)·s) · η · G` — folding points the
  corrugation at the sun but self-shadows the aperture, so the optimum is an
  interior maximum that migrates with the sun.  That trade-off is what makes
  the problem non-trivial and the AI gauge nonzero.
- **Manual baseline.**  A "frozen human" command starts at θ = 55° and never
  adapts; the **AI Advantage** gauge is `P(θ*) − P(55°)`, the watts recovered
  by the optimizer over that baseline.
- **Autopilot toggle.**  `AUTOPILOT` engages/disengages the optimizer
  bumplessly: switching to manual seeds the slider with the live θ; switching
  back re-seeds the optimizer with the slider's command and drops stale Adam
  moments.

## Tuning

| Where | Knob |
|---|---|
| `helios_backend.py` | `TICK_MS` (10 Hz), `STEPS_PER_TICK` (10), `LEARNING_RATE` (0.015) |
| `helios_physics.py` | `DEFAULT_AREA_M2` (12), `DEFAULT_EFFICIENCY` (0.29), self-shading (0.45), crease half-angle (45°) |
| `helios_render.py` | Lens-flare strength, star density, satellite materials |
| `qml/Theme.js` | Palette, glass fills, chart window |

## Known scope

- Charts are a custom transparent painter item rather than embedded
  pyqtgraph — pyqtgraph needs a `QQuickWidget` host with an opaque background
  and its own axis chrome, which fights glassmorphism; the curves here are
  4–600 points/frame and cost sub-millisecond paint time.
- The 3D stage is a software `QQuickPaintedItem` (not Qt3D/QQuickFramebufferObject)
  for the same portability reason: no Addons dependency, identical 10 Hz react
  behavior, and the lighting direction is guaranteed to match the solver.
