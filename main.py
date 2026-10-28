"""Project Helios — PySide6/QML entry point.

Boot order matters:

1. Cap the torch intra-op thread pool *before* importing anything else that
   indirectly initialises it.  The controller solves a one-parameter problem;
   letting torch spawn a pool per core would cost more in scheduling overhead
   than the arithmetic itself and would compete with the GUI thread for time.
2. Create the ``QGuiApplication``.  QML runs on the scene graph renderer, so
   no special OpenGL surface format is needed — the 3D stage is a software
   ``QQuickPaintedItem`` and the glass panels are QQuick shapes.
3. Register the Python types under the ``Helios`` QML module, expose the
   ``HeliosBackend`` singleton as the ``backend`` context property, load
   ``qml/Main.qml`` and hand control to the Qt event loop.  The optimizer
   runs on its own QThread inside :class:`helios_backend.HeliosBackend`.

Run with:  ./.venv/bin/python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import torch

torch.set_num_threads(1)

from PySide6.QtCore import QUrl                        # noqa: E402
from PySide6.QtGui import QGuiApplication              # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType  # noqa: E402

from helios_backend import HeliosBackend               # noqa: E402
from helios_charts import LiveChart                    # noqa: E402
from helios_optimizer import HeliosOptimizerBridge     # noqa: E402
from helios_render import SatelliteView                # noqa: E402
from helios_render_views import (                      # noqa: E402
    EarthOrbitView,
    HorizonChart,
    OptimizerSurfaceView,
    TerminatorMap,
)

QML_DIR = Path(__file__).resolve().parent / "qml"


def main() -> int:
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Project Helios")
    app.setApplicationDisplayName("Project Helios")
    app.setOrganizationName("Helios Demo")

    qmlRegisterType(HeliosBackend, "Helios", 1, 0, "HeliosBackend")
    qmlRegisterType(SatelliteView, "Helios", 1, 0, "SatelliteView")
    qmlRegisterType(LiveChart, "Helios", 1, 0, "LiveChart")
    qmlRegisterType(EarthOrbitView, "Helios", 1, 0, "EarthOrbitView")
    qmlRegisterType(OptimizerSurfaceView, "Helios", 1, 0, "OptimizerSurfaceView")
    qmlRegisterType(HorizonChart, "Helios", 1, 0, "HorizonChart")
    qmlRegisterType(TerminatorMap, "Helios", 1, 0, "TerminatorMap")

    # The dashboard drives a single HeliosBackend instance; QML binds to it
    # through the `backend` context property (Main.qml references it from
    # every panel, gauge and chart).
    backend = HeliosBackend()
    app.aboutToQuit.connect(backend.shutdown)

    engine = QQmlApplicationEngine()
    context = engine.rootContext()
    context.setContextProperty("backend", backend)
    context.setContextProperty("monoFont", "SF Mono")
    # QML-facing Adam-state bridge: streams optimizer internals out of the
    # worker thread and feeds slider commands back through queued slots.
    optimizer = HeliosOptimizerBridge(backend)
    context.setContextProperty("optimizer", optimizer)

    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        sys.stderr.write("error: failed to load qml/Main.qml\n")
        backend.shutdown()
        return 1

    rc = app.exec()
    # Dispose of the QML bindings before the backend object so bindings never
    # re-evaluate against a half-released context property at teardown.
    del engine
    return rc


if __name__ == "__main__":
    sys.exit(main())
