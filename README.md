# hawk-bt — Python Client for Hawk-Backtester

A Python client library for controlling the browser-based WASM trading engine.
Build, backtest, and evaluate algorithmic trading strategies programmatically.

This library works alongside the [Hawk-Backtester](https://app.hawk-backtester.com) web app — your strategies run locally in Python while the simulation engine runs in the browser via WASM. See the [documentation](https://app.hawk-backtester.com/py-engine/) for detailed usage and setup instructions.

## Architecture

```
Browser (WASM Engine + UI)
    ↕  WebSocket (binary, lock-step RPC)
hawk-bt (Python)
    ↕  py_engine_rust (Rust extension, required)
```

- **WASM Engine**: The core trading simulation running in the browser
- **hawk-bt**: Python client handling strategy execution and state management
- **py_engine_rust**: Rust extension for WebSocket communication, binary codec, and RPC (required dependency)

## Requirements

- Python >= 3.10
- `py-engine-rust` (Rust extension, **required**)
- `numpy >= 1.23`

```bash
pip install -e .
```

## Quick Start

```python
import asyncio
from py_engine.runtime.rust_engine_async_adapter import RustEngineAsyncAdapter
from py_engine.runtime.loop import run_attached
from py_engine.strategy.api import Strategy, Context

class MyStrategy(Strategy):
    async def step(self, ctx: Context) -> None:
        s = ctx.state.statics
        price = s.current_rate

        if price > 100.0 and s.tickets_num == 0:
            await ctx.engine.place_ticket(side="buy", units=10, sub_limit_pips=5.0, stop_order_pips=3.0)

async def main():
    engine = RustEngineAsyncAdapter(host="127.0.0.1", port=8787)
    await engine.start()
    await engine.wait_connected(timeout=None)

    result = await run_attached(engine, MyStrategy(), gate_policy="eager")
    print(f"Steps: {result.steps}, Final assets: {result.final_assets()}")

asyncio.run(main())
```

## What You Can Do

### 1. Write a Strategy

Subclass `Strategy` and implement `step()`. It is called automatically on every simulation step.

```python
class Strategy(ABC):
    @abstractmethod
    async def step(self, ctx: Context) -> None: ...
```

Available via `ctx`:
- `ctx.state.statics` — Current assets, price, and position info (`Statics`)
- `ctx.engine` — Engine operations (`BoundEngine`)
- `ctx.state.done` — Simulation completion flag
- `ctx.user` — Free-use `dict` for state persistence, logging, etc.

### 2. Trade Operations

#### Market Entry (place_ticket)

```python
out = await ctx.engine.place_ticket(
    side="buy",           # "buy" | "sell"
    units=100,            # lot size
    sub_limit_pips=5.0,   # TP (absolute price difference, optional)
    stop_order_pips=3.0,  # SL (absolute price difference, optional)
    trail_pips=2.0,       # trailing stop (optional)
)
# out: shape (14,) — [0]=flag (ticket ID), [1..4]=reward fields, [5]=current_rate, ...
```

#### Pending Order (place_token)

```python
out = await ctx.engine.place_token(
    side="sell",          # "buy" | "sell"
    order="limit",        # "limit" | "stop"
    price=90.0,           # order price
    units=80,
    sub_limit_pips=8.0,   # TP (optional)
    stop_order_pips=25.0, # SL (optional)
    trail_pips=None,      # trailing stop (optional)
    time_limits=240.0,    # expiry in steps (optional)
)
# out: shape (18,) — [0]=flag (token ID), ...
```

#### Close Position (close_step)

```python
events = await ctx.engine.close_step(
    flags=[ticket_flag],  # target ticket flag (ID)
    actions=[1],          # 1=full close, 2=partial close (REDUCE)
    ratios=[0.0],         # ratio for action=2 (0.0–1.0)
)
# events: shape (N, 5) — close results
```

Batch closing of multiple tickets is supported by passing arrays.

### 3. Market Data

```python
# Current state
statics = await ctx.engine.get_statics()
statics.assets           # account balance
statics.virtual_assets   # balance including unrealized P&L
statics.current_rate     # current price
statics.current_step     # current step
statics.total_steps      # total steps
statics.margin_ratio     # margin ratio
statics.tickets_num      # open ticket count
statics.token_num        # pending order count
# ... 20+ fields

# Ticket list
tickets = await ctx.engine.get_ticket_list()
# shape (rows, cols) — each row is one ticket's details
```

### 4. Running Simulations

#### Attached Mode (browser-driven)

Runs the strategy against OHLC data already loaded in the browser.

```python
result = await run_attached(engine, strategy, gate_policy="eager")
```

#### Backtest Mode (Python-driven)

Sends OHLC data from Python and runs the backtest.

```python
result = await run_backtest(engine, strategy, ohlc5, steps=5000)
```

`ohlc5`: `np.ndarray` shape `(N, 5)` — `[time_ms, open, close, high, low]`

#### BacktestResult

```python
result.steps              # number of steps executed
result.assets             # np.ndarray — asset history per step
result.virtual_assets     # np.ndarray — asset history including unrealized P&L
result.price              # np.ndarray — price history
result.final_assets()     # final account balance
result.max_drawdown()     # max drawdown (negative value)
```

### 5. Connection

```python
from py_engine.runtime.rust_engine_async_adapter import RustEngineAsyncAdapter

engine = RustEngineAsyncAdapter(host="127.0.0.1", port=8787)
await engine.start()
await engine.wait_connected()
```

### 6. Gate Policy

Controls intra-step state synchronization. Can be set in the browser UI or auto-detected via `get_gate_policy_hint()`.

- **`eager`** (default): Runs `affect` + `get_statics` after every operation. Accurate but slower.
- **`step_end`**: Syncs only at step end. Faster but intermediate state may be stale.

```python
gate_policy = await engine.get_gate_policy_hint() or "eager"
result = await run_attached(engine, strategy, gate_policy=gate_policy)
```

## Responsibility Split

### hawk-bt handles

- WebSocket connection management (server startup, connection waiting, disconnect detection)
- Binary protocol encode/decode (Rust implementation)
- RPC communication (send → await response, timeout, error handling)
- Step loop control (`run_attached` / `run_backtest`)
- Automatic state sync (`BoundEngine` runs `affect` → `get_statics`)
- Termination detection (margin call `GAME_BREAK` / completion `GAME_END`)
- Progress display (`create_progress_printer`)

### You handle

- **Strategy logic**: When, what, and how much to trade
- **Parameter design**: TP/SL levels, lot sizes, entry conditions
- **Risk management**: Max positions, margin ratio monitoring, drawdown limits
- **OHLC data preparation**: Provide `(N, 5)` numpy arrays for backtest mode
- **Result analysis**: Interpret `BacktestResult`, evaluate performance
- **Browser setup**: Open the browser UI with the WASM engine before connecting

### hawk-bt does NOT

- Recommend or optimize strategies
- Automatically limit risk (you handle this in `step()`)
- Fetch or preprocess OHLC data
- Manage the browser-side WASM engine

## TP/SL Behavior

- TP/SL values are **absolute price differences** (not pips or percentages)
- Buy TP hit: `high >= open_rate + sub_limit_pips`
- Buy SL hit: `low <= open_rate - stop_order_pips`
- When both TP and SL are hit on the same bar: **SL takes priority**
- Close price is set to the bar's close price (not the exact TP/SL level)

## Project Structure

```
py_engine/
├── src/py_engine/
│   ├── runtime/
│   │   ├── engine_api.py     # Statics, BoundEngine
│   │   ├── loop.py           # run_backtest, run_attached, BacktestResult
│   │   ├── rust_engine_async_adapter.py  # RustEngineAsyncAdapter
│   │   └── progress.py       # Progress display
│   ├── strategy/
│   │   └── api.py            # Strategy, Context, EngineState, Engine protocol
│   └── results/              # (extensible)
├── examples/
│   └── simple_ma.py          # MA crossover strategy example
└── pyproject.toml
```

## License

[MIT](LICENSE)
