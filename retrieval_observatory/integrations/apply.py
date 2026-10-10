import ast
from dataclasses import replace
from hashlib import sha256
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from retrieval_observatory.integrations.manifest import load_manifest, write_manifest
from retrieval_observatory.integrations.model import (
    ADAPTER_MODULE,
    IntegrationCheck,
    IntegrationManifest,
    IntegrationPlan,
    IntegrationResult,
    PatchOperation,
)
from retrieval_observatory.integrations.planner import INSTRUMENTATION_MARKER

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
    return IntegrationResult("apply", "applied", plan=plan, changed_files=changed, checks=_scenario_command_checks(plan))


def _scenario_command_checks(plan: IntegrationPlan) -> tuple[IntegrationCheck, ...]:
    """Apply runs nothing; a scenario without a command is named here so it is not silently skipped."""
    missing = [scenario.scenario_id for scenario in plan.scenarios if not (scenario.command or "").strip()]
    if not missing:
        return ()
    return (
        IntegrationCheck(
            "scenario_commands", "warn", "static", "1.0", len(plan.scenarios),
            limitations=tuple(f"scenario {scenario_id} has no command: nothing will exercise it" for scenario_id in missing),
            fix="set each scenario's command in the plan to the call that exercises the entrypoint, re-plan, and run it before verify",
        ),
    )


def _has_retobs_edits(text: str) -> bool:
    return INSTRUMENTATION_MARKER in text or "retrieval_observatory.sdk.observe import" in text


def revert_integration(project_root: Path) -> IntegrationResult:
    """Restore every file apply patched, from the manifest's reversal patches, and drop the manifest.

    A file edited since apply is never overwritten. Every other file is still restored, and the
    manifest keeps only the patches left undone, so the project is never left with more of
    retobs in it than it needs and a later revert picks up where this one stopped.
    """
    root = project_root.resolve()
    manifest_path = root / "retobs" / "integration.yaml"
    if not manifest_path.is_file():
        return IntegrationResult("revert", "failed", errors=(NO_MANIFEST,))
    manifest = load_manifest(root)
    restorable, modified = [], []
    for patch in manifest.reversal_patches:
        target = _target(root, patch.relative_path)
        current = target.read_bytes() if target.is_file() else None
        if current is not None and sha256(current).hexdigest() == patch.precondition_sha256:
            restorable.append((target, patch))
        elif current is not None and _has_retobs_edits(current.decode("utf-8", errors="replace")):
            modified.append(patch)
        # Otherwise the file was deleted or cleaned by hand since apply: nothing of retobs is left.
    _write_atomically([(target, patch.replacement) for target, patch in restorable])
    restored = tuple(patch.relative_path for _target_path, patch in restorable)
    manifest_relative = str(manifest_path.relative_to(root))
    if not modified:
        manifest_path.unlink()
        return IntegrationResult("revert", "reverted", changed_files=restored + (manifest_relative,))
    write_manifest(root, replace(manifest, reversal_patches=tuple(modified)))
    return IntegrationResult(
        "revert",
        "failed",
        changed_files=restored,
        errors=tuple(
            f"cannot revert {patch.relative_path}: modified since apply; delete the lines retobs added "
            f"(the '@observe'/'@trace_scope' decorators, the retobs import and the comment "
            f"{INSTRUMENTATION_MARKER!r}) by hand, then run revert again"
            for patch in modified
        ),
    )
