# PyPI / TestPyPI trusted publishing (`retobs`)

Publishing uses **OIDC trusted publishers** (no API tokens in GitHub secrets). The package name in `pyproject.toml` must **exactly match** the project name on each trusted publisher.

Current distribution name: **`retobs`** (see `name = "retobs"` in `pyproject.toml`).

## Required setup (do this after renaming from `retrieval-observatory`)

### TestPyPI

1. Open [test.pypi.org/manage/account/publishing](https://test.pypi.org/manage/account/publishing)
2. **Add a new pending publisher** (or trusted publisher if the project already exists):
   - **PyPI project name:** `retobs`
   - **Owner:** `AmeyaKI`
   - **Repository name:** `retrieval-observatory`
   - **Workflow name:** `publish.yml`
   - **Environment name:** `testpypi`
3. Remove or ignore any publisher still pointing at project name `retrieval-observatory`.

### PyPI (production)

1. Open [pypi.org/manage/account/publishing](https://pypi.org/manage/account/publishing)
2. Add the same publisher with environment name **`pypi`** (not `testpypi`).

### GitHub environments

In the repo → **Settings → Environments**, confirm these exist:

| Environment | Used by |
|-------------|---------|
| `testpypi` | `publish-testpypi` job |
| `pypi` | `publish-pypi` job |

Environment names are case-sensitive and must match the trusted publisher config.

## Common error

```
400 Non-user identities cannot create new projects.
This was probably caused by successfully using a pending publisher but
specifying the project name incorrectly...
```

**Cause:** Trusted publisher project name ≠ wheel metadata name. After the rename, publishers must use **`retobs`**, not `retrieval-observatory`.

## Re-run after fixing

1. Fix trusted publishers on TestPyPI (and PyPI before production publish).
2. In GitHub Actions, **Re-run failed jobs** on the latest tag workflow, or push a new tag:

```bash
git tag v0.3.2
git push origin v0.3.2
```
