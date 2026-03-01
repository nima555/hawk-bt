"""hawk_backtester -- Python backtesting engine for the Hawk trading simulator."""

from hawk_backtester.runtime.engine_api import Snapshot, Engine, EXIT_MARGIN_CALL, EXIT_COMPLETE
from hawk_backtester.runtime.rust_engine_async_adapter import RustEngineAsyncAdapter
from hawk_backtester.runtime.loop import run_backtest, run_attached, BacktestResult
from hawk_backtester.strategy.api import Strategy, Context, SessionState, EngineProtocol, Candles
from hawk_backtester.logging import configure as configure_logging
from hawk_backtester.hawk_engine import HawkEngine

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
