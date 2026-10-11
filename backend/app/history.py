"""Daily score history.

The daily Explore job records every rated ticker's (balanced) score in one
file per month, app/data/history/YYYY-MM.json:
    {"dates": ["2026-10-12", ...], "scores": {"AAPL": [62, 63, ...], ...}}
where scores[ticker][i] belongs to dates[i] (null when it wasn't rated that day).
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Rating

DEFAULT_DIR = Path(__file__).parent / "data" / "history"
MONTHS_KEPT = 24


def record(ratings: list[Rating], date: str, directory: Path = DEFAULT_DIR) -> Path:
    """Add (or replace) the scores for `date` in that month's file."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{date[:7]}.json"
    data = json.loads(path.read_text()) if path.is_file() else {"dates": [], "scores": {}}
    dates: list[str] = data["dates"]
    scores: dict[str, list] = data["scores"]
    if date in dates:
        i = dates.index(date)
    else:
        dates.append(date)
        dates.sort()
        i = dates.index(date)
        for series in scores.values():
            series.insert(i, None)
    today = {r.ticker: int(r.score) for r in ratings if r.score is not None}
    for ticker in set(scores) | set(today):
        series = scores.setdefault(ticker, [None] * len(dates))
        series[i] = today.get(ticker)
    data["scores"] = {t: s for t, s in sorted(scores.items()) if any(v is not None for v in s)}
    path.write_text(json.dumps(data, separators=(",", ":")))
    for old in sorted(directory.glob("*.json"))[:-MONTHS_KEPT]:
        old.unlink()
    return path


class History:
    def __init__(self, directory: Path = DEFAULT_DIR):
        self.directory = directory
        self._months: dict[str, tuple[float, dict]] = {}

    def _month(self, path: Path) -> dict:
        # Re-read a month only when its file changed (the job updates it daily).
        mtime = path.stat().st_mtime
        cached = self._months.get(path.name)
        if not cached or cached[0] != mtime:
            cached = (mtime, json.loads(path.read_text()))
            self._months[path.name] = cached
        return cached[1]

    def get(self, ticker: str) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        if not self.directory.is_dir():
            return out
        for path in sorted(self.directory.glob("*.json")):
            data = self._month(path)
            series = data["scores"].get(ticker)
            if series:
                out.extend((d, s) for d, s in zip(data["dates"], series) if s is not None)
        return out
