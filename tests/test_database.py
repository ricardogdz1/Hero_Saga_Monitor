import json
import sqlite3

import pytest

from gdz_monitor.core import database, resources, settings, storage
from gdz_monitor.services import mvp_timer


class TestDocuments:
    def test_documento_ausente_devolve_default(self):
        assert database.get_document("nada", {"x": 1}) == {"x": 1}
        assert not database.has_document("nada")

    def test_grava_e_le_documento(self):
        database.set_document("k", {"a": [1, 2], "txt": "ação"})
        assert database.get_document("k") == {"a": [1, 2], "txt": "ação"}
        database.set_document("k", [3])
        assert database.get_document("k") == [3]

    def test_storage_monitorados_round_trip_deduplica(self):
        storage.save_data({"monitored": [{"id": 1}, {"id": "1"}, {"id": 2, "category": "Cartas"}]})
        data = storage.load_data()
        assert [m["id"] for m in data["monitored"]] == [1, 2]
        assert data["monitored"][1]["category"] == "Cartas"
        assert "Gerais" in data["monitor_categories"]

    def test_storage_sem_dados_tem_estrutura_padrao(self):
        data = storage.load_data()
        assert data["monitored"] == [] and data["searches"] == []
        assert storage.load_alerts() == {}
        assert storage.load_prices_history() == {}

    def test_settings_mescla_defaults(self):
        settings.save_settings({"smtp_port": "25", "ui_theme": "LIGHT"})
        out = settings.load_settings()
        assert out["smtp_port"] == 25
        assert out["ui_theme"] == "light"
        assert out["alert_interval_seconds"] == 300


class TestImages:
    def test_grava_le_e_lista(self):
        database.put_image("item_icon", "501", b"png-a")
        database.put_image("item_icon", "502", b"png-b")
        database.put_image("mob", "1038", b"png-c")
        assert database.get_image("item_icon", "501") == b"png-a"
        assert database.has_image("mob", "1038")
        assert not database.has_image("mob", "501")
        assert database.list_image_keys("item_icon") == ["501", "502"]

    def test_bytes_vazios_nao_gravam(self):
        database.put_image("mob", "1", b"")
        assert database.get_image("mob", "1") is None


class TestMigracao:
    def _setup_legacy(self, tmp_path, monkeypatch):
        alerts = tmp_path / "herosaga_alerts.json"
        alerts.write_text(json.dumps({"501": {"max": 10}}), encoding="utf-8")
        broken = tmp_path / "herosaga_builds.json"
        broken.write_text("{nao é json", encoding="utf-8")
        icons = tmp_path / "item_icons"
        icons.mkdir()
        (icons / "501.png").write_bytes(b"icon501")
        (icons / "leia-me.txt").write_bytes(b"ignorar")
        mobs = tmp_path / "mobs"
        mobs.mkdir()
        (mobs / "1038").write_bytes(b"mob1038")
        monkeypatch.setattr(database, "LEGACY_DOCUMENT_FILES", (
            (database.DOC_ALERTS, str(alerts)),
            (database.DOC_BUILDS, str(broken)),
            (database.DOC_SETTINGS, str(tmp_path / "nao_existe.json")),
        ))
        monkeypatch.setattr(database, "LEGACY_IMAGE_DIRS", (
            (database.IMG_ITEM_ICON, str(icons)),
            (database.IMG_MOB, str(mobs)),
        ))
        database.close()
        return alerts

    def test_importa_ficheiros_antigos_e_mantem_originais(self, tmp_path, monkeypatch):
        alerts = self._setup_legacy(tmp_path, monkeypatch)
        assert storage.load_alerts() == {"501": {"max": 10}}
        assert not database.has_document(database.DOC_BUILDS)
        assert database.get_image(database.IMG_ITEM_ICON, "501") == b"icon501"
        assert database.get_image(database.IMG_MOB, "1038") == b"mob1038"
        assert database.list_image_keys(database.IMG_ITEM_ICON) == ["501"]
        assert alerts.exists()

    def test_migracao_corre_uma_vez(self, tmp_path, monkeypatch):
        alerts = self._setup_legacy(tmp_path, monkeypatch)
        storage.save_alerts({"novo": {}})
        alerts.write_text(json.dumps({"velho": {}}), encoding="utf-8")
        database.close()
        assert storage.load_alerts() == {"novo": {}}


class TestResources:
    def test_le_de_ficheiros_sem_banco(self, tmp_path, monkeypatch):
        (tmp_path / "sub").mkdir()
        (tmp_path / "a.json").write_text('{"ok": true}', encoding="utf-8")
        (tmp_path / "sub" / "x.png").write_bytes(b"x")
        self._use(monkeypatch, tmp_path, db=False)
        assert resources.read_json("a.json") == {"ok": True}
        assert resources.read_bytes("sub/x.png") == b"x"
        assert resources.exists("sub/x.png") and not resources.exists("sub/y.png")
        assert resources.list_dir("sub") == ["x.png"]

    def test_le_do_banco_empacotado(self, tmp_path, monkeypatch):
        src = tmp_path / "src"
        (src / "sub" / "deep").mkdir(parents=True)
        (src / "item_icons").mkdir()
        (src / "a.json").write_text('{"ok": 1}', encoding="utf-8")
        (src / "sub" / "x.png").write_bytes(b"x")
        (src / "sub" / "deep" / "z.png").write_bytes(b"z")
        (src / "item_icons" / "1.png").write_bytes(b"cache")
        out = tmp_path / "dist" / "data"
        assert resources.build_resources_db(str(out / "resources.db"), data_dir=str(src)) == 3
        self._use(monkeypatch, out, db=True)
        assert resources.read_json("a.json") == {"ok": 1}
        assert resources.read_bytes("sub\\x.png") == b"x"
        assert resources.list_dir("sub") == ["x.png"]
        assert not resources.exists("item_icons/1.png")
        assert resources.read_json("falta.json", {}) == {}

    def test_banco_empacotado_e_somente_leitura(self, tmp_path, monkeypatch):
        out = tmp_path / "data"
        out.mkdir()
        (tmp_path / "src").mkdir()
        resources.build_resources_db(str(out / "resources.db"), data_dir=str(tmp_path / "src"))
        self._use(monkeypatch, out, db=True)
        conn = resources._get_conn()
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO resources (path, data) VALUES ('a', x'00')")

    @staticmethod
    def _use(monkeypatch, data_dir, *, db):
        monkeypatch.setattr(resources, "DATA_DIR", str(data_dir))
        monkeypatch.setattr(resources, "RESOURCES_DB_FILE", str(data_dir / "resources.db") if db else str(data_dir / "nao_existe.db"))
        monkeypatch.setattr(resources, "_conn", None)
        monkeypatch.setattr(resources, "_conn_checked", False)


class TestCatalogoMvp:
    def test_versao_actualizada_no_banco_tem_prioridade(self, tmp_path, monkeypatch):
        bundled = {"mvp": [{"id": 1038, "name": "Osiris"}], "name_display_locale": "en"}
        monkeypatch.setattr(mvp_timer.resources, "read_json", lambda rel, default=None: bundled if rel == "mvp_catalog_cache.json" else default)
        monkeypatch.setattr(mvp_timer, "MVP_CATALOG_CACHE_FILE_LEGACY", str(tmp_path / "nao_existe.json"))

        assert [x["name"] for x in mvp_timer.load_mvp_catalog_cache()] == ["Osiris"]
        assert mvp_timer.mvp_catalog_names_are_english_marked()

        mvp_timer.save_mvp_catalog_cache([{"id": 1039, "name": "Baphomet", "respawn_seconds": 7200}])
        items = mvp_timer.load_mvp_catalog_cache()
        assert items == [{"id": 1039, "name": "Baphomet", "respawn_seconds": 7200}]
        # locale herdado do catálogo anterior quando não indicado
        assert mvp_timer.mvp_catalog_names_are_english_marked()

    def test_path_explicito_usa_ficheiro(self, tmp_path):
        fp = tmp_path / "cat.json"
        mvp_timer.save_mvp_catalog_cache([{"id": 1, "name": "A"}], path=str(fp), name_display_locale="pending")
        assert json.loads(fp.read_text(encoding="utf-8"))["mvp"] == [{"id": 1, "name": "A"}]
        assert mvp_timer.load_mvp_catalog_cache(max_age_seconds=None, path=str(fp)) == [{"id": 1, "name": "A"}]
        assert not database.has_document(database.DOC_MVP_CATALOG)

    def test_timers_round_trip(self):
        assert mvp_timer.load_mvp_storage() == {"version": 1, "entries": []}
        mvp_timer.save_mvp_storage({"entries": [{"id": "x"}]})
        assert mvp_timer.load_mvp_storage()["entries"] == [{"id": "x"}]
