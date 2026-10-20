from engine.config import list_accounts, load_account, validate_configuration


def test_both_accounts_are_present_and_distinct() -> None:
    assert list_accounts() == [
        "account_01_psychology",
        "account_02_storytelling",
    ]
    first = load_account("account_01_psychology")
    second = load_account("account_02_storytelling")
    assert first["name"] != second["name"]
    assert second["visual"]["ai_first"] is True
    assert first["language"]["voice"] == "en"
    assert second["language"]["voice"] == "en"


def test_configuration_validation_passes() -> None:
    result = validate_configuration()
    assert result["ok"] is True
    assert result["technical_master"] == {"resolution": [1080, 1920], "fps": 30}
