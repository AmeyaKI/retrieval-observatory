from retrieval_observatory.dashboard.api import _is_static_asset_path


def test_static_asset_paths():
    assert _is_static_asset_path("assets/index-abc.js")
    assert _is_static_asset_path("assets/index-abc.css")
    assert _is_static_asset_path("favicon.ico")
    assert not _is_static_asset_path("")
    assert not _is_static_asset_path("runs")
