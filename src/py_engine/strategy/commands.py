from __future__ import annotations

from typing import Awaitable, Callable

from py_engine.strategy.api import Context

# ユーザーが step 内で使える型（便利）
StepFn = Callable[[Context], Awaitable[None]]


async def hold(ctx: Context) -> None:
    """
    何もしない（return廃止版）。
    step 内で「何もしない」を明示したい場合に使える。
    例:
      await hold(ctx)
    """
    return None


def not_implemented(reason: str = "This operation is not implemented yet.") -> StepFn:
    """
    将来拡張用：呼ばれたら明示的に落とす（事故防止）。
    例:
      await not_implemented("buy is not supported")(ctx)
    """
    async def _fn(ctx: Context) -> None:
        raise NotImplementedError(reason)
    return _fn
