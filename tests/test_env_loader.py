import os

from impostor.env import load_env_file


def test_load_env_file_sets_missing_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        '\n'.join(
            [
                "# comment",
                'REDIS_URL="redis://localhost:6379/1"',
                "PLAIN_VALUE=value",
                "  SPACED_KEY = spaced value  ",
                "",
            ]
        )
    )
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("PLAIN_VALUE", raising=False)
    monkeypatch.delenv("SPACED_KEY", raising=False)

    load_env_file(env_file)

    assert os.environ["REDIS_URL"] == "redis://localhost:6379/1"
    assert os.environ["PLAIN_VALUE"] == "value"
    assert os.environ["SPACED_KEY"] == "spaced value"


def test_load_env_file_does_not_override_existing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OVERWRITE_ME=new\n")
    monkeypatch.setenv("OVERWRITE_ME", "existing")

    load_env_file(env_file)

    assert os.environ["OVERWRITE_ME"] == "existing"
