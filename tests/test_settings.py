from pytest import MonkeyPatch

from scam2market.config.settings import Settings


def test_allowed_origins_accepts_compose_comma_separated_value(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173")

    settings = Settings()

    assert settings.allowed_origins == [
        "http://localhost:3000",
        "http://localhost:5173",
    ]
