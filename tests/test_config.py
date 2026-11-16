import pytest
from pydantic import ValidationError

from triage.config import HelpdeskSettings

VALID = {
    "helpdesk_base_url": "https://helpdesk.test/functions/v1/helpdesk/",
    "helpdesk_api_key": "nrd_test_key",
    "candidate_email": "candidate@example.com",
}


def test_settings_load_from_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HELPDESK_BASE_URL", "https://helpdesk.test/x/")
    monkeypatch.setenv("HELPDESK_API_KEY", "nrd_test_key")
    monkeypatch.setenv("CANDIDATE_EMAIL", "candidate@example.com")
    settings = HelpdeskSettings(_env_file=None)
    assert settings.helpdesk_base_url == "https://helpdesk.test/x"
    assert settings.helpdesk_api_key.get_secret_value() == "nrd_test_key"
    assert settings.helpdesk_requests_per_second == 4.0


def test_the_key_never_appears_in_repr_or_str() -> None:
    settings = HelpdeskSettings.model_validate(VALID)
    assert "nrd_test_key" not in repr(settings)
    assert "nrd_test_key" not in str(settings)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("helpdesk_base_url", "http://helpdesk.test", "https"),
        ("helpdesk_api_key", "   ", "empty"),
        ("candidate_email", "not-an-email", "email address"),
        ("candidate_email", "me@localhost", "email address"),
        ("helpdesk_requests_per_second", 6.0, "less than or equal to 5"),
    ],
)
def test_invalid_settings_are_rejected(field: str, value: object, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        HelpdeskSettings.model_validate(VALID | {field: value})
