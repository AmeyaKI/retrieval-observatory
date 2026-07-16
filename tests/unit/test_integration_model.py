from retrieval_observatory.integrations.model import (
    IntegrationManifest,
    IntegrationPlan,
    IntegrationResult,
    PatchOperation,
)


def test_plan_round_trip_and_apply_validation(tmp_path) -> None:
    target = tmp_path / "app.py"
    target.write_text("old", encoding="utf-8")
    plan = IntegrationPlan.create(
        project_root=tmp_path,
        framework="python",
        service_id="svc",
        pipeline_id="pipe",
        patches=[PatchOperation.from_file(tmp_path, target, "new")],
        operators=[],
        candidate_mapping={"doc_id": "item.id", "score": "item.score", "rank": "enumerate"},
        scenarios=[],
    )
    restored = IntegrationPlan.from_dict(plan.to_dict())
    restored.validate_for_apply()
    assert restored.plan_id == plan.plan_id
    assert restored.patches[0].relative_path == "app.py"
    assert IntegrationManifest.from_dict(
        IntegrationManifest.from_plan(plan).to_dict()
    ) == IntegrationManifest.from_plan(plan)
    assert IntegrationResult.from_dict(IntegrationResult("plan", "planned", plan=plan).to_dict()).plan == plan


def test_plan_id_does_not_depend_on_project_location(tmp_path) -> None:
    values = dict(
        framework="python",
        service_id="svc",
        pipeline_id="pipe",
        patches=[],
        operators=[],
        candidate_mapping={"doc_id": "item.id"},
        scenarios=[],
    )
    assert (
        IntegrationPlan.create(project_root=tmp_path / "one", **values).plan_id
        == IntegrationPlan.create(project_root=tmp_path / "two", **values).plan_id
    )
