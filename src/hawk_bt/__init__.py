"""hawk_bt -- Python backtesting engine for the Hawk trading simulator."""

from hawk_bt.runtime.engine_api import Snapshot, Engine, EXIT_MARGIN_CALL, EXIT_COMPLETE
from hawk_bt.runtime.rust_engine_async_adapter import RustEngineAsyncAdapter
from hawk_bt.runtime.loop import run_backtest, run_attached, BacktestResult
from hawk_bt.strategy.api import Strategy, Context, SessionState, EngineProtocol, Candles
from hawk_bt.logging import configure as configure_logging
from hawk_bt.hawk_engine import HawkEngine

__all__ = [
    "HawkEngine",
    "Snapshot",
    "Engine",
    "EngineProtocol",
    "RustEngineAsyncAdapter",
    "run_backtest",
    "run_attached",
    "BacktestResult",
    "Strategy",
    "Context",
    "SessionState",
    "Candles",
    "EXIT_MARGIN_CALL",
    "EXIT_COMPLETE",
    "configure_logging",
]
