import pytest
from backend.chatbi.seed import validate_local_database_url


def test_seeder_allows_only_the_known_local_mock_database() -> None:
    path = validate_local_database_url("sqlite:///data/local/chatbi.sqlite")
    assert path.name == "chatbi.sqlite"
    assert path.parent.name == "local"


def test_seeder_rejects_cloud_and_other_local_databases() -> None:
    with pytest.raises(ValueError):
        validate_local_database_url("postgresql://example.invalid/mock")
    with pytest.raises(ValueError):
        validate_local_database_url("sqlite:///data/local/other.sqlite")
