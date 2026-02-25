"""
Thin wrapper to call the Rust batch runner (py_engine_rust.run_batch).

This is a PoC: it only builds statics (current_rate/time/step/total) and
does not implement ticket/margin logic. Use for performance exploration.
"""

from __future__ import annotations

import numpy as np

try:
    from py_engine_rust import run_batch as _run_batch
    from py_engine_rust import RustEngine as _RustEngine
except Exception as _e:  # pragma: no cover - optional dependency
    _run_batch = None
    _RustEngine = None
    _import_err = _e
else:
    _import_err = None


def rust_statics_batch(ohlc5: np.ndarray) -> np.ndarray:
    """
    Run the Rust batch statics builder.

    Args:
        ohlc5: np.ndarray shape (N,5) [time, open, close, high, low], float64
    Returns:
        np.ndarray shape (N,20) statics (current_rate/time/step/total filled, others 0)
    """
    if _run_batch is None:
        raise RuntimeError(f"py_engine_rust not available: {_import_err}")
    if not isinstance(ohlc5, np.ndarray):
        raise TypeError("ohlc5 must be numpy.ndarray")
    if ohlc5.ndim != 2 or ohlc5.shape[1] != 5:
        raise ValueError(f"ohlc5 must be shape (N,5), got {ohlc5.shape}")
    return _run_batch(ohlc5)


class RustEngineAPI:
    """
    EngineAPI互換インタフェースの簡易ラッパー（現状はダミー実装）。
    """

    def __init__(self, ohlc5: np.ndarray):
        if _RustEngine is None:
            raise RuntimeError(f"py_engine_rust not available: {_import_err}")
        if not isinstance(ohlc5, np.ndarray):
            raise TypeError("ohlc5 must be numpy.ndarray")
        if ohlc5.ndim != 2 or ohlc5.shape[1] != 5:
            raise ValueError(f"ohlc5 must be shape (N,5), got {ohlc5.shape}")
        self._eng = _RustEngine(ohlc5)

    def init_ohlc5(self, ohlc5: np.ndarray, timeout: float = 10.0) -> None:  # noqa: ARG002
        # コンストラクタで受け取るためここはノーオペ
        return None

    def step_next(self, timeout: float = 10.0) -> None:  # noqa: ARG002
        self._eng.step_next()
        return None

    def get_statics(self, timeout: float = 10.0) -> np.ndarray:  # noqa: ARG002
        return np.asarray(self._eng.get_statics())

    def get_statics_series(self, timeout: float = 10.0) -> np.ndarray:  # noqa: ARG002
        return np.asarray(self._eng.statics_series()).reshape(-1, 20)

    def affect(self, timeout: float = 10.0) -> np.ndarray:  # noqa: ARG002
        return np.asarray(self._eng.affect()).reshape(-1, 5)

    def close_step(self, flags, actions, ratios, timeout: float = 10.0) -> np.ndarray:  # noqa: ARG002
        return np.asarray(self._eng.close_step(flags, actions, ratios)).reshape(-1, 5)

    def get_ticket_traces(self, timeout: float = 10.0) -> np.ndarray:  # noqa: ARG002
        return np.asarray(self._eng.get_ticket_traces()).reshape(-1, 12)
