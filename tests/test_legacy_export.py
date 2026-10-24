"""Legacy regression tests that depend on excluded v1 files.

These tests are NOT included in the exported starter kit.
They verify properties of the old v1 code that is retained in the source repo
for reference but not shipped to users.
"""
import ast
import csv
from pathlib import Path
from types import SimpleNamespace
from typing import List
from unittest.mock import AsyncMock

import pytest


async def test_legacy_export_uses_file_ids_and_never_requests_secret_urls(tmp_path):
    # Compile ONLY this pure export function, not the obsolete v1 runtime or its globals.
    # Only newly generated synthetic CSV is read; existing broadcast_logs are untouched.
    source = Path(__file__).resolve().parents[1] / "features/admin/broadcast.py"
    if not source.exists():
        pytest.skip("Legacy file features/admin/broadcast.py not found (not in exported kit)")
    tree = ast.parse(source.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "create_broadcast_text_file")
    namespace = {"Path": Path, "List": List, "Bot": object, "csv": csv,
                 "logger": SimpleNamespace(info=lambda *_: None),
                 "_get_broadcast_filename": lambda *_, **__: "synthetic.csv"}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
    token = "123456:" + "T" * 35
    bot = SimpleNamespace(token=token, get_file=AsyncMock(side_effect=AssertionError("No network")))
    output = await namespace["create_broadcast_text_file"](
        "synthetic", "TEST", ["photo_id"], ["video_id"], [], tmp_path, bot)
    text = output.read_text(encoding="utf-8-sig")
    assert "photo_id" in text and "video_id" in text
    assert token not in text and "api.telegram.org" not in text
    bot.get_file.assert_not_awaited()