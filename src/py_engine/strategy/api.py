from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Protocol, runtime_checkable

import numpy as np

from py_engine.runtime.engine_api import Statics


@runtime_checkable
class Engine(Protocol):
    """
    Strategy が利用する Engine インタフェース（BoundEngine想定）。
    ctx.state.statics を常に最新に保つ実装であること（契約）。
    """

    async def get_statics(self, timeout: float = 10.0) -> Statics: ...
    async def step_next(self, timeout: float = 10.0) -> None: ...
    async def get_ticket_list(self, timeout: float = 10.0) -> np.ndarray: ...

    # backtestで使う（attachedでは使わない）
    async def init_ohlc5(self, ohlc5: np.ndarray, timeout: float = 10.0) -> None: ...

    async def refresh(self, timeout: float = 10.0) -> Statics: ...
    async def affect(self, timeout: float = 10.0) -> np.ndarray: ...
    async def game_end(self, timeout: float = 10.0) -> np.ndarray: ...

@dataclass
class EngineState:
    """
    逐次ループで更新され続ける「唯一の状態」。
    ユーザーは基本的に ctx.state.statics を参照すればよい。
    """
    statics: Statics
    # 将来拡張用（必要なら使う）
    tickets: Any | None = None
    affect_events: np.ndarray | None = None
    done: bool = False
    done_code: int | None = None


@dataclass
class Context:
    """
    Strategy に渡すコンテキスト。
    - engine: 操作対象（BoundEngine等）
    - state : 逐次ループが毎ステップ更新する最新状態（唯一の真実）
    - user  : ユーザーが自由に使える永続辞書（学習・ログ・状態保持など）
    """
    engine: Engine
    state: EngineState
    user: Dict[str, Any] = field(default_factory=dict)


class Strategy(ABC):
    """
    ユーザーが実装する戦略。

    重要:
    - return はしない（step 内で必要な read/write を好きな回数呼ぶ）
    - 状態参照は ctx.state.statics を唯一の真実とする
    """

    @abstractmethod
    async def step(self, ctx: Context) -> None:
        raise NotImplementedError
