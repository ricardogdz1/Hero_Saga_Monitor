import pytest

from gdz_monitor.core import database


@pytest.fixture(autouse=True)
def _isolated_database(tmp_path, monkeypatch):
    """Cada teste usa um banco temporário — nunca o do utilizador — e sem ficheiros antigos a migrar."""
    database.close()
    monkeypatch.setattr(database, "DB_FILE", str(tmp_path / "gdz_monitor.db"))
    monkeypatch.setattr(database, "LEGACY_DOCUMENT_FILES", ())
    monkeypatch.setattr(database, "LEGACY_IMAGE_DIRS", ())
    yield
    database.close()
