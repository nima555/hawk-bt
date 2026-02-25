from __future__ import annotations

from dataclasses import dataclass
import asyncio
from typing import Optional

from py_engine.protocol.wire import (
    MSG_RESULT,
    MSG_ERROR,
    MSG_PING,
    MSG_PONG,
    MSG_PUSH,
    FN_ANALYSIS_RESULT,
    unpack_message,
    pack_run,
    pack_message,
    decode_error_payload,
    PROTOCOL_VERSION,
)

@dataclass(frozen=True)
class RpcError(Exception):
    seq: int
    fn_id: int
    err_code: int
    sub_code: int
    message: str

    def __str__(self) -> str:
        base = f"RpcError(seq={self.seq}, fnId={self.fn_id}, err={self.err_code}, sub={self.sub_code})"
        return f"{base}: {self.message}" if self.message else base


@dataclass(frozen=True)
class RpcTransportError(Exception):
    message: str
    seq: Optional[int] = None
    fn_id: Optional[int] = None

    def __str__(self) -> str:
        base = "RpcTransportError"
        if self.seq is not None or self.fn_id is not None:
            base += f"(seq={self.seq}, fnId={self.fn_id})"
        return f"{base}: {self.message}"


class RpcClient:
    """
    Browser側 wasm_rpc_bridge.js が lock-step seq を強制する前提:
      - seq は 1,2,3... の単調増加で送る
      - in-flight は最大1（並列RUN禁止）
    """

    def __init__(self, websocket, *, start_seq: int = 1) -> None:
        self._ws = websocket
        self._seq = int(start_seq)
        self._lock = asyncio.Lock()
        self._push_queue: asyncio.Queue = asyncio.Queue()

    @property
    def next_seq(self) -> int:
        return self._seq

    async def _recv_until_result_or_error(self, expected_seq: int, expected_fn_id: int, timeout: float) -> bytes:
        """
        RESULT/ERROR が来るまで待つ。
        PING が来たら PONG 返して継続。
        その他 msgType は無視（将来拡張耐性）。
        """
        while True:
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
            except asyncio.TimeoutError as e:
                raise TimeoutError(f"timeout waiting response (seq={expected_seq}, fnId={expected_fn_id})") from e
            except Exception as e:
                raise RpcTransportError("websocket recv failed", expected_seq, expected_fn_id) from e

            if not isinstance(raw, (bytes, bytearray, memoryview)):
                raise RpcTransportError(f"expected binary frame, got {type(raw)}", expected_seq, expected_fn_id)

            msg = unpack_message(bytes(raw))

            if msg.version != PROTOCOL_VERSION:
                raise RpcTransportError(
                    f"protocol version mismatch: got {msg.version}, expected {PROTOCOL_VERSION}",
                    expected_seq,
                    expected_fn_id,
                )

            # PING handling
            if msg.msg_type == MSG_PING:
                try:
                    pong = pack_message(MSG_PONG, msg.seq, msg.fn_id, msg.payload)
                    await self._ws.send(pong)
                except Exception:
                    pass
                continue

            # PUSH handling (Browser → Agent, e.g. analysis results)
            if msg.msg_type == MSG_PUSH:
                await self._push_queue.put(msg)
                continue

            # seq/fnId は RESULT/ERROR で厳密チェック
            if msg.msg_type in (MSG_RESULT, MSG_ERROR):
                if msg.seq != expected_seq:
                    raise RpcTransportError(f"seq mismatch: expected {expected_seq}, got {msg.seq}", expected_seq, expected_fn_id)
                if msg.fn_id != (expected_fn_id & 0xFFFF):
                    raise RpcTransportError(f"fnId mismatch: expected {expected_fn_id}, got {msg.fn_id}", expected_seq, expected_fn_id)

                if msg.msg_type == MSG_RESULT:
                    return msg.payload

                err_code, sub_code, message = decode_error_payload(msg.payload)
                raise RpcError(
                    seq=expected_seq,
                    fn_id=expected_fn_id,
                    err_code=err_code,
                    sub_code=sub_code,
                    message=message,
                )

            # その他 msgType は無視して待ち続ける
            continue

    async def send_run_and_wait(self, fn_id: int, payload: bytes = b"", timeout: float = 10.0) -> bytes:
        async with self._lock:
            seq = self._seq
            self._seq += 1  # 送ったら消費（ズレを回避）

            frame = pack_run(seq, fn_id, payload)

            try:
                await self._ws.send(frame)
            except Exception as e:
                raise RpcTransportError("websocket send failed", seq, fn_id) from e

            return await self._recv_until_result_or_error(seq, fn_id, timeout)

    async def wait_for_push(self, timeout: float = 300.0) -> "Message":
        """
        Browser からの PUSH メッセージを待つ。
        Agent Mode で SIM_DONE 後の分析結果 (FN_ANALYSIS_RESULT) を受信する用途。
        """
        try:
            return await asyncio.wait_for(self._push_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"timeout waiting for push message ({timeout}s)")

    async def wait_for_analysis_result(self, timeout: float = 300.0) -> bytes:
        """
        FN_ANALYSIS_RESULT の PUSH を待ち、payload を返す。
        payload は JSON (UTF-8) を想定。
        """
        while True:
            msg = await self.wait_for_push(timeout=timeout)
            if msg.fn_id == FN_ANALYSIS_RESULT:
                return msg.payload
            # 他の push は無視して待ち続ける
