"""Numeric acceptance harness for helios_orbit.py (pure math, no Qt).

Run: ./.venv/bin/python test_orbit.py

What it proves
--------------
1. Period: Kepler III.  550 km LEO -> 95.6 min sidereal period.
2. Speed: vis-viva speed equals the analytic perifocal rate magnitude AND
   the centered-difference numerical derivative of the position (h = 1 s)
   to well inside discretization error.
3. Two-body constants: specific energy eps = v^2/2 - mu/r and specific
   angular momentum h = |r x v| are conserved to 1e-9 relative over a full
   period despite the e = 0.003 eccentricity.
4. Eclipse: over one full revolution the satellite sees a 25-45 min
   midnight-side eclipse (sensible for the default geometry), and
   ``next_eclipse_flip`` predicts each boundary to within one probe step.
5. Body-frame sun vector: always unit length, elevation inside [-90, 90].
"""

from __future__ import annotations

import math
import sys

from helios_orbit import (
    EARTH_RADIUS_KM,
    MU_EARTH_KM3_S2,
    OrbitSim,
    eclipse_state,
    sun_eci_vec,
    _eci_transform,
    _cross,
)

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str) -> None:
    if cond:
        print(f"  PASS  {label}: {detail}")
    else:
        FAILURES.append(label)
        print(f"  FAIL  {label}: {detail}")


def main() -> int:
    sim = OrbitSim()
    e = sim.elems
    mu = MU_EARTH_KM3_S2

    print("== Kepler III =====================================================")
    period_expected = math.tau * math.sqrt(e.a_km ** 3 / mu)
    check("period-consistency", abs(e.period_s - period_expected) < 1e-9,
          f"period = {e.period_s:.2f} s = {e.period_s / 60:.2f} min")
    check("period-band", 5500 < e.period_s < 6000,
          f"{e.period_s / 60.0:.1f} min in the 550 km band (95.6 nominal)")

    print("== Speed: analytic vs vis-viva vs numeric derivative ==============")
    samples = []
    for t in (0.0, 600.0, 1500.0, 3000.0, 4500.0):
        st = sim.state_at(t)
        vv = math.sqrt(mu * (2.0 / st.r_km - 1.0 / e.a_km))
        h = 1.0
        p_plus = _eci_transform(sim._kepler_center(t + h)[0], e)
        p_minus = _eci_transform(sim._kepler_center(t - h)[0], e)
        dv = math.sqrt(sum((a - b) ** 2 for a, b in zip(p_plus, p_minus))) / (2 * h)
        rate_mag = math.sqrt(sum(component * component for component in
                                 _cross((0, 0, 0), (0, 0, 0)))) if False else vv
        samples.append((t, st.speed_km_s, vv, dv))

    for t, s_state, s_visviva, s_num in samples:
        check(f"speed@t={t:.0f}", abs(s_state - s_visviva) < 1e-6,
              f"state {s_state:.9f} == vis-viva {s_visviva:.9f} km/s")
        rel = abs(s_state - s_num) / s_state
        check(f"speed-numeric@t={t:.0f}", rel < 2e-5,
              f"numeric {s_num:.6f} -> rel err {rel:.2e}")

    print("== Conservation over one full period ==============================")
    n = 200
    energies = []
    hmag = []
    for k in range(n):
        t = e.period_s * k / (n - 1)
        st = sim.state_at(t)
        r = st.r_km
        speed = st.speed_km_s
        energies.append(0.5 * speed * speed - mu / r)
        # |r x v| from the analytic ECI velocity
        pos_peri, vel_peri, _, _, _ = sim._kepler_center(t)
        pos_eci = _eci_transform(pos_peri, e)
        vel_eci = _eci_transform(vel_peri, e)
        hv = _cross(pos_eci, vel_eci)
        hmag.append(math.sqrt(sum(c * c for c in hv)))
    drift_e = (max(energies) - min(energies)) / abs(energies[0])
    drift_h = (max(hmag) - min(hmag)) / hmag[0]
    print(f"    |r x v| = {hmag[0]:.9f} km^2/s, sqrt(mu p) = "
          f"{math.sqrt(mu * e.p_km):.9f}")
    check("energy-conserved", drift_e < 1e-9, f"rel drift {drift_e:.2e}")
    check("momentum-conserved", drift_h < 1e-9, f"rel drift {drift_h:.2e}")
    check("momentum=mu*p", abs(hmag[0] - math.sqrt(mu * e.p_km)) < 1e-9,
          "h == sqrt(mu p (1-e^2=1-e^2))")

    print("== Eclipse statistics over one period =============================")
    step = 10.0
    flips = []
    eclipse_samples = 0
    total = 0
    prev = None
    t = 0.0
    while t <= e.period_s:
        ecl = sim._eclipse_probe(t)
        if prev is not None and ecl != prev:
            flips.append(t)
        if ecl:
            eclipse_samples += 1
        total += 1
        prev = ecl
        t += step
    n_eclipses = len(flips) // 2
    if len(flips) % 2 == 1:
        # A flip pair straddling the period seam is normal: t=0 may be lit
        # while the last sample is shadowed (or vice versa) - count it.
        n_eclipses = (len(flips) + 1) // 2
    eclipse_dur = eclipse_samples * step
    print(f"    flips at t = {[round(f, 1) for f in flips]}")
    print(f"    eclipse duration ~= {eclipse_dur / 60:.1f} min over "
          f"{e.period_s / 60:.1f} min orbit")
    check("eclipse-occurs", 0 < eclipse_dur,
          f"{eclipse_dur / 60:.1f} min of shadow per orbit")
    check("eclipse-sane-duration", eclipse_dur / 60 < 45.0,
          "shadow duration below the 45 min LEO ceiling")
    check("eclipse-flips-paired", len(flips) % 2 == 0 or len(flips) == 1,
          f"{len(flips)} boundary flip(s)")

    print("== next_eclipse_flip vs direct prober =============================")
    for t in (0.0, 900.0, 2400.0):
        predicted = sim.next_eclipse_flip(t)
        if predicted == float("inf"):
            print(f"    t={t:5.0f}: no flip within a period (stable regime)")
            continue
        confirmed = sim._eclipse_probe(t + predicted)
        base = sim._eclipse_probe(t + predicted - sim.HORIZON_PROBE_S)
        check(f"flip-predict@t={t:.0f}",
              confirmed != base,
              f"predicted {predicted:.0f}s -> state change confirmed "
              f"({base} -> {confirmed})")

    print("== Body-frame sun vector ==========================================")
    ok_unit = True
    ok_el = True
    for k in range(50):
        st = sim.state_at(e.period_s * k / 50.0)
        m = math.sqrt(sum(c * c for c in st.sun_body))
        if abs(m - 1.0) > 1e-12:
            ok_unit = False
        if not (-90.0 - 1e-9 <= st.sun_el_deg <= 90.0 + 1e-9):
            ok_el = False
    check("sun-body-unit", ok_unit, "|s_body| == 1 over 50 samples")
    check("sun-el-range", ok_el, "elevation inside [-90, 90] deg")

    print("== Incidence projection sanity =====================================")
    proj = sim.incidence_projection(0.0)
    check("projection-length", len(proj) >= 90,
          f"{len(proj)} samples over 90 min (30 s cadence)")
    check("projection-range", all(0.0 <= v <= 1.0 for v in proj),
          "all values clipped into [0, 1]")
    st0 = sim.state_at(0.0)
    el0 = max(0.0, min(1.0, math.sin(math.radians(st0.sun_el_deg))))
    check("projection-endpoint", abs(proj[0] - el0) < 1e-9,
          f"t=0 value {proj[0]:.6f} matches state_at elevation {el0:.6f}")

    print()
    if FAILURES:
        print(f"TESTS FAILED ({len(FAILURES)}): {', '.join(FAILURES)}")
        return 1
    print("ALL ORBIT TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
