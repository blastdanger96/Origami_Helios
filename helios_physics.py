"""Differentiable physics for Project Helios (audited & upgraded core).

Mission
-------
A LEO spacecraft carries a deployable Miura-ori solar array.  The array has a
single controlled degree of freedom: the primary (transverse) fold angle
``theta``.  The objective is the instantaneous electrical power the folded
aperture captures.  Everything here is a pure function of ``theta`` and the
sun incidence vector, written in PyTorch so the controller in
``helios_backend`` can differentiate it at 10 Hz.

Kinematics (Part-1 audit, upgrade 2)
------------------------------------
A real Miura cell has *two* coupled fold angles.  The major (transverse) angle
``theta_x`` is the controlled knob; the minor (longitudinal) angle is slaved by
the classical Poisson coupling (nu_Miura = -cos alpha, Tachi 2011 / Schenk &
Guest PNAS 2013)::

    tan(theta_y / 2) = cos(alpha) * tan(theta_x / 2)

The two facet families tilt by::

    psi_x = atan2(cos(alpha) * sin(theta_x), cos(theta_x))
    psi_y = atan2(sin(alpha) * sin(theta_y), cos(theta_y))

and the homogenised effective surface normal becomes the *two-axis corrugation
law* (the unit normal of a doubly-corrugated height field)::

    n(theta) ~ (tan psi_x, tan psi_y, 1),  normalised.

evaluated in the atan2-safe form ``(sin psi_x cos psi_y, sin psi_y cos psi_x,
cos psi_x cos psi_y)`` so nothing blows up at the stops.  ``alpha -> 0``
collapses ``psi_y -> 0`` and the law degenerates to the flat plate - the old
single-tilt model is the special case ``psi_y = 0``.

Area loss is no longer a fitted self-shading coefficient: after homogenising,
the exact projected aperture of the folded sheet is

    A_eff(theta) = A0 * cos(psi_x) * cos(psi_y)

(the product foreshortening of the two crease families).

Objective (Part-1 audit, upgrades 3 & 4)
----------------------------------------
::

    P(theta, s) = A_eff(theta) * max(0, n.s) * tau(i) * eta(T_cell) * G

with
    i        incidence angle, cos i = n . s
    tau(i)   cover-glass transmittance: exact unpolarised Fresnel for
             glass-to-air interface (n_glass = 1.5) - flat to ~45 deg, rolls
             off toward grazing incidence.
    T_cell   radiation-balance steady state, T_0 + dT * (n . s)
    eta(T)   eta_ref * (1 + beta * (T - T_ref)),  beta = -0.22 %/deg C
             (typical end-of-life triple-junction GaAs coefficient).

Net effect: the fully sunlit facets run hot and their glass reflects more at
grazing angles, so the optimum migrates *away* from perfect incidence - a real
second-order trade-off that deepens the interior maximum.

All arithmetic runs in float64 on CPU.   The model has a single scalar input,
so float64 costs nothing and keeps gradient norms legible down to ~1e-8 on the
log-scale diagnostic chart.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import Tensor, nn

# --------------------------------------------------------------------------- #
# Constants - representative of a small 12 m^2 class deployable wing.
# --------------------------------------------------------------------------- #
DEFAULT_AREA_M2 = 12.0          # total cell area of the deployed aperture
DEFAULT_EFFICIENCY = 0.29       # triple-junction GaAs, reference temperature
SOLAR_CONSTANT_W_M2 = 1361.0    # 1 AU, AM0
DEFAULT_CREASE_HALF_ANGLE = 45.0

# Thermal balance (Part-1 audit, upgrade 4).
T_CELL_MIN_C = -20.0            # eclipsed / dark-side steady state
T_CELL_RANGE_C = 75.0           # rise at perfect normal incidence
T_REF_C = 28.0                  # datasheet reference for eta_ref
TEMP_COEFF_PER_C = -0.0022      # relative eta change per degree C

# Cover glass (Part-1 audit, upgrade 4).
GLASS_INDEX = 1.5


@dataclass(frozen=True)
class ArrayProbe:
    """Immutable snapshot of one optical/thermal evaluation (telemetry/QML)."""

    theta: float            # major fold, rad
    theta_y: float          # Poisson-slaved minor fold, rad
    psi_x: float            # transverse facet tilt, rad
    psi_y: float            # longitudinal facet tilt, rad
    normal: tuple
    sun: tuple
    cos_incidence: float
    incidence_deg: float
    cell_temperature_c: float
    eta_temperature: float
    fresnel_transmittance: float
    effective_area: float
    power: float


class SolarArrayModel(nn.Module):
    """Differentiable Miura-ori aperture model (audited objective).

    The module owns no trainable state: ``theta`` is supplied by the caller and
    the controller optimises a latent reparameterisation of it.  The module is
    stateless and safe to evaluate from several places (worker thread,
    landscape sweeps, tests) without touching optimizer state.

    Args:
        area_m2: Deployed cell area in square metres.
        efficiency: Photovoltaic conversion efficiency at ``T_REF_C``.
        solar_constant: Irradiance at the array in W/m^2.
        crease_half_angle_deg: Miura crease half-angle ``alpha`` in degrees.
        fold_azimuth_deg: Body-frame azimuth the effective normal tilts toward.
            Defaults to the crease half-angle (original MVP layout); the QML
            backend passes 0 so the normal lies in the X-Z plane.
    """

    def __init__(
        self,
        area_m2: float = DEFAULT_AREA_M2,
        efficiency: float = DEFAULT_EFFICIENCY,
        solar_constant: float = SOLAR_CONSTANT_W_M2,
        crease_half_angle_deg: float = DEFAULT_CREASE_HALF_ANGLE,
        fold_azimuth_deg: float | None = None,
    ) -> None:
        super().__init__()
        self.area_m2 = float(area_m2)
        self.efficiency = float(efficiency)
        self.solar_constant = float(solar_constant)
        self.crease_half_angle = math.radians(float(crease_half_angle_deg))
        self.cos_alpha = math.cos(self.crease_half_angle)
        self.sin_alpha = math.sin(self.crease_half_angle)
        azimuth = (
            float(crease_half_angle_deg)
            if fold_azimuth_deg is None
            else float(fold_azimuth_deg)
        )
        self.fold_azimuth = math.radians(azimuth)
        self.cos_azimuth = math.cos(self.fold_azimuth)
        self.sin_azimuth = math.sin(self.fold_azimuth)

    # -- kinematics --------------------------------------------------------- #

    def facet_tilts(self, theta: Tensor) -> tuple[Tensor, Tensor, Tensor]:
        """Return (theta_y, psi_x, psi_y) for the major fold angle ``theta``.

        All three use numerically stable ``atan2``/half-angle forms: the minor
        fold never exceeds ``2*atan(cos alpha) = 67.5 deg`` for alpha = 45 deg,
        so its tangent is finite everywhere and the autograd graph stays well
        conditioned at both mechanical stops.
        """
        theta_y = 2.0 * torch.atan(self.cos_alpha * torch.tan(theta / 2.0))
        psi_x = torch.atan2(self.cos_alpha * torch.sin(theta), torch.cos(theta))
        psi_y = torch.atan2(self.sin_alpha * torch.sin(theta_y), torch.cos(theta_y))
        return theta_y, psi_x, psi_y

    def panel_normal(self, theta: Tensor) -> Tensor:
        """Unit effective surface normal (two-axis corrugation law), shape (3,).

        Degenerates to the flat-plate normal (0, 0, 1) at theta = 0 and to the
        fully-folded azimuth-0 normal as theta -> 90 deg.  Renormalisation is
        safe: the third component stays strictly positive for theta in
        [0, 90 deg] because psi_y < 90 deg always.
        """
        _, psi_x, psi_y = self.facet_tilts(theta)
        n = torch.stack(
            (
                torch.sin(psi_x) * torch.cos(psi_y),
                torch.sin(psi_y) * torch.cos(psi_x),
                torch.cos(psi_x) * torch.cos(psi_y),
            )
        )
        return n / torch.linalg.vector_norm(n)

    def effective_area(self, theta: Tensor) -> Tensor:
        """Exact projected aperture (m^2): product foreshortening of the folds."""
        _, psi_x, psi_y = self.facet_tilts(theta)
        return self.area_m2 * torch.cos(psi_x) * torch.cos(psi_y)

    def cell_temperature(self, cos_incidence: Tensor) -> Tensor:
        """Radiation-balance steady state in degrees C (differentiable)."""
        return T_CELL_MIN_C + T_CELL_RANGE_C * cos_incidence

    def temperature_efficiency(self, cell_temperature_c: Tensor) -> Tensor:
        """Relative cell efficiency at temperature (linearised datasheet law)."""
        return 1.0 + TEMP_COEFF_PER_C * (cell_temperature_c - T_REF_C)

    @staticmethod
    def fresnel_transmittance(cos_incidence: Tensor, glass_index: float = GLASS_INDEX) -> Tensor:
        """Unpolarised air->glass Fresnel transmittance ``tau(i)``.

        Exact two-parameter Fresnel with Snell's law; both internal branches
        stay finite because ``sin i / n_glass <= 1 / 1.5`` for any incidence.
        Monotonically decreasing in i: ~0.96 at 0 deg incidence, ~0.9 at 60,
        -> 0 at 90 (the cover glass becomes a mirror past the Brewster region).
        """
        cos_i = torch.clamp(cos_incidence, 1e-9, 1.0)
        sin_i = torch.sqrt(torch.clamp(1.0 - cos_i * cos_i, 0.0, 1.0))
        cos_t = torch.sqrt(
            torch.clamp(1.0 - (sin_i / glass_index) ** 2, 0.0, 1.0)
        )
        r_s = (cos_i - glass_index * cos_t) / (cos_i + glass_index * cos_t)
        r_p = (glass_index * cos_i - cos_t) / (glass_index * cos_i + cos_t)
        return 1.0 - 0.5 * (r_s * r_s + r_p * r_p)

    # -- objective ---------------------------------------------------------- #

    def forward(self, theta: Tensor | float, sun_vector) -> Tensor:
        """Return the captured electrical power in watts (differentiable).

        Args:
            theta: Scalar major fold angle in radians, shape ``()``.  May also
                be a plain Python float (telemetry paths); the tensor path is
                preserved exactly so autograd still sees an ``nn.Parameter``
                when one is supplied.
            sun_vector: Unit sun direction in the body frame, shape ``(3,)``.

        Returns:
            Scalar tensor ``P = A_eff * max(0, n.s) * tau(i) * eta(T) * G``.
        """
        if not isinstance(theta, Tensor):
            theta = torch.tensor(float(theta), dtype=torch.float64)
        sun = torch.as_tensor(sun_vector, dtype=theta.dtype, device=theta.device)
        normal = self.panel_normal(theta)
        cos_incidence = torch.clamp(torch.dot(normal, sun), min=0.0)
        power = (
            self.effective_area(theta)
            * cos_incidence
            * self.fresnel_transmittance(cos_incidence)
            * self.temperature_efficiency(self.cell_temperature(cos_incidence))
            * self.efficiency
            * self.solar_constant
        )
        return power

    # -- non-differentiable inspection -------------------------------------- #

    @torch.no_grad()
    def measure(self, theta: float, sun_vector) -> ArrayProbe:
        """Evaluate the full optical/thermal state without autograd.

        Used by the worker thread for telemetry (no retained graph) and by the
        tests / landscape sweeps to assert on the individual objective terms.
        """
        th = torch.tensor(float(theta), dtype=torch.float64)
        sun = torch.as_tensor(sun_vector, dtype=torch.float64)
        normal = self.panel_normal(th)
        cos_i = float(torch.clamp(torch.dot(normal, sun), min=0.0))
        theta_y = float(self.facet_tilts(th)[0])
        psi_x, psi_y = (float(v) for v in self.facet_tilts(th)[1:])
        area = float(self.effective_area(th))
        t_cell = float(self.cell_temperature(torch.tensor(cos_i)))
        eta_t = float(self.temperature_efficiency(torch.tensor(t_cell)))
        tau = float(self.fresnel_transmittance(torch.tensor(cos_i)))
        power = area * cos_i * tau * eta_t * self.efficiency * self.solar_constant
        return ArrayProbe(
            theta=float(th),
            theta_y=theta_y,
            psi_x=psi_x,
            psi_y=psi_y,
            normal=tuple(float(v) for v in normal),
            sun=tuple(float(v) for v in sun),
            cos_incidence=cos_i,
            incidence_deg=math.degrees(math.acos(max(-1.0, min(1.0, cos_i)))) if cos_i > 0.0 else 90.0,
            cell_temperature_c=t_cell,
            eta_temperature=eta_t,
            fresnel_transmittance=tau,
            effective_area=area,
            power=power,
        )
