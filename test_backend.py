"""Phase-1 acceptance harness for the Project Helios control loop.

What it proves
--------------
1. **Sun-shift recovery (the mission-control test).**  Three abrupt sun
   moves drive the deployment.  After each step the worker's 100 ms Adam
   loop (10 steps/tick, lr 0.015) must bring theta to the brute-force
   optimum within 0.5 deg and 99.5 % of achievable power within a 2.5 s
   hold, while the gradient norm spikes at the event and decays as the
   controller settles.

2. **Bumpless mode handover.**  Engaging manual authority must freeze the
   optimizer: the command must not drift while the operator holds it.

It runs the real :class:`HeliosWorker` code path through a real event loop
(QCoreApplication + signal plumbing, no QGuiApplication windows), so the same
contract the QML dashboard relies on is what gets tested.

Run:  ./.venv/bin/python test_backend.py
"""

from __future__ import annotations

import math
import sys

import torch
from PySide6.QtCore import QCoreApplication, QElapsedTimer

from helios_backend import HeliosBackend, sun_vector_from_angles
from helios_physics import SolarArrayModel


def brute_force_optimum(model: SolarArrayModel, az_deg: float, el_deg: float):
    """Golden reference: dense grid scan of the true power-vs-theta optimum."""
    sun = sun_vector_from_angles(az_deg, el_deg)
    thetas = torch.linspace(0.0, math.pi / 2, 9001, dtype=torch.float64)
    powers = torch.stack([model(float(t), sun) for t in thetas])
    idx = int(torch.argmax(powers))
    return float(thetas[idx]), float(powers[idx])


def main() -> int:
    torch.set_num_threads(1)
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)

    backend = HeliosBackend()
    model = backend._model  # the live physics object the worker optimizes against
    samples: list[dict] = []
    backend.sampleReady.connect(samples.append)

    def settle(seconds: float) -> None:
        app.processEvents()
        loop = QElapsedTimer()
        loop.start()
        while not loop.hasExpired(int(seconds * 1000)):
            app.processEvents()

    # ---------------------------------------------------------------- #
    # Test 1: abrupt sun shift -> real-time recovery
    # ---------------------------------------------------------------- #
    ok = True
    events = [
        (35.0, 46.0),   # mission default
        (140.0, 22.0),  # abrupt move #1: sun swings behind the fold axis
        (10.0, 70.0),   # abrupt move #2: sun climbs high over the shear side
    ]
    hold = 2.5

    for az, el in events:
        backend.sunAzimuth = az
        backend.sunElevation = el
        before = len(samples)
        settle(hold)
        window = samples[before:]
        powers = [s["power_auto"] for s in window]
        opt_theta, opt_power = brute_force_optimum(model, az, el)
        # backend.sampleReady already reports angles in degrees.
        final_theta = window[-1]["theta_auto"]
        final_power = window[-1]["power_auto"]
        err_deg = abs(final_theta - math.degrees(opt_theta))
        # (Old-sun samples from the first ~100 ms of the window are expected;
        #  the acceptance test is on the SETTLED tail, not the window max.)
        spike = max(s["grad"] for s in window[:4])
        tail = max(s["grad"] for s in window[-5:])
        interior = 1.0 < math.degrees(opt_theta) < 89.0

        print(f"[sun {az:5.1f}/{el:4.1f}] theta={final_theta:7.3f} deg "
              f"(grid-opt {math.degrees(opt_theta):7.3f}, err {err_deg:.4f} deg) "
              f"P={final_power:9.1f} W vs opt {opt_power:9.1f} W "
              f"({100.0 * final_power / opt_power:.3f} %) "
              f"| grad spike {spike:.2e} -> tail {tail:.2e} "
              f"({'interior' if interior else 'clamp-boundary'} optimum)")
        if err_deg > 0.5 or abs(opt_power - final_power) > 0.005 * max(opt_power, 1.0):
            ok = False
            print("  FAIL: did not recover the optimum.")
        if interior and spike / max(tail, 1e-12) < 20.0:
            ok = False
            print("  FAIL: no recognizable transient gradient spike.")

    # ---------------------------------------------------------------- #
    # Test 2: mode handover must be bumpless
    # ---------------------------------------------------------------- #
    backend.autopilot = False
    settle(0.3)
    frozen_manual = samples[-1]["theta_manual"]
    settle(0.3)
    drift = abs(samples[-1]["theta_manual"] - frozen_manual)
    print(f"[manual hold] drift={drift:.6f} deg over 0.3 s")
    if drift > 1e-6:
        ok = False
        print("  FAIL: manual mode drifted.")
    backend.autopilot = True
    settle(0.3)

    backend.shutdown()
    print("\nALL TESTS PASSED" if ok else "\nTESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
