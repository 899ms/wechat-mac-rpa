#!/usr/bin/env python3
"""Generate a self-hosted SVG chart from GitHub stargazer timestamps."""

import argparse
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape


def _load_stars(path: Path) -> list[datetime]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    pages = payload if payload and isinstance(payload[0], list) else [payload]
    timestamps = []
    for item in (entry for page in pages for entry in page):
        starred_at = item.get("starred_at")
        if starred_at:
            timestamps.append(datetime.fromisoformat(starred_at.replace("Z", "+00:00")))
    return sorted(timestamps)


def _history(stars: list[datetime], created_at: datetime, total: int) -> list[tuple[date, int]]:
    daily = Counter(star.date() for star in stars)
    points = [(created_at.date(), 0)]
    running = 0
    for day in sorted(daily):
        running += daily[day]
        points.append((day, running))
    current = max(total, running)
    if current > running:
        points.append((datetime.now().astimezone().date(), current))
    return points


def generate_svg(stargazers_path: Path, repository_path: Path) -> str:
    repository = json.loads(repository_path.read_text(encoding="utf-8"))
    stars = _load_stars(stargazers_path)
    created_at = datetime.fromisoformat(repository["created_at"].replace("Z", "+00:00"))
    total = int(repository.get("stargazers_count", len(stars)))
    points = _history(stars, created_at, total)

    width, height = 900, 360
    left, right, top, bottom = 70, 30, 58, 54
    chart_width = width - left - right
    chart_height = height - top - bottom
    start_day, end_day = points[0][0], points[-1][0]
    day_span = max((end_day - start_day).days, 1)
    y_max = max(total, 1)

    def xy(point: tuple[date, int]) -> tuple[float, float]:
        day, count = point
        x = left + (day - start_day).days / day_span * chart_width
        y = top + chart_height - count / y_max * chart_height
        return x, y

    coordinates = [xy(point) for point in points]
    line = " ".join(
        ("M" if index == 0 else "L") + f" {x:.1f} {y:.1f}"
        for index, (x, y) in enumerate(coordinates)
    )
    area = (
        f"M {coordinates[0][0]:.1f} {top + chart_height:.1f} "
        + " ".join(f"L {x:.1f} {y:.1f}" for x, y in coordinates)
        + f" L {coordinates[-1][0]:.1f} {top + chart_height:.1f} Z"
    )
    grid = []
    for index in range(5):
        count = round(y_max * index / 4)
        y = top + chart_height - chart_height * index / 4
        grid.append(
            f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}"/>'
            f'<text class="axis" x="{left - 12}" y="{y + 4:.1f}" text-anchor="end">{count}</text>'
        )
    title = escape(repository.get("full_name", "Star History"))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Star history for {title}">
<style>
:root{{color-scheme:light dark}}.bg{{fill:#fff}}.title{{fill:#24292f;font:600 20px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}.sub,.axis{{fill:#57606a;font:12px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}.grid{{stroke:#d8dee4;stroke-width:1}}.area{{fill:#f5c542;opacity:.2}}.line{{fill:none;stroke:#d4a72c;stroke-width:3;stroke-linejoin:round;stroke-linecap:round}}.point{{fill:#bf8700}}
@media(prefers-color-scheme:dark){{.bg{{fill:#0d1117}}.title{{fill:#f0f6fc}}.sub,.axis{{fill:#8c959f}}.grid{{stroke:#30363d}}.area{{fill:#d29922;opacity:.18}}.line{{stroke:#e3b341}}.point{{fill:#f2cc60}}}}
</style>
<rect class="bg" width="100%" height="100%" rx="10"/>
<text class="title" x="{left}" y="30">⭐ {title}</text>
<text class="sub" x="{width - right}" y="30" text-anchor="end">{total} stars</text>
{''.join(grid)}
<path class="area" d="{area}"/><path class="line" d="{line}"/>
<circle class="point" cx="{coordinates[-1][0]:.1f}" cy="{coordinates[-1][1]:.1f}" r="4"/>
<text class="axis" x="{left}" y="{height - 20}">{start_day.isoformat()}</text>
<text class="axis" x="{width - right}" y="{height - 20}" text-anchor="end">{end_day.isoformat()}</text>
</svg>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a self-hosted star history SVG")
    parser.add_argument("--stargazers", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        generate_svg(args.stargazers, args.repository),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
