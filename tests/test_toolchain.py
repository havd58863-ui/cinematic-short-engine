from engine.toolchain import SECRET_ENV_NAMES, _module_present, diagnose, validate_toolchain_manifest


def test_module_present_never_raises_on_missing_dotted_parent() -> None:
    assert _module_present("definitely_missing_parent.child") is False
    assert _module_present("json") is True


def test_toolchain_manifest_is_consistent() -> None:
    result = validate_toolchain_manifest()
    assert result["ok"] is True
    assert "openmontage" in result["tool_ids"]
    assert "reactor_sdk" in result["tool_ids"]
    assert "ollama" in result["tool_ids"]


def test_doctor_never_exposes_secret_values(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-be-printed")
    result = diagnose()
    assert result["secrets_present"]["GEMINI_API_KEY"] is True
    assert set(result["secrets_present"]) == set(SECRET_ENV_NAMES)
    assert "must-not-be-printed" not in repr(result)
