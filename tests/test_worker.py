import shutil

import pytest

from worker.__main__ import ROLES, main
from worker.health import run_checks, tool_version

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg não instalado")


@needs_ffmpeg
def test_ffmpeg_and_ffprobe_versions():
    assert tool_version("ffmpeg").startswith("ffmpeg version")
    assert tool_version("ffprobe").startswith("ffprobe version")


def test_missing_tool_returns_none():
    assert tool_version("binario-que-nao-existe") is None


@needs_ffmpeg
def test_checks_without_database():
    assert run_checks(check_database=False)


def test_roles_are_not_faked_before_task_3():
    for role in ROLES:
        assert main(["worker", role]) == 2


def test_unknown_command_fails():
    assert main(["worker", "xyz"]) == 1
