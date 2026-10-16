from pathlib import Path

from editing.kinocut_adapter import run_kinocut_qc
from tools.push_to_github import collect_project_files


def test_kinocut_qc_is_optional_when_cli_missing(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test-video-placeholder")
    monkeypatch.setattr("editing.kinocut_adapter.shutil.which", lambda name: None)
    result = run_kinocut_qc(video)
    assert result["status"] == "not_installed"
    assert result["reason"] == "kino_executable_not_found"


def test_github_uploader_collects_text_files_and_omits_secrets_and_media(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("project", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=secret", encoding="utf-8")
    (tmp_path / "secrets.json").write_text("{}", encoding="utf-8")
    (tmp_path / "demo.mp4").write_bytes(b"media")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "junk.pyc").write_bytes(b"bad")
    files = dict((name, raw) for name, raw in collect_project_files(tmp_path))
    assert "pyproject.toml" in files
    assert "README.md" in files
    assert ".env" not in files
    assert "secrets.json" not in files
    assert "demo.mp4" not in files
    assert "__pycache__/junk.pyc" not in files
