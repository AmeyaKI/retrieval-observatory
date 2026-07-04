"""Self-describing config tools: describe_config + validate_config (MCP + REST)."""
import pytest

from retrieval_observatory.config.discovery import config_schema, validate_config_dict


def test_schema_has_shape_and_examples():
    sc = config_schema()
    assert "json_schema" in sc
    assert sc["adapter_examples"]["adapter.http"]["type"] == "adapter.http"
    assert set(sc["dataset_examples"]) == {"beir", "custom"}
    assert sc["notes"]


def test_shipped_example_validates():
    sc = config_schema()
    report = validate_config_dict(sc["example_config"])
    assert report["valid"] is True
    assert report["status"] in ("ok", "warning")


def test_validate_rejects_malformed():
    report = validate_config_dict({"not": "a config"})
    assert report["valid"] is False
    assert report["status"] == "error"
    assert report["items"]


@pytest.mark.asyncio
async def test_mcp_discovery_tools_registered():
    from retrieval_observatory.mcp import server

    srv = server.build_server()
    names = {t.name for t in await srv.list_tools()}
    assert {"describe_config", "validate_config"} <= names
    # Sync tool logic is directly callable.
    assert server._validate_config(server._describe_config()["example_config"])["valid"]


def test_rest_config_endpoints(tmp_path):
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    from retrieval_observatory.dashboard.api import create_app

    db_path = str(tmp_path / "disc.db")
    with fastapi_testclient.TestClient(create_app(db_paths=[db_path])) as client:
        schema = client.get("/config/schema")
        assert schema.status_code == 200
        example = schema.json()["example_config"]
        good = client.post("/config/validate", json={"config": example})
        assert good.status_code == 200 and good.json()["valid"] is True
        bad = client.post("/config/validate", json={"config": {"x": 1}})
        assert bad.status_code == 200 and bad.json()["valid"] is False
