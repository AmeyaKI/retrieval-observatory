import json
from pathlib import Path

from retrieval_observatory.integrations.apply import NO_MANIFEST, apply_integration_plan, revert_integration
from retrieval_observatory.integrations.model import IntegrationOptions, IntegrationPhase, IntegrationPlan, IntegrationResult
from retrieval_observatory.integrations.planner import build_integration_plan
from retrieval_observatory.integrations.record import build_integration_record, save_integration_record

__all__ = ["NO_MANIFEST", "integrate_project", "resolve_db_path"]


def resolve_db_path(db_path: str, project_root: Path) -> str:
    """A relative database path is anchored at the project root, matching ``trace_scope``."""
    path = Path(db_path)
    return str(path if path.is_absolute() else project_root / path)


async def integrate_project(project_root: Path, phase: IntegrationPhase, options: IntegrationOptions) -> IntegrationResult:
    root = project_root.resolve()
    if not root.is_dir():
        raise ValueError(f"project root does not exist: {root}")
    if phase is IntegrationPhase.PLAN:
        # With a reviewed plan this re-plans from its operators and scenarios (patches regenerated).
        plan = build_integration_plan(root, options.framework, db_path=options.db_path, reviewed=options.plan)
        return IntegrationResult("plan", "planned", plan=plan)
    if phase is IntegrationPhase.APPLY:
        if options.plan is None:
            raise ValueError("apply requires a reviewed plan")
        return apply_integration_plan(options.plan)
    if phase is IntegrationPhase.REVERT:
        return revert_integration(root)
    from retrieval_observatory.integrations.manifest import load_manifest
    from retrieval_observatory.integrations.verify import verify_project
    from retrieval_observatory.release.policy import load_release_policy
    from retrieval_observatory.store.sqlite import SQLiteStore
    if not (root / "retobs" / "integration.yaml").is_file():
        return IntegrationResult("verify", "failed", errors=(NO_MANIFEST,))
    if options.plan is not None:
        applied = load_manifest(root).plan_id
        if options.plan.plan_id != applied:
            raise ValueError(
                f"plan_id mismatch: the supplied plan is {options.plan.plan_id} but retobs/integration.yaml "
                f"records {applied}; verify reads the applied manifest, so pass that plan or omit it"
            )
    db_path = resolve_db_path(options.db_path, root)
    store = SQLiteStore(db_path)
    await store.init_db()
    policy = load_release_policy(options.policy_path) if options.policy_path else None
    result = await verify_project(root, store, policy=policy, db_path=db_path)
    manifest = load_manifest(root)
    plan = options.plan or _saved_plan(root, manifest.plan_id)
    await save_integration_record(store, build_integration_record(manifest, result, project_root=root, db_path=db_path, plan=plan))
    return result


def _saved_plan(root: Path, plan_id: str) -> IntegrationPlan | None:
    """The reviewed plan file next to the manifest, when it is the plan that was applied."""
    path = root / "retobs" / "integration-plan.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        plan = IntegrationPlan.from_dict(payload.get("plan", payload))
    except (OSError, ValueError, TypeError):
        return None
    return plan if plan.plan_id == plan_id else None
