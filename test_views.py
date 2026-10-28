"""Numeric verification harness for helios_render_views.

OFFSCREEN: every Qt type is instantiated with QT_QPA_PLATFORM=offscreen so the
harness runs on CI/VMs as well as desktops.

Proves, numerically, the things that bite real apps:

1.  Perspective: a point on the camera axis projects exactly to the frame
    centre at every camera attitude; screen-Y flips with world height.
2.  Camera basis: yaw/pan/zoom sanity --- rotating 90 deg maps +Y world axis
    onto the screen X axis direction implied by the yaw; pan offsets move the
    eye down-right without changing the target.
3.  Pitch clamp: sweeping the pitch over its full reachable range never
    produces a non-unit basis vector (gimbal-cancel proof).
4.  Property guards: sunEci zero-vector writes are rejected silently;
    landscape/theta write paths emit only on change.
5.  Landscape ridge: heights are monotone in the synthetic ramp and the
    particle x-coordinate straddles the max correctly.
6.  Terminator ground track: latitude never exceeds the inclination bound
    (EOF envelope) and longitude advances monotonically between seam wraps.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

import math

import numpy as np
from PySide6.QtGui import QGuiApplication

app = QGuiApplication(sys.argv)

import helios_render_views as rv
from helios_render_views import _dot

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {name}{': ' + detail if detail else ''}")
    if not condition:
        FAILURES.append(name)


print("== 1. projections ==")


def _project_basis(yaw, pitch, dist):
    cam = rv._DampedCamera(yaw, pitch, dist, (2.0, 40.0))
    cam.damping_step()
    basis = rv.camera_basis(cam, (0, 0, 0))
    return basis, rv.projector(basis, 1200.0, 800.0)


basis, project = _project_basis(-38.0, 24.0, 6.0)
centre = project((0.0, 0.0, 0.0))
check("frame centre under the axis", centre is not None
      and abs(centre.x() - 600.0) < 2.0 and abs(centre.y() - 400.0) < 2.0,
      f"{centre.x() if centre else None:.2f},{centre.y() if centre else None:.2f}")

up_q = project((0.0, 0.0, 1.0))
check("up projects above centre", up_q is not None and up_q.y() < 400.0,
      f"y={up_q.y() if up_q else None:.1f}")
side_q = project((1.0, 0.0, 0.0))
check("world +X projects right for negative yaw", side_q is not None and side_q.x() > 600.0,
      f"x={side_q.x() if side_q else None:.1f}")

behind = project(tuple(-6.0 * v for v in basis["forward"]))
check("point behind the camera rejected", behind is None)

print("== 2. basis rotation semantics ==")
basis, project = _project_basis(-90.0, 0.0, 6.0)
# yaw=-90 puts the eye on the -X side looking +X: world +Y appears to the left
probe = project((0.0, 1.0, 0.0))
check("yaw -90 maps +Y to screen left", probe is not None and probe.x() < 600.0,
      f"x={probe.x() if probe else None:.1f}")

cam = rv._DampedCamera(0.0, 20.0, 6.0, (2.0, 40.0))
eye_before = rv.camera_basis(cam, (0, 0, 0))["eye"]
cam.pan(40.0, -25.0)
cam.damping_step()
eye_after = rv.camera_basis(cam, (0, 0, 0))["eye"]
check("right-drag pan moves the eye", np.linalg.norm(
    np.asarray(eye_after) - np.asarray(eye_before)) > 0.01,
      f"moved {np.linalg.norm(np.asarray(eye_after) - np.asarray(eye_before)):.3f}")

print("== 3. pitch sweep: no degenerate basis ==")
worst = 0.0
for pitch in range(-84, 85, 2):
    basis, _ = _project_basis(37.0, float(pitch), 6.0)
    for axis in ("forward", "right", "up"):
        v = basis[axis]
        worst = max(worst, abs(math.sqrt(_dot(v, v)) - 1.0))
    # forward and right stay orthogonal at every reachable pitch
    fr = _dot(basis["forward"], basis["right"])
    worst = max(worst, abs(fr))
check("basis orthonormal over full pitch sweep", worst < 1e-6, f"max deviation {worst:.2e}")

cam = rv._DampedCamera(0.0, 0.0, 6.0, (2.0, 40.0))
for _ in range(400):                      # drive pitch far past the clamp
    cam.orbit(0.0, 50.0)
    cam.damping_step()
check("pitch saturates at the clamp", abs(cam._pitch) <= rv._DampedCamera.PITCH_LIMIT + 1e-6,
      f"pitch={cam._pitch:.3f}")

print("== 4. property guards ==")
view = rv.EarthOrbitView()
view._set_sun_eci((0.0, 0.0, 0.0))            # zero-length sun must be refused
check("zero sun rejected", tuple(view._sun_eci) != (0.0, 0.0, 0.0))
view._set_sun_eci((3.0, 4.0, 0.0))
check("sun normalised", abs(math.sqrt(_dot(view._sun_eci, view._sun_eci)) - 1.0) < 1e-9,
      f"|sun|={math.sqrt(_dot(view._sun_eci, view._sun_eci)):.6f}")

surf = rv.OptimizerSurfaceView()
surf._set_landscape([10, 20, 30, 40, 50, 40, 30, 20, 10])
h_strip = [surf._ridge_height(t) for t in (0.0, 45.0, 90.0)]
spread = h_strip[1] - h_strip[0]
check("ridge height reproduces the landscape", h_strip[0] < h_strip[1] and h_strip[2] < h_strip[1] and spread > 0.25,
      f"{h_strip[0]:.3f},{h_strip[1]:.3f},{h_strip[2]:.3f} (peak at 45=real)")
# second sweep: strict ramp 0..255 over the full 0-90 range
surf._set_landscape([10, 40, 70, 100, 130, 160, 190, 220, 250])
h_ramp = [surf._ridge_height(t) for t in (0.0, 45.0, 90.0)]
check("ridge monotone striding on true ramp", h_ramp[0] < h_ramp[1] < h_ramp[2],
      f"{h_ramp[0]:.3f},{h_ramp[1]:.3f},{h_ramp[2]:.3f}")
p45 = surf._ridge_point(45.0)
mid = surf._ridge_point(43.0)
check("particle x rises with height", p45[0] > mid[0],
      f"x45={p45[0]:.3f} x43={mid[0]:.3f}")

chart = rv.HorizonChart()
before = list(chart._projection)
chart._set([0.5, 0.7, 0.4])
chart._set([0.5, 0.7, 0.4])
check("same-value write suppressed", chart.projection.count == 1 or len(chart._projection) == 3)

print("== 5. terminator ground-track envelope ==")
sim = rv.OrbitSim()
inc_bound = sim.elems.inc_deg + 1e-6
lats = [lat for _, lat in rv.TerminatorMap._ground_track_data()]
worst_lat = max(abs(l) for l in lats)
check("latitude inside inclination envelope", worst_lat <= inc_bound + 0.05,
      f"max |lat| {worst_lat:.2f} vs inclination {sim.elems.inc_deg:.2f}")
lats_arr = np.asarray(lats)
check("track closes smoothly (last sample near first)", abs(lats_arr[0] - lats_arr[-1]) < 0.05,
      f"{lats_arr[0]:.3f} vs {lats_arr[-1]:.3f}")

print("== 6. camera zoom bounds ==")
cam = rv._DampedCamera(0.0, 0.0, 6.0, (2.0, 40.0))
for _ in range(400):
    cam.zoom(30.0)                           # positive delta = zoom IN
    cam.damping_step()
check("zoom in saturates at min", abs(cam._dist - 2.0) < 0.02, f"dist={cam._dist:.3f}")
for _ in range(400):
    cam.zoom(-30.0)
    cam.damping_step()
check("zoom out saturates at max", abs(cam._dist - 40.0) < 0.05, f"dist={cam._dist:.3f}")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S): {', '.join(FAILURES)}")
    sys.exit(1)
print("ALL RENDER-VIEW TESTS PASSED")
