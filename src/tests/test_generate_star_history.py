import json
from pathlib import Path

from scripts.generate_star_history import generate_svg


def test_generate_svg_from_paginated_github_response(tmp_path: Path):
    stargazers = tmp_path / "stargazers.json"
    repository = tmp_path / "repository.json"
    stargazers.write_text(
        json.dumps([[{"starred_at": "2026-05-04T08:23:05Z"}, {"starred_at": "2026-05-05T09:00:00Z"}]]),
        encoding="utf-8",
    )
    repository.write_text(
        json.dumps({
            "created_at": "2026-05-02T08:32:15Z",
            "full_name": "owner/repo",
            "stargazers_count": 2,
        }),
        encoding="utf-8",
    )

    svg = generate_svg(stargazers, repository)

    assert svg.startswith("<svg")
    assert "owner/repo" in svg
    assert "2 stars" in svg
    assert "2026-05-02" in svg
