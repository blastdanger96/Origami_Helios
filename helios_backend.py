"""PyTorch backend for the Project Helios QML dashboard.

The first prototype flew a scripted sun along a compressed orbit.  This backend
hands the sun to the operator: two properties, ``sunAzimuth`` (0-360 deg) and
``sunElevation`` (0-90 deg), define the incidence vector

    s = [cos(el) cos(az),  cos(el) sin(az),  sin(el)]

and every QML change is forwarded to the solver as a queued slot.  The fold
angle is still the only decision variable; everything else is telemetry.

Architecture
------------
* :class:`SolarArrayModel` (imported from ``helios_physics``) is stateless and
  evaluates the differentiable power objective in float64.
* :class:`HeliosWorker` owns the torch state (the latent ``z`` Parameter, the
  Adam optimizer, the manual angle and the latest sun).  It lives on a
  dedicated ``QThread`` and is driven by a precise 100 ms ``QTimer`` created
  *inside* that thread.  Each tick performs 10 Adam steps and emits an
  immutable sample dictionary.
* :class:`HeliosBackend` is the QML-facing ``QObject``.  It exposes Qt
  properties and signals but contains no torch calls, so the GUI thread never
  blocks on autograd.  Commands go down through private signals; telemetry
  comes back through ``sampleReady`` and ``landscapeReady``.

Threading contract
------------------
The GUI may set properties at any time; the resulting ``_sunRequested`` /
``_manualRequested`` / ``_modeRequested`` / ``_orbitRequested`` signals are
queued onto the worker thread.  The worker never touches QML objects and the
backend never touches torch tensors.  Shutdown is a blocking queued call so
the timer is stopped by the thread that owns it (see
:meth:`HeliosBackend.shutdown`).

Optimization rationale
----------------------
The objective (see ``helios_physics``) is the captured electrical power

    P(theta) = A_eff(theta) * max(0, n(theta).s) * tau(i) * eta(T) * G

with an interior maximum for most sun angles.  Two audit-driven upgrades:

* **Soft boundaries (Part-1 audit 3).**  The controller no longer optimizes
  ``theta`` directly.  It optimizes an unconstrained latent

      theta(z) = 45 deg * (1 + tanh z)

  so the mechanical stops at 0/90 deg are *asymptotes of the map*, not clamp
  operations.  Every element of the graph stays differentiable, the gradient
  never vanishes against a clamp, and near the boundaries the Jacobian
  ``d theta/d z = 45 deg * sech^2 z`` decays smoothly instead of exploding.

* **LVLH orbit drive (Level A).**  In "ORBIT" mode the sun is the real moving
  body: azimuth sweeps at the LVLH orbital rate (~3.9 deg/min at 550 km) from
  the operator baseline, elevation breathing with the same orbital period.
  Manual slider jumps still exist in the other mode, and only *those* jumps
  emit event markers - an orbital sun is continuous, not an event.

Telemetry extras
----------------
The worker also maintains three audit deliverables: the 181-point loss
landscape ``P(theta)`` re-swept whenever the sun vector changes (emitted as a
flat value list for the QML LandscapeCard), a 20-sample optimizer trail
(\"the ball rolling down the hill\"), and a 1 Hz CSV telemetry recorder with an
export slot and an exit-time autosave.
"""

from __future__ import annotations

import csv
import math
from collections import deque
from pathlib import Path

import torch
from PySide6.QtCore import (
    Property,
    QMetaObject,
    QObject,
    QThread,
    QTimer,
    Qt,
    Signal,
    Slot,
)

from helios_physics import DEFAULT_EFFICIENCY, SolarArrayModel

TICK_MS = 100
STEPS_PER_TICK = 40
LEARNING_RATE = 0.02
THETA_MIN = 0.0
THETA_MAX = math.pi / 2.0
THETA_MID = 0.5 * (THETA_MIN + THETA_MAX)   # latent map centre: 45 deg
INITIAL_THETA = math.radians(12.0)
INITIAL_MANUAL_THETA = math.radians(55.0)
DEFAULT_SUN_AZIMUTH = 35.0
DEFAULT_SUN_ELEVATION = 46.0
SOLAR_CONSTANT = 1361.0

# LVLH orbital drive: at 550 km the sun's LVLH azimuth precesses at about
# (360 deg / 95.6 min) ≈ 3.77 deg/min.  The elevation breathes with the same
# period (beta-angle swing) so the objective keeps reshaping continuously.
ORBIT_RATE_DEG_S = 3.77 / 60.0
ORBIT_EL_SWING_DEG = 20.0

# A manual sun move beyond this angle restarts the Adam moment state.
SUN_JUMP_RESET_DEG = 2.0

TRAIL_SAMPLES = 20
CSV_INTERVAL_S = 1.0
CSV_AUTOSAVE_NAME = "helios_mission_autosave.csv"
CSV_EXPORT_NAME = "helios_mission_export.csv"


def sun_vector_from_angles(
    azimuth_deg: float,
    elevation_deg: float,
    dtype: torch.dtype = torch.float64,
) -> torch.Tensor:
    """Return the unit sun vector for operator-supplied spherical angles.

    Azimuth is measured from +X toward +Y; elevation is measured above the
    array's mounting plane (+Z).  Elevation is clamped to the physical
    hemisphere, azimuth wraps.  The formula is unit-length by construction
    (cos^2 el [cos^2 az + sin^2 az] + sin^2 el ≡ 1), so there is no
    renormalization step and no gradient singularity at the poles.
    """
    az = math.radians(float(azimuth_deg) % 360.0)
    el = math.radians(max(0.0, min(90.0, float(elevation_deg))))
    return torch.tensor(
        [math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)],
        dtype=dtype,
    )


def _wrap_degrees(value: float) -> float:
    return float(value) % 360.0


def _clip_el_degrees(value: float) -> float:
    return max(0.0, min(90.0, float(value)))


class HeliosWorker(QObject):
    """Owns the torch state and runs the 10 Hz optimizer loop off the GUI thread.

    The worker is deliberately free of QML knowledge: it produces plain
    dictionaries that :class:`HeliosBackend` republishes as Qt properties.
    """

    sample = Signal(object)  # dict[str, float | bool | list]

    def __init__(self, model: SolarArrayModel, parent=None) -> None:
        super().__init__(parent)
        self.model = model
        # Unconstrained latent: theta = THETA_MID * (1 + tanh z).  The stops
        # are asymptotes of the map, so no clamp op ever enters the graph.
        self.z = torch.nn.Parameter(torch.tensor(LATENT_SEED, dtype=torch.float64))
        self.optimizer = self._make_optimizer()

        self.sun_azimuth = DEFAULT_SUN_AZIMUTH
        self.sun_elevation = DEFAULT_SUN_ELEVATION
        self._prev_sun_az = self.sun_azimuth
        self._prev_sun_el = self.sun_elevation
        # The operator's frozen baseline starts at a naive 55 deg hold, so the
        # first frame already shows the value of adaptive folding.  Taking
        # manual authority transfers the live command (bumpless handover).
        self.manual_theta = INITIAL_MANUAL_THETA
        self.autopilot = True
        self.orbit = False
        self.t = 0.0
        self.t_lvlh = 0.0
        self._timer = None
        self._trail: deque[tuple[float, float]] = deque(maxlen=TRAIL_SAMPLES)
        self.last_event: dict | None = None
        # 1 Hz CSV recorder (kept in the worker thread, off the GUI).
        self._csv_rows: list[list] = []
        self._last_csv_t = -1.0

    # -- lifecycle ---------------------------------------------------------- #

    @property
    def is_active(self) -> bool:
        return self._timer is not None

    @Slot()
    def start(self) -> None:
        """Create the timer on this thread and publish an initial frame."""
        if self._timer is not None:
            return
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()  # initial frame so the first paint never waits 100 ms

    @Slot()
    def stop(self) -> None:
        """Halt ticking and autosave any collected telemetry."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._autosave_csv()

    # -- controls ----------------------------------------------------------- #

    @Slot(float, float)
    def set_sun(self, azimuth_deg: float, elevation_deg: float) -> None:
        """Store the operator's sun; the next tick uses it.

        A manual jump rewrites the objective, so the Adam moment state is
        dropped as well: momentum and second moments accumulated on the old
        landscape drag on the re-convergence from a saturated boundary.
        Theta itself is untouched - the command stays bumpless.
        """
        az = _wrap_degrees(azimuth_deg)
        el = _clip_el_degrees(elevation_deg)
        jumped = math.hypot(
            ((az - self.sun_azimuth + 180.0) % 360.0) - 180.0,
            el - self.sun_elevation,
        ) > SUN_JUMP_RESET_DEG
        self.sun_azimuth = az
        self.sun_elevation = el
        if jumped:
            self.optimizer = self._make_optimizer()

    @Slot(float)
    def set_manual_theta(self, theta_rad: float) -> None:
        if self.autopilot:
            return
        self.manual_theta = max(THETA_MIN, min(THETA_MAX, float(theta_rad)))

    @Slot(bool)
    def set_autopilot(self, enabled: bool) -> None:
        """Transfer authority without a jump in the command."""
        if enabled == self.autopilot:
            return
        if enabled:
            self._seed_theta(self.manual_theta)
        else:
            self.manual_theta = self.theta_value
        self.autopilot = enabled
        self._tick()  # republish immediately so the UI sees the handover

    @Slot(bool)
    def set_orbit(self, enabled: bool) -> None:
        if bool(enabled) == self.orbit:
            return
        self.orbit = bool(enabled)
        if enabled:
            # Baseline for the sweep is whatever the sliders show right now.
            self.t_lvlh = 0.0

    # -- derived values ----------------------------------------------------- #

    @property
    def theta_value(self) -> float:
        """Current physical fold angle in radians (soft-constrained)."""
        return THETA_MID * (1.0 + math.tanh(float(self.z.detach())))

    def _seed_theta(self, theta_rad: float) -> None:
        """Hard-set the latent from a physical angle and drop stale moments."""
        ratio = max(THETA_MIN, min(THETA_MAX, float(theta_rad))) / THETA_MID - 1.0
        with torch.no_grad():
            self.z.fill_(math.atanh(max(-0.999999, min(0.999999, ratio))))
        self.optimizer = self._make_optimizer()

    def _make_optimizer(self) -> torch.optim.Optimizer:
        return torch.optim.Adam([self.z], lr=LEARNING_RATE)

    def _current_sun(self) -> tuple[torch.Tensor, float, float]:
        """Sun angles for this tick, applying the LVLH sweep in orbit mode."""
        if self.orbit:
            t = self.t_lvlh
            az = _wrap_degrees(self.sun_azimuth + ORBIT_RATE_DEG_S * t)
            el = _clip_el_degrees(
                self.sun_elevation
                + ORBIT_EL_SWING_DEG * math.sin(2.0 * math.pi * t / ORBIT_PERIOD_S)
            )
            return sun_vector_from_angles(az, el), az, el
        return (
            sun_vector_from_angles(self.sun_azimuth, self.sun_elevation),
            self.sun_azimuth,
            self.sun_elevation,
        )

    # -- control loop ------------------------------------------------------- #

    @Slot()
    def _tick(self) -> None:
        if self.orbit:
            self.t_lvlh += TICK_MS / 1000.0
        sun, sun_az, sun_el = self._current_sun()

        # Event detection: a *manual* jump of the sliders, not the slow
        # orbital sweep.  (Orbit mode is continuous by construction.)
        if not self.orbit and (
            abs(sun_az - self._prev_sun_az) > 1e-9
            or abs(sun_el - self._prev_sun_el) > 1e-9
        ):
            self.last_event = {
                "t": self.t,
                "delta_deg": math.hypot(
                    ((sun_az - self._prev_sun_az + 180.0) % 360.0) - 180.0,
                    sun_el - self._prev_sun_el,
                ),
            }
        self._prev_sun_az = sun_az
        self._prev_sun_el = sun_el

        grad_norm = self._optimize(sun)
        theta_auto = self.theta_value
        theta_array = theta_auto if self.autopilot else self.manual_theta

        auto = self.model.measure(theta_auto, sun)
        manual = self.model.measure(self.manual_theta, sun)
        array = self.model.measure(theta_array, sun)
        auto_power = auto.power
        manual_power = manual.power
        self.t += TICK_MS / 1000.0
        self._trail.append((math.degrees(theta_array), array.power))

        fresnel_T = (
            auto.fresnel_transmittance if self.autopilot else manual.fresnel_transmittance
        )
        eta_T = auto.eta_temperature if self.autopilot else manual.eta_temperature

        payload = {
            "met": self.t,
            "sun_az": sun_az,
            "sun_el": sun_el,
            "theta_auto": theta_auto,
            "theta_manual": self.manual_theta,
            "theta_array": theta_array,
            "theta_minor": array.theta_y,
            "psi": array.psi_x,
            "psi_y": array.psi_y,
            "cos_i": array.cos_incidence,
            "t_cell": array.cell_temperature_c,
            "fresnel_T": fresnel_T,
            "eta_T": eta_T,
            "power_auto": auto_power,
            "power_manual": manual_power,
            "power": array.power,
            "advantage": auto_power - manual_power,
            "grad": grad_norm,
            "autopilot": self.autopilot,
            "orbit": self.orbit,
            "t_lvlh": self.t_lvlh,
            "trail": list(self._trail),
            "events": [self.last_event] if self.last_event is not None else [],
        }
        self.last_event = None
        self.sample.emit(payload)

        self._csv_tick(payload)

    def _optimize(self, sun: torch.Tensor) -> float:
        """Run one control tick; report the *physical* dP/dtheta magnitude.

        The Adam loop steps the latent z.  The reported norm is dP/dtheta at
        the current physical angle (chain rule through the tanh map) so the
        log-scale chart reads a real physical quantity, not the latent slope.
        """
        if not self.autopilot:
            # Frozen manual authority: no autograd, no accrued optimizer state.
            return 0.0

        tanh_z = torch.tanh(self.z)
        theta = THETA_MID * (1.0 + tanh_z)
        self.optimizer.zero_grad(set_to_none=True)
        loss = -self.model(theta, sun)
        loss.backward()
        grad = self.z.grad
        latent_step = float(grad.abs().item()) if grad is not None else 0.0

        for step in range(STEPS_PER_TICK):
            if step > 0:
                # The first step reuses the gradient just measured for telemetry.
                self.optimizer.zero_grad(set_to_none=True)
                tz = torch.tanh(self.z)
                (-self.model(THETA_MID * (1.0 + tz), sun)).backward()
            self.optimizer.step()
        # Soft-boundary Jacobian: converts the latent gradient to the
        # physical dP/dtheta the telemetry chart expects.
        dtheta_dz = THETA_MID * (1.0 - math.tanh(float(self.z.detach())) ** 2)
        return latent_step * dtheta_dz

    # -- CSV telemetry ------------------------------------------------------- #

    def _csv_tick(self, payload: dict) -> None:
        met = float(payload["met"])
        if met - self._last_csv_t >= CSV_INTERVAL_S:
            self._last_csv_t = met
            self._csv_rows.append(
                [
                    met,
                    math.degrees(float(payload["theta_array"])),
                    math.degrees(float(payload["theta_manual"])),
                    float(payload["power"]),
                    float(payload["power_manual"]),
                    float(payload["power_auto"]),
                    float(payload["grad"]),
                    float(payload["cos_i"]),
                    float(payload["t_cell"]),
                    float(payload["fresnel_T"]),
                    float(payload["sun_az"]),
                    float(payload["sun_el"]),
                    "orbit" if payload["orbit"] else "manual",
                    str(payload["autopilot"]),
                ]
            )

    @Slot(str)
    def save_csv(self, path: str) -> bool:
        if not self._csv_rows:
            return False
        target = Path(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(
                    [
                        "met_s",
                        "theta_array_deg",
                        "theta_manual_deg",
                        "power_W",
                        "power_manual_W",
                        "power_auto_W",
                        "grad_norm",
                        "cos_incidence",
                        "t_cell_C",
                        "fresnel_T",
                        "sun_az_deg",
                        "sun_el_deg",
                        "sun_mode",
                        "autopilot",
                    ]
                )
                writer.writerows(self._csv_rows)
        except OSError:
            return False
        return True

    def _autosave_csv(self) -> None:
        self.save_csv(CSV_AUTOSAVE_NAME)


LATENT_SEED = math.atanh(INITIAL_THETA / THETA_MID - 1.0)
ORBIT_PERIOD_S = 360.0 / ORBIT_RATE_DEG_S   # one full LVLH sweep


class HeliosBackend(QObject):
    """QML-facing state holder for the Helios dashboard.

    Properties intentionally use plain scalars (degrees, watts, radians/s for
    display) rather than tensors so QML bindings stay cheap and serialisable.
    """

    sunAzimuthChanged = Signal()
    sunElevationChanged = Signal()
    manualThetaChanged = Signal()
    autopilotChanged = Signal()
    orbitChanged = Signal()
    thetaChanged = Signal()
    powerChanged = Signal()
    advantageChanged = Signal()
    gradChanged = Signal()
    metChanged = Signal()
    psiChanged = Signal()
    incidenceChanged = Signal()
    sampleReady = Signal("QVariantMap")
    csvExported = Signal(str)

    _sunRequested = Signal(float, float)
    _manualRequested = Signal(float)
    _modeRequested = Signal(bool)
    _orbitRequested = Signal(bool)
    _shutdownRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = SolarArrayModel(
            efficiency=DEFAULT_EFFICIENCY,
            solar_constant=SOLAR_CONSTANT,
            crease_half_angle_deg=45.0,
            fold_azimuth_deg=0.0,
        )
        self._sun_azimuth = DEFAULT_SUN_AZIMUTH
        self._sun_elevation = DEFAULT_SUN_ELEVATION
        self._manual_deg = math.degrees(INITIAL_MANUAL_THETA)
        self._theta_deg = math.degrees(INITIAL_THETA)
        self._power = 0.0
        self._advantage = 0.0
        self._grad = 0.0
        self._met = 0.0
        self._psi_deg = 0.0
        self._incidence = 0.0
        self._autopilot = True
        self._orbit = False

        self._thread = QThread()
        self._thread.setObjectName("helios-optimizer")
        self._worker = HeliosWorker(self._model)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.start)
        self._worker.sample.connect(self._on_sample)
        self._sunRequested.connect(self._worker.set_sun)
        self._manualRequested.connect(self._worker.set_manual_theta)
        self._modeRequested.connect(self._worker.set_autopilot)
        self._orbitRequested.connect(self._worker.set_orbit)
        self._shutdownRequested.connect(self._worker.stop)
        self._thread.start()

    # -- settable properties ------------------------------------------------ #

    @Property(float, notify=sunAzimuthChanged)
    def sunAzimuth(self) -> float:
        return self._sun_azimuth

    @sunAzimuth.setter
    def sunAzimuth(self, value: float) -> None:
        value = _wrap_degrees(value)
        if abs(value - self._sun_azimuth) < 1e-9:
            return
        self._sun_azimuth = value
        self.sunAzimuthChanged.emit()
        self._sunRequested.emit(self._sun_azimuth, self._sun_elevation)

    @Property(float, notify=sunElevationChanged)
    def sunElevation(self) -> float:
        return self._sun_elevation

    @sunElevation.setter
    def sunElevation(self, value: float) -> None:
        value = _clip_el_degrees(value)
        if abs(value - self._sun_elevation) < 1e-9:
            return
        self._sun_elevation = value
        self.sunElevationChanged.emit()
        self._sunRequested.emit(self._sun_azimuth, self._sun_elevation)

    @Property(float, notify=manualThetaChanged)
    def manualTheta(self) -> float:
        """Manual fold command.  While autopilot is engaged this reports the
        optimizer's command so the locked slider mirrors the live solution."""
        return self._theta_deg if self._autopilot else self._manual_deg

    @manualTheta.setter
    def manualTheta(self, value: float) -> None:
        if self._autopilot:
            return
        value = max(0.0, min(90.0, float(value)))
        if abs(value - self._manual_deg) < 1e-9:
            return
        self._manual_deg = value
        self.manualThetaChanged.emit()
        self._manualRequested.emit(math.radians(value))

    @Property(bool, notify=autopilotChanged)
    def autopilot(self) -> bool:
        return self._autopilot

    @autopilot.setter
    def autopilot(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._autopilot:
            return
        self._autopilot = enabled
        if not enabled:
            # Hand the current optimizer command to the manual slider without
            # waiting for the worker round-trip, so the knob does not jump.
            self._manual_deg = self._theta_deg
            self.manualThetaChanged.emit()
        self.autopilotChanged.emit()
        self._modeRequested.emit(enabled)

    @Property(bool, notify=orbitChanged)
    def orbitMode(self) -> bool:
        return self._orbit

    @orbitMode.setter
    def orbitMode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._orbit:
            return
        self._orbit = enabled
        self.orbitChanged.emit()
        self._orbitRequested.emit(enabled)

    # -- read-only properties ----------------------------------------------- #

    @Property(float, notify=thetaChanged)
    def theta(self) -> float:
        """Fold angle driving the array, in degrees."""
        return self._theta_deg

    @Property(float, notify=powerChanged)
    def power(self) -> float:
        return self._power

    @Property(float, notify=advantageChanged)
    def advantage(self) -> float:
        return self._advantage

    @Property(float, notify=gradChanged)
    def gradNorm(self) -> float:
        return self._grad

    @Property(float, notify=metChanged)
    def met(self) -> float:
        return self._met

    @Property(float, notify=psiChanged)
    def psi(self) -> float:
        """Transverse facet tilt in degrees (drives the 3D wing)."""
        return self._psi_deg

    @Property(float, notify=incidenceChanged)
    def incidence(self) -> float:
        """Cosine of the sun incidence angle on the effective aperture."""
        return self._incidence

    @Property(float, constant=True)
    def solarConstant(self) -> float:
        return SOLAR_CONSTANT

    # -- telemetry ---------------------------------------------------------- #

    @Slot(object)
    def _on_sample(self, data: dict) -> None:
        self._met = float(data["met"])
        self._theta_deg = math.degrees(float(data["theta_array"]))
        self._manual_deg = math.degrees(float(data["theta_manual"]))
        self._psi_deg = math.degrees(float(data["psi"]))
        self._incidence = float(data["cos_i"])
        self._power = float(data["power"])
        self._advantage = float(data["advantage"])
        self._grad = float(data["grad"])
        self._autopilot = bool(data["autopilot"])
        self._orbit = bool(data["orbit"])

        self.thetaChanged.emit()
        self.powerChanged.emit()
        self.advantageChanged.emit()
        self.gradChanged.emit()
        self.metChanged.emit()
        self.psiChanged.emit()
        self.incidenceChanged.emit()
        self.manualThetaChanged.emit()
        self.autopilotChanged.emit()
        self.orbitChanged.emit()
        self.sampleReady.emit(
            {
                "t": float(data["met"]),
                "power": float(data["power"]),
                "power_manual": float(data["power_manual"]),
                "power_auto": float(data["power_auto"]),
                "theta": math.degrees(float(data["theta_array"])),
                "theta_array": math.degrees(float(data["theta_array"])),
                "theta_manual": math.degrees(float(data["theta_manual"])),
                "theta_auto": math.degrees(float(data["theta_auto"])),
                "grad": float(data["grad"]),
                "t_cell": float(data["t_cell"]),
                "fresnel_T": float(data["fresnel_T"]),
                "events": [
                    (float(ev["t"]), float(ev["delta_deg"]))
                    for ev in data["events"]
                    if ev is not None
                ],
                "trail": [
                    [float(row[0]), float(row[1])] for row in data["trail"]
                ],
                "autopilot": bool(data["autopilot"]),
            }
        )

    # -- CSV export ---------------------------------------------------------- #

    @Slot()
    def exportCsv(self) -> None:
        """Write the 1 Hz telemetry ring to the project directory."""
        QMetaObject.invokeMethod(
            self._worker,
            "save_csv",
            Qt.ConnectionType.BlockingQueuedConnection,
            QMetaObject.fromType(str),
            Path.cwd() / CSV_EXPORT_NAME,
        )
        self.csvExported.emit(str(Path.cwd() / CSV_EXPORT_NAME))

    # -- lifecycle ---------------------------------------------------------- #

    @Slot()
    def shutdown(self) -> None:
        """Stop the timer on its own thread and join the QThread."""
        if not self._thread.isRunning():
            return
        if self._worker.is_active:
            QMetaObject.invokeMethod(
                self._worker, "stop", Qt.ConnectionType.BlockingQueuedConnection
            )
        self._thread.quit()
        self._thread.wait(2000)