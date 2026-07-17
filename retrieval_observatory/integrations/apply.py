from hashlib import sha256
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from retrieval_observatory.integrations.manifest import write_manifest
from retrieval_observatory.integrations.model import IntegrationManifest, IntegrationPlan, IntegrationResult, PatchOperation


def apply_integration_plan(plan: IntegrationPlan) -> IntegrationResult:
    plan.validate_for_apply()
    root = Path(plan.project_root).resolve()
    targets = []
    originals = []
    for patch in plan.patches:
        target = (root / patch.relative_path).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"patch escapes project root: {patch.relative_path}")
        if not target.is_file() or sha256(target.read_bytes()).hexdigest() != patch.precondition_sha256:
            raise ValueError(f"stale integration plan: {patch.relative_path}")
        targets.append((target, patch))
        originals.append(target.read_text(encoding="utf-8"))
    staged = []
    try:
        for target, patch in targets:
            with NamedTemporaryFile("w", dir=target.parent, delete=False, encoding="utf-8") as handle:
                handle.write(patch.replacement)
                staged.append((Path(handle.name), target))
        for temporary, target in staged:
            os.replace(temporary, target)
        reversals = tuple(
            PatchOperation(
                patch.relative_path,
                sha256(patch.replacement.encode()).hexdigest(),
                original,
            )
            for (_, patch), original in zip(targets, originals)
        )
        manifest_path = write_manifest(root, IntegrationManifest.from_plan(plan, reversals))
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    changed = tuple(p.relative_path for p in plan.patches) + (str(manifest_path.relative_to(root)),)
    return IntegrationResult("apply", "applied", plan=plan, changed_files=changed)
