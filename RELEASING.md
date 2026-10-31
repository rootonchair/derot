# Releasing

Releases are built and published by GitHub Actions (`.github/workflows/release.yml`) using
PyPI [Trusted Publishing](https://docs.pypi.org/trusted-publishers/): no API tokens are
stored anywhere.

## One-time setup

1. Create accounts on [pypi.org](https://pypi.org/account/register/) and
   [test.pypi.org](https://test.pypi.org/account/register/) (separate accounts), with 2FA.
2. On each site, add a **pending publisher** (pypi.org → Your projects → Publishing →
   "Add a new pending publisher"; same on test.pypi.org):

   | Field | PyPI | TestPyPI |
   |---|---|---|
   | PyPI project name | `derot` | `derot` |
   | Owner | `rootonchair` | `rootonchair` |
   | Repository name | `derot` | `derot` |
   | Workflow name | `release.yml` | `release.yml` |
   | Environment name | `pypi` | `testpypi` |

   The first successful upload creates the project and turns the pending publisher into a
   normal one.
3. Optional: in GitHub → Settings → Environments → `pypi`, add yourself as a required
   reviewer, so every release waits for your click before it uploads.

## Dry run on TestPyPI

GitHub → Actions → **release** → Run workflow (on `main`). It runs the tests, builds,
installs the wheel on macOS and Linux, and uploads to TestPyPI. Then check it installs:

```sh
pipx install --index-url https://test.pypi.org/simple/ --pip-args="--extra-index-url https://pypi.org/simple/" derot
```

TestPyPI keeps every version too; a re-run of the same version is skipped, so bump the
version (e.g. `0.1.1.dev1`) if you need to upload again.

## Releasing a version

1. Set the version in `derot/__init__.py` (`__version__ = "0.1.0"`); it's the only place.
2. In `CHANGELOG.md`, change `## 0.1.0 (unreleased)` to `## 0.1.0 (YYYY-MM-DD)`.
3. Commit, then tag and push:

   ```sh
   git commit -am "Release 0.1.0"
   git tag v0.1.0
   git push origin main v0.1.0
   ```

The workflow checks that the tag matches `__version__`, runs the full test suite, builds,
test-installs the wheel, publishes to PyPI and creates a GitHub release with that version's
changelog section. A version can't be uploaded twice: fix mistakes with a new version.
