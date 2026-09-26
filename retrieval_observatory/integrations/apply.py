import ast
from hashlib import sha256
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from retrieval_observatory.integrations.manifest import load_manifest, write_manifest
from retrieval_observatory.integrations.model import (
    ADAPTER_MODULE,
    IntegrationManifest,
    IntegrationPlan,
    IntegrationResult,
    PatchOperation,
)

NO_MANIFEST = "no retobs/integration.yaml: run apply first"


def _already_applied(root: Path, plan: IntegrationPlan) -> bool:
    manifest_path = root / "retobs" / "integration.yaml"
    if not manifest_path.is_file():
        return False
    try:
        return load_manifest(root).plan_id == plan.plan_id
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _target(root: Path, relative_path: str) -> Path:
    target = (root / relative_path).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"patch escapes project root: {relative_path}")
    return target


def _write_atomically(files: list[tuple[Path, str]]) -> None:
    """Stage every file next to its target, then swap them all in; nothing is written on failure."""
    staged = []
    try:
        for target, content in files:
            with NamedTemporaryFile("w", dir=target.parent, delete=False, encoding="utf-8") as handle:
                handle.write(content)
                staged.append((Path(handle.name), target))
        for temporary, target in staged:
            os.replace(temporary, target)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def _adapter_defines(path: Path, symbol: str) -> bool:
    """``symbol`` is a module-level assignment, function, or class in the root adapter file."""
    if not path.is_file():
        return False
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
            return True
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(item, ast.Name) and item.id == symbol for item in targets):
            return True
    return False


def apply_integration_plan(plan: IntegrationPlan) -> IntegrationResult:
    plan.validate_for_apply()
    root = Path(plan.project_root).resolve()
    adapter = root / f"{ADAPTER_MODULE}.py"
    for operator in plan.operators:
        if operator.capture is not None:
            symbol = operator.capture.split(":", 1)[1]
            if not _adapter_defines(adapter, symbol):
                raise ValueError(f"capture {operator.capture}: {adapter} does not define {symbol}")
    targets = []
    originals = []
    for patch in plan.patches:
        target = _target(root, patch.relative_path)
        if not target.is_file() or sha256(target.read_bytes()).hexdigest() != patch.precondition_sha256:
            if _already_applied(root, plan):
                raise ValueError(
                    f"already applied (manifest present): plan {plan.plan_id} is recorded in retobs/integration.yaml; "
                    "run --phase verify, or re-plan to pick up new changes"
                )
            raise ValueError(f"stale integration plan: {patch.relative_path}")
        # A plan is a file on disk and may have been hand-edited between plan and apply. Never
        # write Python that does not parse: reporting "applied" over a broken module is worse
        # than refusing, because the failure surfaces far from its cause.
        if target.suffix == ".py":
            try:
                ast.parse(patch.replacement)
            except SyntaxError as error:
                raise ValueError(
                    f"patch would not compile: {patch.relative_path} line {error.lineno}: {error.msg}"
                ) from error
        targets.append((target, patch))
        originals.append(target.read_text(encoding="utf-8"))
    _write_atomically([(target, patch.replacement) for target, patch in targets])
    reversals = tuple(
        PatchOperation(
            patch.relative_path,
            sha256(patch.replacement.encode()).hexdigest(),
            original,
        )
        for (_, patch), original in zip(targets, originals)
    )
    manifest_path = write_manifest(root, IntegrationManifest.from_plan(plan, reversals))
    changed = tuple(p.relative_path for p in plan.patches) + (str(manifest_path.relative_to(root)),)
    return IntegrationResult("apply", "applied", plan=plan, changed_files=changed)


def revert_integration(project_root: Path) -> IntegrationResult:
    """Restore every file apply patched, from the manifest's reversal patches, and drop the manifest.

    A patched file must still hash to its post-apply content: an edit made since apply is never
    overwritten, and one modified file blocks the whole revert so the project is not left half-restored.
    """
    root = project_root.resolve()
    manifest_path = root / "retobs" / "integration.yaml"
    if not manifest_path.is_file():
        return IntegrationResult("revert", "failed", errors=(NO_MANIFEST,))
    manifest = load_manifest(root)
    targets = [(_target(root, patch.relative_path), patch) for patch in manifest.reversal_patches]
    modified = [
        patch.relative_path
        for target, patch in targets
        if not target.is_file() or sha256(target.read_bytes()).hexdigest() != patch.precondition_sha256
    ]
    if modified:
        raise ValueError("; ".join(f"cannot revert {path}: modified since apply; restore it manually" for path in modified))
    _write_atomically([(target, patch.replacement) for target, patch in targets])
    manifest_path.unlink()
    restored = tuple(patch.relative_path for patch in manifest.reversal_patches)
    return IntegrationResult("revert", "reverted", changed_files=restored + (str(manifest_path.relative_to(root)),))
