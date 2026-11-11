from musicbuddy import drive, ingest


class FakeResp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class FakeSession:
    TREE = {
        "root": [
            {"id": "f1", "name": "20261110", "mimeType": drive.FOLDER_MIME, "modifiedTime": "2026-11-10T19:45:00Z"},
            {"id": "f2", "name": "notes", "mimeType": drive.FOLDER_MIME, "modifiedTime": "2026-11-10T19:45:00Z"},
            {"id": "x", "name": "stray.m4a", "mimeType": "audio/mp4", "size": "5", "modifiedTime": "2026-11-10T19:45:00Z"},
        ],
        "f1": [
            {"id": "a", "name": "20261110-violin-coleman.m4a", "mimeType": "audio/mp4", "size": "64464099",
             "modifiedTime": "2026-11-11T03:45:00.123Z"},
            {"id": "d", "name": "Doc", "mimeType": "application/vnd.google-apps.document",
             "modifiedTime": "2026-11-11T03:45:00Z"},
        ],
    }

    def get(self, url, params=None, **_):
        parent = params["q"].split("'")[1]
        return FakeResp({"files": self.TREE.get(parent, [])})


def test_scan_syncs_only_dated_folders_with_real_files(monkeypatch):
    calls = []
    monkeypatch.setattr(drive, "_session", lambda: FakeSession())
    monkeypatch.setattr(drive.config, "DRIVE_FOLDER_ID", "root")
    monkeypatch.setattr(ingest, "sync_lesson", lambda did, entries, source: calls.append((did, entries, source)) or True)
    assert drive.scan() == ["20261110"]
    did, entries, source = calls[0]
    assert did == "20261110" and source == "gdrive:20261110"
    assert [(e.name, e.size) for e in entries] == [("20261110-violin-coleman.m4a", 64464099)]
    assert entries[0].mtime == drive._mtime("2026-11-11T03:45:00.123Z") > 0
