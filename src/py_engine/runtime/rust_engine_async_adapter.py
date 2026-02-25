from __future__ import annotations

import asyncio
import time
from typing import Optional

import numpy as np
from py_engine.runtime.engine_api import Statics


class RustEngineAsyncAdapter:
    """
    py_engine_rust.RustEngineAsync をそのまま await で呼ぶ薄いラッパ。
    to_thread 不要。
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8787, *, start_seq: int = 1):
        try:
            from py_engine_rust import RustEngineAsync as _RustEngineAsync  # type: ignore
        except Exception as e:  # pragma: no cover - optional dependency
            raise RuntimeError(f"py_engine_rust is not available: {e}") from e
        self._eng = _RustEngineAsync(host, port, start_seq)

    async def start(self) -> None:
        await self._eng.start()

    async def wait_connected(self, timeout: Optional[float] = None) -> None:
        await self._eng.wait_connected(timeout)

    async def init_ohlc5(self, ohlc5: np.ndarray, timeout: float = 10.0) -> None:
        await self._eng.init_ohlc5(ohlc5, timeout)

    async def step_next(self, timeout: float = 10.0) -> None:
        await self._eng.step_next(timeout)

    async def step_next_affect_statics(self, timeout: float = 10.0) -> tuple[np.ndarray, Statics]:
        events, vec = await self._eng.step_next_affect_statics(timeout)
        events_arr = np.asarray(events)
        vec_arr = np.asarray(vec)
        return events_arr, Statics.from_vec14(vec_arr)

    async def get_statics_raw(self, timeout: float = 10.0) -> np.ndarray:
        out = await self._eng.get_statics(timeout)
        return np.asarray(out)

    async def get_statics(self, timeout: float = 10.0) -> Statics:
        vec = await self.get_statics_raw(timeout=timeout)
        return Statics.from_vec14(vec)

    async def get_ticket_list(self, timeout: float = 10.0) -> np.ndarray:
        out = await self._eng.get_ticket_list(timeout)
        return np.asarray(out)

    async def affect(self, timeout: float = 10.0) -> np.ndarray:
        out = await self._eng.affect(timeout)
        return np.asarray(out)

    async def game_end(self, timeout: float = 10.0) -> np.ndarray:
        out = await self._eng.game_end(timeout)
        return np.asarray(out)

    async def close_step(self, flags, actions, ratios, *, timeout: float = 10.0) -> np.ndarray:
        out = await self._eng.close_step(flags, actions, ratios, timeout)
        return np.asarray(out)

    async def get_gate_policy_hint(self, timeout: float = 5.0) -> Optional[str]:
        return await self._eng.get_gate_policy_hint(timeout)

    async def place_token(
        self,
        *,
        side: str,
        order: str,
        price: float,
        units: int,
        sub_limit_pips: float | None = None,
        stop_order_pips: float | None = None,
        trail_pips: float | None = None,
        time_limits: float | None = None,
        timeout: float = 10.0,
    ) -> np.ndarray:
        out = await self._eng.place_token(
            side,
            order,
            float(price),
            int(units),
            sub_limit_pips,
            stop_order_pips,
            trail_pips,
            time_limits,
            timeout,
        )
        return np.asarray(out)

    async def place_ticket(
        self,
        *,
        side: str,
        units: int,
        sub_limit_pips: float | None = None,
        stop_order_pips: float | None = None,
        trail_pips: float | None = None,
        timeout: float = 10.0,
    ) -> np.ndarray:
        out = await self._eng.place_ticket(
            side,
            int(units),
            sub_limit_pips,
            stop_order_pips,
            trail_pips,
            timeout,
        )
        return np.asarray(out)

    async def wait_for_wasm_ready(
        self,
        timeout: float = 60.0,
        min_statics_len: int = 14,
        poll_interval: float = 0.5,
        verbose: bool = True,
    ) -> bool:
        """
        WASMエンジンの初期化完了を待つ。

        Args:
            timeout: タイムアウト秒数
            min_statics_len: 初期化完了とみなすstaticsの最小長
            poll_interval: ポーリング間隔秒数
            verbose: ログ出力するかどうか

        Returns:
            True: 初期化完了, False: タイムアウト
        """
        if verbose:
            print("[py] WASM初期化待機中...")

        start = time.time()
        attempt = 0
        while time.time() - start < timeout:
            attempt += 1
            try:
                statics = await self.get_statics_raw(timeout=2.0)
                if len(statics) >= min_statics_len:
                    if verbose:
                        print("[py] WASM初期化完了!")
                    return True
            except Exception as e:
                if verbose and attempt <= 3:
                    print(f"[py] WASM初期化待機中... (attempt {attempt}, error: {e})")
            await asyncio.sleep(poll_interval)

        if verbose:
            print("[py] WASM初期化タイムアウト")
        return False

    async def wait_for_disconnect(
        self,
        poll_interval: float = 0.5,
        verbose: bool = True,
    ) -> None:
        """
        ブラウザの切断を待つ。

        Args:
            poll_interval: ポーリング間隔秒数
            verbose: ログ出力するかどうか
        """
        if verbose:
            print("\n[py] 切断待機中...")

        while True:
            try:
                await self.get_statics_raw(timeout=1.0)
            except Exception:
                break
            await asyncio.sleep(poll_interval)

        if verbose:
            print("[py] 切断完了\n")


__all__ = ["RustEngineAsyncAdapter"]
