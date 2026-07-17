from pathlib import Path
import pytest

from retrieval_observatory.integrations.apply import apply_integration_plan
from retrieval_observatory.integrations.manifest import load_manifest
from retrieval_observatory.integrations.model import IntegrationPlan, PatchOperation


def _plan(root: Path, patches):
    return IntegrationPlan.create(project_root=root, framework="python", service_id="svc", pipeline_id="pipe", patches=patches, operators=(), candidate_mapping={"doc_id":"item.id"}, scenarios=())


def test_atomic_apply_and_manifest(tmp_path):
    target=tmp_path/"app.py";target.write_text("old")
    result=apply_integration_plan(_plan(tmp_path,[PatchOperation.from_file(tmp_path,target,"new")]))
    assert target.read_text()=="new" and result.status=="applied"
    manifest = load_manifest(tmp_path)
    assert manifest.service_id=="svc"
    assert manifest.reversal_patches[0].replacement == "old"
    assert manifest.reversal_patches[0].precondition_sha256


def test_stale_plan_does_not_modify_other_files(tmp_path):
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("a")
    b.write_text("b")
    plan = _plan(tmp_path, [PatchOperation.from_file(tmp_path, a, "A"), PatchOperation.from_file(tmp_path, b, "B")])
    b.write_text("stale")
    with pytest.raises(ValueError, match="stale integration plan"):
        apply_integration_plan(plan)
    assert a.read_text() == "a"
