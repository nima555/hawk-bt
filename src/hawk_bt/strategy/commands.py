from __future__ import annotations

from typing import Awaitable, Callable

from hawk_bt.strategy.api import Context

# Convenience type for step functions
StepFn = Callable[[Context], Awaitable[None]]


async def hold(ctx: Context) -> None:
    """Do nothing for this step.

    Use when you want to explicitly skip a bar::

        await hold(ctx)
    """
    return None


def not_implemented(reason: str = "This operation is not implemented yet.") -> StepFn:
    """Return a step function that raises NotImplementedError.

    Useful as a placeholder during development::

        await not_implemented("buy logic pending")(ctx)
    """
    async def _fn(ctx: Context) -> None:
        raise NotImplementedError(reason)
    return _fn
