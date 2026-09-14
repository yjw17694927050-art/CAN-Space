"""GitHub URLs, scoped scans, and cache files preserve remote identity."""
from pathlib import Path
import hashlib

from core import github_fetcher


class Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.response = self

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            error = github_fetcher.requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error

    @property
    def headers(self):
        return {}

    def iter_content(self, chunk_size=64 * 1024):
        yield self._payload


def test_parse_tree_url_preserves_kind_branch_and_directory():
    info = github_fetcher.parse_github_url(
        "https://github.com/acme/vehicle/tree/develop/logs/can"
    )
    assert info["kind"] == "tree"
    assert info["branch"] == "develop"
    assert info["path"] == "logs/can"


def test_parse_blob_url_preserves_exact_file_scope():
    info = github_fetcher.parse_github_url(
        "https://github.com/acme/vehicle/blob/release/dbc/vehicle.dbc"
    )
    assert info["kind"] == "blob"
    assert info["branch"] == "release"
    assert info["path"] == "dbc/vehicle.dbc"


def test_encoded_path_is_decoded_once_then_safely_reencoded():
    info = github_fetcher.parse_github_url(
        "https://github.com/acme/vehicle/blob/main/logs/a%20file.csv"
    )
    assert info["path"] == "logs/a file.csv"
    assert "%2520" not in info["api_tree"]


def test_explicit_branch_and_directory_control_tree_request(monkeypatch):
    info = github_fetcher.parse_github_url(
        "https://github.com/acme/vehicle/tree/develop/logs/can"
    )
    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        if url == info["api_base"]:
            return Response({"default_branch": "main"})
        if "/git/trees/" in url:
            return Response({"tree": [
                {"type": "blob", "path": "logs/can/a.csv", "size": 10, "sha": "a" * 40},
                {"type": "blob", "path": "logs/other/b.csv", "size": 20, "sha": "b" * 40},
            ]})
        return Response({}, status_code=404)

    monkeypatch.setattr(github_fetcher.requests, "get", fake_get)
    completed = []
    worker = github_fetcher.RepoScanWorker(info)
    worker.done.connect(completed.append)
    worker.run()

    assert any("/git/trees/develop?recursive=1" in url for url in requested)
    assert [entry["path"] for entry in completed[0]["logs"]] == ["logs/can/a.csv"]


def test_blob_scope_returns_only_requested_file(monkeypatch):
    info = github_fetcher.parse_github_url(
        "https://github.com/acme/vehicle/blob/release/dbc/vehicle.dbc"
    )

    def fake_get(url, **kwargs):
        if url == info["api_base"]:
            return Response({"default_branch": "main"})
        if "/git/trees/" in url:
            return Response({"tree": [
                {"type": "blob", "path": "dbc/vehicle.dbc", "size": 10, "sha": "a" * 40},
                {"type": "blob", "path": "other/vehicle.dbc", "size": 10, "sha": "b" * 40},
            ]})
        return Response({}, status_code=404)

    monkeypatch.setattr(github_fetcher.requests, "get", fake_get)
    completed = []
    worker = github_fetcher.RepoScanWorker(info)
    worker.done.connect(completed.append)
    worker.run()

    assert [entry["path"] for entry in completed[0]["dbcs"]] == ["dbc/vehicle.dbc"]


def test_root_url_uses_repository_default_branch(monkeypatch):
    info = github_fetcher.parse_github_url("https://github.com/acme/vehicle")
    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        if url == info["api_base"]:
            return Response({"default_branch": "trunk"})
        if "/git/trees/" in url:
            return Response({"tree": []})
        return Response({}, status_code=404)

    monkeypatch.setattr(github_fetcher.requests, "get", fake_get)
    worker = github_fetcher.RepoScanWorker(info)
    worker.run()
    assert any("/git/trees/trunk?recursive=1" in url for url in requested)


def test_url_components_are_encoded_when_building_api_and_download_urls(monkeypatch):
    info = github_fetcher._build_result(
        "ac me", "vehicle#one", "release candidate", "logs/a file.csv", "blob"
    )
    assert "ac%20me/vehicle%23one" in info["api_base"]
    assert "release%20candidate" in info["api_tree"]

    def fake_get(url, **kwargs):
        if url == info["api_base"]:
            return Response({"default_branch": "main"})
        if "/git/trees/" in url:
            return Response({"tree": [{
                "type": "blob", "path": "logs/a file.csv", "size": 1,
                "sha": "a" * 40,
            }]})
        return Response({}, status_code=404)

    monkeypatch.setattr(github_fetcher.requests, "get", fake_get)
    completed = []
    worker = github_fetcher.RepoScanWorker(info)
    worker.done.connect(completed.append)
    worker.run()
    assert "%20" in completed[0]["logs"][0]["download_url"]
    assert "%23" in completed[0]["logs"][0]["download_url"]


def test_missing_explicit_branch_reports_specific_error(monkeypatch):
    info = github_fetcher.parse_github_url(
        "https://github.com/acme/vehicle/tree/missing/logs"
    )

    def fake_get(url, **kwargs):
        if url == info["api_base"]:
            return Response({"default_branch": "main"})
        return Response({}, status_code=404)

    monkeypatch.setattr(github_fetcher.requests, "get", fake_get)
    errors = []
    worker = github_fetcher.RepoScanWorker(info)
    worker.error.connect(errors.append)
    worker.run()
    assert errors == ["Branch or path not found — check the GitHub URL."]


def _remote_file(**overrides):
    blob_sha = hashlib.sha1(b"blob 4\0data").hexdigest()
    result = {
        "owner": "acme", "repo": "vehicle", "branch": "main",
        "path": "logs/can.csv", "name": "can.csv", "sha": blob_sha,
        "size": 4, "download_url": "https://raw.example/can.csv",
    }
    result.update(overrides)
    return result


def test_cache_identity_separates_repositories_and_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(github_fetcher, "CACHE_DIR", tmp_path)
    first = github_fetcher._cache_path(_remote_file())
    other_repo = github_fetcher._cache_path(_remote_file(repo="other"))
    other_path = github_fetcher._cache_path(_remote_file(path="archive/can.csv"))
    assert len({first, other_repo, other_path}) == 3
    assert all(path.is_relative_to(tmp_path) for path in (first, other_repo, other_path))


def test_matching_sha_reuses_cache_but_changed_sha_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(github_fetcher, "CACHE_DIR", tmp_path)
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return Response(b"data")

    monkeypatch.setattr(github_fetcher.requests, "get", fake_get)
    done = []
    first = _remote_file()
    worker = github_fetcher.BatchDownloadWorker([first])
    worker.all_done.connect(done.append)
    worker.run()
    worker = github_fetcher.BatchDownloadWorker([first])
    worker.run()
    worker = github_fetcher.BatchDownloadWorker([_remote_file(sha="b" * 40)])
    worker.run()
    assert len(calls) == 2
    assert Path(done[0][0]).read_bytes() == b"data"


def test_same_size_corrupt_cache_is_redownloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(github_fetcher, "CACHE_DIR", tmp_path)
    remote = _remote_file()
    dest = github_fetcher._cache_path(remote)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"xxxx")
    calls = []
    monkeypatch.setattr(
        github_fetcher.requests, "get",
        lambda *a, **k: calls.append(a[0]) or Response(b"data"),
    )
    worker = github_fetcher.BatchDownloadWorker([remote])
    worker.run()
    assert calls == [remote["download_url"]]
    assert dest.read_bytes() == b"data"


def test_interrupted_download_never_leaves_valid_cache_file(tmp_path, monkeypatch):
    monkeypatch.setattr(github_fetcher, "CACHE_DIR", tmp_path)

    class BrokenResponse(Response):
        def iter_content(self, chunk_size=64 * 1024):
            yield b"part"
            raise OSError("connection lost")

    monkeypatch.setattr(github_fetcher.requests, "get", lambda *a, **k: BrokenResponse(b""))
    errors = []
    worker = github_fetcher.BatchDownloadWorker([_remote_file()])
    worker.file_error.connect(lambda path, error: errors.append(error))
    worker.run()
    assert errors
    assert not github_fetcher._cache_path(_remote_file()).exists()
    assert not list(tmp_path.rglob("*.part"))


def test_download_rejects_declared_oversized_file(tmp_path, monkeypatch):
    monkeypatch.setattr(github_fetcher, "CACHE_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(
        github_fetcher.requests, "get",
        lambda *a, **k: calls.append(a) or Response(b"data"),
    )
    errors = []
    worker = github_fetcher.BatchDownloadWorker([
        _remote_file(size=github_fetcher.MAX_DOWNLOAD_BYTES + 1)
    ])
    worker.file_error.connect(lambda path, error: errors.append(error))
    worker.run()
    assert calls == []
    assert errors and "too large" in errors[0].lower()
