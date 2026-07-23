# PyPI / TestPyPI trusted publishing (`retrieval-observatory`)

Publishing uses **OIDC trusted publishers** (no API tokens in GitHub secrets). The package name in `pyproject.toml` must **exactly match** the project name on each trusted publisher.

Current distribution name: **`retrieval-observatory`** (see `name = "retrieval-observatory"` in `pyproject.toml`).

Public import: `import retrieval_observatory as ro`.

---

## One-time setup (trusted publishers)

### TestPyPI

1. Open [test.pypi.org/manage/account/publishing](https://test.pypi.org/manage/account/publishing)
2. **Add a new pending publisher** (or trusted publisher if the project already exists):
   - **PyPI project name:** `retrieval-observatory`
   - **Owner:** `AmeyaKI`
   - **Repository name:** `retrieval-observatory`
   - **Workflow name:** `publish.yml`
   - **Environment name:** `testpypi`
3. **Remove** any publisher still pointing at project name `retobs` (from the brief rename experiment).

### PyPI (production)

1. Open [pypi.org/manage/account/publishing](https://pypi.org/manage/account/publishing)
2. Add the same publisher with environment name **`pypi`** (not `testpypi`).
3. **Remove** any `retobs` trusted publisher if present.

### GitHub environments

In the repo → **Settings → Environments**, confirm these exist:

| Environment | Used by |
|-------------|---------|
| `testpypi` | `publish-testpypi` job |
| `pypi` | `publish-pypi` job |

Environment names are case-sensitive and must match the trusted publisher config.

---

## Common error

```
400 Non-user identities cannot create new projects.
This was probably caused by successfully using a pending publisher but
specifying the project name incorrectly...
```

**Cause:** Trusted publisher project name ≠ wheel metadata name. Publishers must use **`retrieval-observatory`**, not `retobs`.

Wheel filename on disk uses underscores: `retrieval_observatory-0.3.3-py3-none-any.whl`  
METADATA `Name` field uses hyphen: `retrieval-observatory`

---

## Release checklist

### 1. Code (repo)

- [ ] `pyproject.toml`: `name = "retrieval-observatory"`, version bumped
- [ ] No `retobs/` shim package in tree (only `retrieval_observatory/`)
- [ ] Docs/examples use `pip install retrieval-observatory[...]` and `import retrieval_observatory as ro`
- [ ] `CHANGELOG.md` updated
- [ ] Source CI and the reusable `release-candidate` workflow are green

### 2. Tag and push

```bash
git tag v0.5.4
git push origin main
git push origin v0.5.4
```

Tag must match `version` in `pyproject.toml` exactly (without the `v` prefix).

### 3. Watch GitHub Actions

- **Publish** runs `release-candidate` once, then `publish-testpypi`, then `publish-pypi`.
- The candidate produces `release-dist` and `release-evidence` artifacts with SHA-256 manifests.
- Both promotion jobs verify `release-evidence/artifact-manifest.json`; neither checks out source or rebuilds a distribution.
- TestPyPI smoke installs the exact local wheel with dependencies from PyPI, then records installed-wheel evidence and TestPyPI metadata.
- PyPI promotion verifies the published wheel and sdist digests before the workflow can pass. Post-upload JSON checks retry until the index is visible (PyPI can 404 briefly after a successful upload).

### 4. Verify on PyPI

```bash
curl -sf "https://pypi.org/pypi/retrieval-observatory/0.5.4/json" | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])"

pip install "retrieval-observatory[dashboard]==0.5.4"
python -c "import retrieval_observatory as ro; print(ro.__version__ if hasattr(ro,'__version__') else 'ok')"
retobs --help
```

---

## Reverting from the `retobs` PyPI name (v0.3.1–0.3.2)

If you briefly published under `retobs`:

1. **Stop publishing to `retobs`** — revert `pyproject.toml` name to `retrieval-observatory` (done in v0.3.3).
2. **Delete `retobs/` shim** from the repo (done in v0.3.3).
3. **Update trusted publishers** on TestPyPI and PyPI to point at `retrieval-observatory` (steps above).
4. **Optional:** On [pypi.org/project/retobs](https://pypi.org/project/retobs), add a project description note: *"This package was renamed. Use `pip install retrieval-observatory` instead."* PyPI does not support redirects; you cannot delete a published project name.
5. **Tag and publish** the next version under `retrieval-observatory`.

Users who installed `retobs` should switch:

```bash
pip uninstall retobs -y
pip install "retrieval-observatory[dashboard]"
```

Then update imports: `import retrieval_observatory as ro`

---

## Re-run after fixing publishers

1. Fix trusted publishers on TestPyPI (and PyPI before production publish).
2. In GitHub Actions, **Re-run failed jobs** on the latest tag workflow, or push a new tag:

```bash
git tag v0.5.4
git push origin v0.5.4
```
