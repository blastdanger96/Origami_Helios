"""Adam-optimizer inspection bridge for the Project Helios AI Optimizer view.

Why a bridge
------------
The PyTorch optimizer lives on the ``helios-optimizer`` QThread; the QML scene
graph lives on the GUI thread.  Everything QML needs (momentum, variance,
gradient, the live landscape) therefore crosses the thread boundary as plain
scalars/float lists via the already-threadsafe ``sampleReady`` contract, and
everything the user changes (learning rate, betas, epsilon) flows back as
queued signal invocations — no direct tensor access from the GUI thread, ever.

Live hyperparameter contract
----------------------------
``setLearningRate`` / ``setBeta1`` / ``setBeta2`` / ``setEpsilon`` re-create the
``torch.optim.Adam`` object on the worker thread with the new settings while
**transplanting the moment state**: the parameter instance is the same
``nn.Parameter``, so ``exp_avg`` / ``exp_avg_sq`` survive untouched.  Sliders
must reshape optimizer behaviour, never erase its memory.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Property, QObject, Signal, Slot


class HeliosOptimizerBridge(QObject):
    """QML-facing stream of Adam internals + live hyperparameter controls."""

    lrChanged = Signal()
    beta1Changed = Signal()
    beta2Changed = Signal()
    epsChanged = Signal()
    momentumChanged = Signal()
    varianceChanged = Signal()
    gradChanged = Signal()
    stepChanged = Signal()
    landscapeChanged = Signal()
    settledChanged = Signal()

    def __init__(self, backend, parent=None) -> None:
        super().__init__(parent)
        self._backend = backend
        # Display targets mirror the worker's *requested* hyperparameters; the
        # live optimizer state arrives through the sampleReady stream.
        self._lr = 0.02
        self._beta1 = 0.9
        self._beta2 = 0.999
        self._eps = 1e-8
        self._momentum = 0.0
        self._variance = 0.0
        self._grad = 0.0
        self._step = 0.0
        self._landscape: list[float] = []
        self._peak_grad = 1e-6
        self._settled = False
        backend.sampleReady.connect(self._on_sample)

    # -- inbound stream ------------------------------------------------------ #

    @Slot(object)
    def _on_sample(self, data: dict) -> None:
        lr = float(data["adam_lr"])
        if lr != self._lr:
            self._lr = lr
            self.lrChanged.emit()
        m = float(data["adam_m"])
        if m != self._momentum:
            self._momentum = m
            self.momentumChanged.emit()
        v = float(data["adam_v"])
        if v != self._variance:
            self._variance = v
            self.varianceChanged.emit()
        g = float(data["theta_grad"])
        if g != self._grad:
            self._grad = g
            self.gradChanged.emit()
            # Auto-settle rule: rolling peak with a 0.98/tick decay keeps the
            # 10 Hz event spike in memory for ~2 s; |grad| < 1 % of peak means
            # Adam has exhausted the local gradient and the panel shows SETTLED.
            self._peak_grad = max(self._peak_grad * 0.98, abs(g) or self._peak_grad)
            settled = abs(g) < 0.01 * self._peak_grad
            if settled != self._settled:
                self._settled = settled
                self.settledChanged.emit()
        s = float(data["dtheta"])
        if s != self._step:
            self._step = s
            self.stepChanged.emit()
        landscape = [float(p) for p in data["landscape"]]
        if landscape != self._landscape:
            self._landscape = landscape
            self.landscapeChanged.emit()

    # -- outbound controls --------------------------------------------------- #

    @Slot(float)
    def setLearningRate(self, value: float) -> None:
        value = max(1e-8, min(1.0, float(value)))
        self._lr = value
        self.lrChanged.emit()
        self._backend.setAdamLr(value)

    @Slot(float)
    def setBeta1(self, value: float) -> None:
        value = max(0.0, min(0.9995, float(value)))
        self._beta1 = value
        self.beta1Changed.emit()
        self._backend.setAdamBetas(value, self._beta2)

    @Slot(float)
    def setBeta2(self, value: float) -> None:
        value = max(0.0, min(0.99999, float(value)))
        self._beta2 = value
        self.beta2Changed.emit()
        self._backend.setAdamBetas(self._beta1, value)

    @Slot(float)
    def setEpsilon(self, value: float) -> None:
        value = max(1e-12, min(1e-1, float(value)))
        self._eps = value
        self.epsChanged.emit()
        self._backend.setAdamEps(value)

    # -- QML properties ------------------------------------------------------ #

    @Property(float, notify=lrChanged)
    def lr(self) -> float:
        return self._lr

    @Property(float, notify=beta1Changed)
    def beta1(self) -> float:
        return self._beta1

    @Property(float, notify=beta2Changed)
    def beta2(self) -> float:
        return self._beta2

    @Property(float, notify=epsChanged)
    def epsilon(self) -> float:
        return self._eps

    @Property(float, notify=momentumChanged)
    def momentum(self) -> float:
        """|exp_avg| on the latent -- the Adam first-moment magnitude."""
        return self._momentum

    @Property(float, notify=varianceChanged)
    def variance(self) -> float:
        """|exp_avg_sq| on the latent -- the Adam second-moment magnitude."""
        return self._variance

    @Property(float, notify=gradChanged)
    def thetaGrad(self) -> float:
        """Physical dP/dtheta at the live fold angle (W/rad)."""
        return self._grad

    @Property(float, notify=stepChanged)
    def stepSize(self) -> float:
        """Per-tick theta change in radians (signed)."""
        return self._step

    @Property(bool, notify=settledChanged)
    def settled(self) -> bool:
        """True when |grad| < 1 % of its recent peak: no more useful descent."""
        return self._settled

    @Property("QVariantList", notify=landscapeChanged)
    def landscape(self) -> list[float]:
        return self._landscape

    # -- formatting helpers for QML ------------------------------------------ #

    @Slot(float, result=str)
    def sci(self, value: float) -> str:
        if value <= 0:
            return "0"
        exp = math.floor(math.log10(value))
        mant = value / 10.0 ** exp
        return f"{mant:.2f}e{exp}"

    @Slot(float, result=str)
    def fmtDeg(self, value: float) -> str:
        return f"{math.degrees(value):+.3f}"
