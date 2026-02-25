from __future__ import annotations

import asyncio
from typing import Optional


class RustWsServerRpc:
    """
    Rust実装のWSサーバをPythonのasyncインタフェースに合わせる薄いラッパ。

    EngineAPI が期待する send_run_and_wait(fn_id, payload, timeout) を提供する。
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8787, *, start_seq: int = 1) -> None:
        try:
            from py_engine_rust import RustWsServer as _Raw  # type: ignore
        except Exception as e:  # pragma: no cover - optional dependency
            raise RuntimeError(f"py_engine_rust is not available: {e}") from e
        self._raw = _Raw(host, port, start_seq)
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        await asyncio.to_thread(self._raw.start)

    async def wait_connected(self, timeout: Optional[float] = None) -> None:
        await asyncio.to_thread(self._raw.wait_connected, timeout)

    async def send_run_and_wait(self, fn_id: int, payload: bytes = b"", timeout: float = 10.0) -> bytes:
        if payload is None:
            payload = b""
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise TypeError("payload must be bytes-like")
        async with self._lock:
            out = await asyncio.to_thread(self._raw.send_run_and_wait, int(fn_id), bytes(payload), float(timeout))
            # PyO3 Vec<u8> は通常 bytes になるが、万一 list[int] で返った場合も補足
            if isinstance(out, list):
                out = bytes(out)
            if isinstance(out, bytearray):
                out = bytes(out)
            if not isinstance(out, (bytes, memoryview)):
                raise TypeError(f"send_run_and_wait returned non-bytes payload: {type(out)}")
            return bytes(out)

    async def stop(self) -> None:
        await asyncio.to_thread(self._raw.stop)


__all__ = ["RustWsServerRpc"]
