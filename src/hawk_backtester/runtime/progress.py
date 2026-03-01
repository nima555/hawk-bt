from __future__ import annotations

import shutil
import time
from typing import Optional, Callable


def create_progress_printer() -> Callable[[int, Optional[int]], None]:
    """Create a terminal progress bar callback.

    Returns a callable ``(done, total) -> None`` that draws an animated
    progress bar to stdout.  Does nothing when *total* is ``None`` or <= 0.
    """
    spinner = ["\u28cb", "\u28d9", "\u28f9", "\u28f8", "\u28fc", "\u28f4", "\u28e6", "\u28e7", "\u28c7", "\u28cf"]
    color_filled = "\033[38;5;39m"   # cyan
    color_border = "\033[38;5;244m"  # gray
    color_reset = "\033[0m"
    start = time.perf_counter()
    state = {"index": 0}

    def _human_time(seconds: float) -> str:
        if seconds <= 0 or not seconds == seconds:
            return "--s"
        mins, secs = divmod(int(seconds), 60)
        if mins:
            return f"{mins}m{secs:02d}s"
        return f"{secs}s"

    def _printer(done: int, total: Optional[int]) -> None:
        if not total or total <= 0:
            return
        ratio = min(max(done / total, 0.0), 1.0)
        cols = shutil.get_terminal_size((80, 20)).columns
        bar_len = max(10, cols - 40)
        filled = int(bar_len * ratio)
        filled_segment = "\u2501" * filled
        empty_segment = "\u2501" * (bar_len - filled)
        bar = (
            f"{color_filled}{filled_segment}{color_reset}"
            f"{color_border}{empty_segment}{color_reset}"
        )
        pct = ratio * 100.0
        elapsed = time.perf_counter() - start
        eta = (elapsed / ratio - elapsed) if ratio > 0 else float("inf")
        spinner_char = spinner[state["index"] % len(spinner)]
        state["index"] += 1
        line = (
            f"\r{spinner_char} {color_border}[{color_reset}{bar}{color_border}]{color_reset} {pct:6.2f}% "
            f"{done:>7}/{total:<7} eta {_human_time(eta)}"
        )
        print(line, end="", flush=True)
        if done >= total:
            print()

    return _printer
