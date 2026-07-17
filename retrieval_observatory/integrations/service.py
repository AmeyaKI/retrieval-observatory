from pathlib import Path

from retrieval_observatory.integrations.apply import apply_integration_plan
from retrieval_observatory.integrations.model import IntegrationOptions, IntegrationPhase, IntegrationResult
from retrieval_observatory.integrations.planner import build_integration_plan


async def integrate_project(project_root: Path, phase: IntegrationPhase, options: IntegrationOptions) -> IntegrationResult:
    root = project_root.resolve()
    if phase is IntegrationPhase.PLAN:
        return IntegrationResult("plan", "planned", plan=build_integration_plan(root))
    if phase is IntegrationPhase.APPLY:
        if options.plan is None:
            raise ValueError("apply requires a reviewed plan")
        return apply_integration_plan(options.plan)
    from retrieval_observatory.integrations.verify import verify_project
    from retrieval_observatory.store.sqlite import SQLiteStore
    store = SQLiteStore(options.db_path)
    await store.init_db()
    return await verify_project(root, store)
