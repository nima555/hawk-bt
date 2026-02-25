from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass
from typing import Optional, AsyncIterator, Sequence
from urllib.parse import urlparse, parse_qs

import websockets
from websockets.protocol import State
from websockets.server import WebSocketServerProtocol

# バージョン情報（pyproject.tomlと同期させること）
__version__ = "0.1.0"


@dataclass
class ConnectionState:
    ws: Optional[WebSocketServerProtocol] = None
    connected_event: asyncio.Event = asyncio.Event()


class WsServer:
    """
    Browser(UI/Worker) が接続してくるローカルWSサーバ。

    - bindは127.0.0.1固定を推奨（セキュリティ最低ライン）
    - 接続は1本を前提（lock-step seq / in-flight 1 と相性良い）
    """

    # デフォルトで許可する Origin（localhost系）
    DEFAULT_ALLOWED_ORIGINS = (
        "http://127.0.0.1",
        "http://localhost",
        "https://127.0.0.1",
        "https://localhost",
        "https://www2.kisshi-lab.com",
    )

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8787,
        *,
        metadata: Optional[dict] = None,
        allowed_origins: Optional[Sequence[str]] = None,
        token: Optional[str] = None,
    ) -> None:
        self._host = host
        self._port = port
        self._server: Optional[websockets.server.Serve] = None
        self._state = ConnectionState()
        self._lock = asyncio.Lock()
        self._metadata: dict = metadata or {}
        self._allowed_origins: tuple[str, ...] = tuple(allowed_origins) if allowed_origins else self.DEFAULT_ALLOWED_ORIGINS
        self._token: Optional[str] = token

    @staticmethod
    def generate_token(nbytes: int = 16) -> str:
        """ランダムなワンタイムトークンを生成する。"""
        return secrets.token_urlsafe(nbytes)

    def _is_ws_open(self, ws: Optional[WebSocketServerProtocol]) -> bool:
        """
        websockets 15.x では WebSocketServerProtocol.closed が無いので state で判定する。
        前方互換として closed(bool) があればそれも見る。
        """
        if ws is None:
            return False
        state = getattr(ws, "state", None)
        if state is not None:
            return state not in (State.CLOSING, State.CLOSED)
        closed = getattr(ws, "closed", None)
        if isinstance(closed, bool):
            return not closed
        return True

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    def get_ws(self) -> WebSocketServerProtocol:
        ws = self._state.ws
        if ws is None:
            raise RuntimeError("No browser websocket connected yet")
        return ws

    async def wait_connected(self, timeout: Optional[float] = None) -> WebSocketServerProtocol:
        """
        ブラウザが接続してくるのを待つ。
        """
        try:
            if timeout is None:
                await self._state.connected_event.wait()
            else:
                await asyncio.wait_for(self._state.connected_event.wait(), timeout=timeout)
        except asyncio.TimeoutError as e:
            raise TimeoutError("Timed out waiting for browser connection") from e

        return self.get_ws()

    async def start(self) -> None:
        """
        サーバ起動（非ブロッキング）
        """
        if self._server is not None:
            return

        async def handler(ws: WebSocketServerProtocol):
            # ── Origin 検証 ──
            origin = (ws.request.headers.get("Origin") or "").rstrip("/")
            if not any(origin.startswith(ao) for ao in self._allowed_origins):
                await ws.close(code=1008, reason="Origin not allowed")
                return

            # ── トークン検証（設定されている場合のみ） ──
            if self._token:
                params = parse_qs(urlparse(ws.request.path).query)
                client_token = params.get("token", [None])[0]
                if client_token != self._token:
                    await ws.close(code=1008, reason="Invalid token")
                    return

            # 1本運用を前提：2本目以降は拒否（または上書き）
            async with self._lock:
                if self._is_ws_open(self._state.ws):
                    await ws.close(code=1008, reason="Only one connection is allowed")
                    return

                self._state.ws = ws
                # Eventは再利用されるので、すでにsetならクリア→set
                if self._state.connected_event.is_set():
                    self._state.connected_event.clear()
                self._state.connected_event.set()

                # バージョン情報をhandshakeとして送信
                handshake = {
                    "type": "handshake",
                    "python_library_version": __version__,
                    **self._metadata,
                }
                await ws.send(json.dumps(handshake))

            # 接続維持：クライアントが切断するまで待つ
            try:
                await ws.wait_closed()
            finally:
                # 切断時クリーンアップ
                async with self._lock:
                    if self._state.ws is ws:
                        self._state.ws = None
                        # 次の接続待ちに備えて event を作り直すのが安全
                        self._state.connected_event = asyncio.Event()

        self._server = await websockets.serve(
            handler,
            self._host,
            self._port,
            max_size=8 * 1024 * 1024,  # payload上限（必要なら調整）
        )

        if self._token:
            print(f"[ws] Token auth enabled. Append ?token={self._token} to the WS URL.")

    async def stop(self) -> None:
        """
        サーバ停止
        """
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

        # 接続が残っていたら閉じる
        if self._is_ws_open(self._state.ws):
            await self._state.ws.close()
        self._state.ws = None
        self._state.connected_event = asyncio.Event()
