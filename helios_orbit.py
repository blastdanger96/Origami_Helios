"""Keplerian orbital mechanics for the Project Helios mission (pure Python).

Design notes
------------
This module is deliberately *pure math* (no Qt, no torch): it is called at
10 Hz from the optimizer worker thread and verified by the numeric harness in
``test_orbit.py``, so nothing here can silently drift away from the telemetry.

Coordinate frames
-----------------
- **ECI** (Earth-Centered Inertial): classical orbital element frame. ``+Z``
  is the Earth spin axis, ``+X`` towards the vernal equinox.
- **LVLH** (local-vertical/local-horizontal) body frame — the frame the solar
  physics model calls *body*: ``z = zenith`` (unit geocentric position),
  ``x = along-track`` (velocity projected perpendicular to zenith),
  ``y = z x x`` (right-handed cross-track).  The array mounting plane is the
  body X-Y plane and the fold axis is +X, matching
  ``helios_backend.sun_vector_from_angles`` (azimuth 0 = +X toward +Y,
  elevation above +Z).

Analytic core
-------------
- Kepler's equation ``M = E - e sin E`` solved by Newton-Raphson seeded at
  ``E0 = M`` for e < 0.8 and ``E0 = pi`` otherwise (Vallado Alg. 2).  Ten
  iterations, tol 1e-12 rad, plus a stagnation break: e = 0.003 needs 3.
- Velocity is the *analytic* perifocal rate

      v_p = sqrt(mu p) / r * (-sin nu, e + cos nu),   p = a (1 - e^2)

  exactly d r_p / d t — vis-viva is asserted against it in the test harness.
- Eclipse: classical cylinder shadow.  Eclipsed iff on the anti-sun side
  (dot(r, s) < 0) AND the perpendicular distance to the shadow axis is below
  the blocking radius (Earth mean radius; also used for the tube limit).
- Sun direction: circular ecliptic motion, mean longitude
  L(t) = L0 + n_sun * days-since-J2000, obliquity eps = 23.4393 deg:

      s_ECI = (cos L, sin L cos eps, sin L sin eps)

  unit length by construction; the 0.0167 deg solar-eccentricity wobble is
  far below anything a tracking demo can resolve.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# --- Physical constants ---------------------------------------------------- #
MU_EARTH_KM3_S2 = 398600.4418            # WGS-84 GM
EARTH_RADIUS_KM = 6371.0
SUN_MEAN_MOTION_RAD_DAY = 2.0 * math.pi / 365.256      # sidereal year
SUN_J2000_MEAN_LONG_RAD = 4.88163                      # rad at J2000


def _wrap_tau(angle: float) -> float:
    return angle % math.tau


@dataclass
class OrbitElements:
    """Classical Keplerian elements; angles in degrees (QML-facing ctor)."""

    a_km: float = EARTH_RADIUS_KM + 550.0    # 550 km LEO, near-circular
    ecc: float = 0.003
    inc_deg: float = 51.6                    # ISS-like inclination
    raan_deg: float = 60.0
    argp_deg: float = 0.0

    @property
    def inc(self) -> float:
        return math.radians(self.inc_deg)

    @property
    def raan(self) -> float:
        return math.radians(self.raan_deg)

    @property
    def argp(self) -> float:
        return math.radians(self.argp_deg)

    @property
    def period_s(self) -> float:
        """Kepler's third law: 2 pi sqrt(a^3 / mu)."""
        return math.tau * math.sqrt(self.a_km ** 3 / MU_EARTH_KM3_S2)

    @property
    def p_km(self) -> float:
        return self.a_km * (1.0 - self.ecc * self.ecc)

    @property
    def mean_motion_rad_s(self) -> float:
        return math.sqrt(MU_EARTH_KM3_S2 / self.a_km ** 3)


def solve_kepler(mean_anomaly_rad: float, ecc: float) -> float:
    """Newton-Raphson solution of M = E - e sin E (stagnation-safe)."""
    big_e = math.pi if ecc >= 0.8 else mean_anomaly_rad
    for _ in range(10):
        f = big_e - ecc * math.sin(big_e) - mean_anomaly_rad
        fp = 1.0 - ecc * math.cos(big_e)
        if abs(fp) < 1e-14:                      # singular only if e -> 1
            break
        step = f / fp
        big_e -= step
        if abs(step) < 1e-12:
            break
    return big_e


def true_anomaly(ecc_anomaly_rad: float, ecc: float) -> float:
    """E -> nu via the half-angle form (numerically safe for any e < 1)."""
    return 2.0 * math.atan2(
        math.sqrt((1.0 + ecc) / (1.0 - ecc)) * math.tan(ecc_anomaly_rad / 2.0),
        1.0,
    )


def sun_eci_vec(days_since_j2000: float) -> tuple[float, float, float]:
    """Unit sun direction in ECI from circular ecliptic motion."""
    lam = SUN_J2000_MEAN_LONG_RAD + SUN_MEAN_MOTION_RAD_DAY * days_since_j2000
    eps = math.radians(23.4393)
    return (math.cos(lam), math.sin(lam) * math.cos(eps), math.sin(lam) * math.sin(eps))


def _eci_transform(p_peri: tuple[float, float], elems: OrbitElements):
    """Perifocal (xp, yp) -> ECI, explicit 3-2-3 (RAAN, i, argp) rotation."""
    raan, inc, argp = elems.raan, elems.inc, elems.argp
    cos_o, sin_o = math.cos(raan), math.sin(raan)
    cos_i, sin_i = math.cos(inc), math.sin(inc)
    cos_w, sin_w = math.cos(argp), math.sin(argp)
    xp, yp = p_peri

    r11 = cos_o * cos_w - sin_o * sin_w * cos_i
    r12 = -cos_o * sin_w - sin_o * cos_w * cos_i
    r21 = sin_o * cos_w + cos_o * sin_w * cos_i
    r22 = -sin_o * sin_w + cos_o * cos_w * cos_i
    r31 = sin_w * sin_i
    r32 = cos_w * sin_i
    return (
        r11 * xp + r12 * yp,
        r21 * xp + r22 * yp,
        r31 * xp + r32 * yp,
    )


def eclipse_state(pos_km: tuple[float, float, float], sun_eci: tuple) -> bool:
    """Cylinder-shadow eclipse test (penumbra ignored for prototype fidelity)."""
    sx = pos_km[0] * sun_eci[0] + pos_km[1] * sun_eci[1] + pos_km[2] * sun_eci[2]
    if sx >= 0.0:                                # sun side of the terminator
        return False
    perp_sq = (pos_km[0] ** 2 + pos_km[1] ** 2 + pos_km[2] ** 2) - sx * sx
    return perp_sq < EARTH_RADIUS_KM * EARTH_RADIUS_KM


def sun_body_angles(sun_body: tuple[float, float, float]) -> tuple[float, float]:
    """Body-frame unit sun vector -> (azimuth deg, elevation deg).

    Matches helios_backend.sun_vector_from_angles conventions.
    """
    az = math.degrees(math.atan2(sun_body[1], sun_body[0]))
    el = math.degrees(math.asin(max(-1.0, min(1.0, sun_body[2]))))
    return az, el


def _unit(v):
    m = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if m < 1e-12:
        return (0.0, 0.0, 1.0)
    return (v[0] / m, v[1] / m, v[2] / m)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(v, k):
    return (v[0] * k, v[1] * k, v[2] * k)


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _project_perp(v, onto):
    return _sub(v, _mul(onto, v[0] * onto[0] + v[1] * onto[1] + v[2] * onto[2]))


@dataclass
class OrbitState:
    """Flat snapshot of the mission situation (Qt-friendly primitives)."""

    t_s: float                     # elapsed sim seconds (time warp applied)
    r_km: float
    speed_km_s: float
    altitude_km: float
    true_anomaly_deg: float
    mean_anomaly_deg: float
    eclipse: bool
    sun_eci: tuple
    sun_body: tuple
    sun_az_deg: float
    sun_el_deg: float
    pos_eci_km: tuple
    pos_lvlh_km: tuple             # for the QML orbit-path drawing
    period_s: float
    next_eclipse_s: float          # seconds until the next shadow boundary


class OrbitSim:
    """Stateful Keplerian propagator.  Geometry is recomputed from the
    elements on every call, so time-warp jumps can never poison state."""

    HORIZON_S = 5400.0             # 90-minute projection window
    HORIZON_STEPS = 180            # 30 s resolution in the projection
    HORIZON_PROBE_S = 30.0         # eclipse-flip probe resolution

    def __init__(self, elems: OrbitElements | None = None) -> None:
        self.elems = elems or OrbitElements()
        # Fixed calendar anchor keeps the sim deterministic and unit-testable.
        self.days_since_j2000 = 8000.0

    # -- core propagation ---------------------------------------------------- #

    def _kepler_center(self, t_s: float):
        """Mean motion -> position/velocity/true-anomaly machinery.

        Mean anomaly is taken from mission t=0 at perigee (M0 = 0); the
        argument of periapsis enters ONLY through the frame rotation.
        """
        e = self.elems
        m = _wrap_tau(e.mean_motion_rad_s * t_s)
        big_e = solve_kepler(m, e.ecc)
        nu = true_anomaly(big_e, e.ecc)
        r = e.a_km * (1.0 - e.ecc * math.cos(big_e))
        # Analytic perifocal velocity scale: v_p = (mu / h) * (-sin nu,
        # e + cos nu) with h = sqrt(mu p).  This is the closed form whose
        # cross product r x v collapses to sqrt(mu p) exactly; using
        # sqrt(mu p)/r instead produces an h that drifts by +-e (caught by
        # test_orbit.py during bring-up).
        rate = math.sqrt(MU_EARTH_KM3_S2 / e.p_km)
        vel_peri = (-rate * math.sin(nu), rate * (e.ecc + math.cos(nu)))
        pos_peri = (r * math.cos(nu), r * math.sin(nu))
        return pos_peri, vel_peri, nu, big_e, r

    def state_at(self, t_s: float) -> OrbitState:
        e = self.elems
        pos_peri, vel_peri, nu, big_e, r = self._kepler_center(t_s)
        pos_eci = _eci_transform(pos_peri, e)
        vel_eci = _eci_transform(vel_peri, e)
        speed = math.sqrt(MU_EARTH_KM3_S2 * (2.0 / r - 1.0 / e.a_km))

        sun = sun_eci_vec(self.days_since_j2000 + t_s / 86400.0)
        eclipsed = eclipse_state(pos_eci, sun)

        # LVLH triad: z = zenith, x = along-track, y completes the triad.
        z_hat = _unit(pos_eci)
        x_hat = _unit(_project_perp(vel_eci, z_hat))
        y_hat = _cross(z_hat, x_hat)      # unit by construction (orthonormal)

        s_body = (
            sun[0] * x_hat[0] + sun[1] * x_hat[1] + sun[2] * x_hat[2],
            sun[0] * y_hat[0] + sun[1] * y_hat[1] + sun[2] * y_hat[2],
            sun[0] * z_hat[0] + sun[1] * z_hat[1] + sun[2] * z_hat[2],
        )
        az, el = sun_body_angles(s_body)

        # In-plane (perifocal) coordinates for the QML orbit-path drawing:
        # the drawing pipeline only needs (nu, r) plus the orbit orientation,
        # so hand it the raw perifocal pair it can re-rotate cheaply.
        pos_lvlh = (
            (pos_eci[0] * x_hat[0] + pos_eci[1] * x_hat[1] + pos_eci[2] * x_hat[2]) / r,
            (pos_eci[0] * y_hat[0] + pos_eci[1] * y_hat[1] + pos_eci[2] * y_hat[2]) / r,
            1.0,
        )

        return OrbitState(
            t_s=t_s,
            r_km=r,
            speed_km_s=speed,
            altitude_km=r - EARTH_RADIUS_KM,
            true_anomaly_deg=math.degrees(nu),
            mean_anomaly_deg=math.degrees(_wrap_tau(e.mean_motion_rad_s * t_s)),
            eclipse=eclipsed,
            sun_eci=sun,
            sun_body=_unit(s_body),
            sun_az_deg=az,
            sun_el_deg=el,
            pos_eci_km=pos_eci,
            pos_lvlh_km=pos_lvlh,
            period_s=e.period_s,
            next_eclipse_s=self.next_eclipse_flip(t_s),
        )

    # -- shadow-boundary prediction (recursion-free) -------------------------- #

    def _eclipse_probe(self, t_s: float) -> bool:
        """Lightweight eclipse test at an arbitrary sim time (no LVLH work)."""
        pos_peri, _, _, _, _ = self._kepler_center(t_s)
        pos_eci = _eci_transform(pos_peri, self.elems)
        sun = sun_eci_vec(self.days_since_j2000 + t_s / 86400.0)
        return eclipse_state(pos_eci, sun)

    def next_eclipse_flip(self, t_s: float) -> float:
        """Seconds until the next eclipse-state change (bounded by a period).

        30 s sampling quantises the boundary by at most that much — well
        inside what a mission-control readout needs.  Uses only the cheap
        probe, so it can be called from ``state_at`` with NO recursion.
        """
        first = self._eclipse_probe(t_s)
        limit = min(self.HORIZON_S, self.elems.period_s) + self.HORIZON_PROBE_S
        t = t_s + self.HORIZON_PROBE_S
        while t <= t_s + limit + self.elems.period_s:
            if self._eclipse_probe(t) != first:
                return t - t_s
            t += self.HORIZON_PROBE_S
        return float("inf")

    # -- 90-minute projection ------------------------------------------------- #

    def incidence_projection(self, t_s: float, ahead_s: float = HORIZON_S) -> list[float]:
        """cos(incidence-clamped elevation) over [t, t + ahead_s], 30 s steps.

        The *elevation* of the sun above the body mounting plane is the body
        z-component of the sun vector; clamping to [0, 1] means a sun below
        the plane reads as zero rather than crossing zero.  This is the exact
        quantity the physics model multiplies in for a track-aligned array.
        """
        out: list[float] = []
        probes = max(2, int(ahead_s / self.HORIZON_PROBE_S))
        for k in range(probes):
            tk = t_s + ahead_s * k / (probes - 1) if probes > 1 else t_s
            pos_peri, vel_peri, _, _, _ = self._kepler_center(tk)
            pos_eci = _eci_transform(pos_peri, self.elems)
            vel_eci = _eci_transform(vel_peri, self.elems)
            sun = sun_eci_vec(self.days_since_j2000 + tk / 86400.0)
            z_hat = _unit(pos_eci)
            x_hat = _unit(_project_perp(vel_eci, z_hat))
            s_z = sun[0] * z_hat[0] + sun[1] * z_hat[1] + sun[2] * z_hat[2]
            out.append(max(0.0, min(1.0, s_z)))
        return out
