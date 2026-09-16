from pathlib import Path

from retrieval_observatory.integrations.apply import apply_integration_plan
from retrieval_observatory.integrations.model import IntegrationOptions, IntegrationPhase, IntegrationResult
from retrieval_observatory.integrations.planner import build_integration_plan

NO_MANIFEST = "no retobs/integration.yaml: run apply first"


def resolve_db_path(db_path: str, project_root: Path) -> str:
    """A relative database path is anchored at the project root, matching ``trace_scope``."""
    path = Path(db_path)
    return str(path if path.is_absolute() else project_root / path)


async def integrate_project(project_root: Path, phase: IntegrationPhase, options: IntegrationOptions) -> IntegrationResult:
    root = project_root.resolve()
    if not root.is_dir():
        raise ValueError(f"project root does not exist: {root}")
    if phase is IntegrationPhase.PLAN:
        return IntegrationResult(
            "plan", "planned", plan=build_integration_plan(root, options.framework, db_path=options.db_path)
        )
    if phase is IntegrationPhase.APPLY:
        if options.plan is None:
            raise ValueError("apply requires a reviewed plan")
        return apply_integration_plan(options.plan)
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
    return await verify_project(root, store, policy=policy, db_path=db_path)
