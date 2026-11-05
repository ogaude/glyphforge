# Releasing

GlyphForge is pushed to a private GitHub repo first, made public after review, and released as a tagged GitHub release. Publishing to PyPI is optional and off until `PUBLISH_PYPI` is set. All repo-level values below use owner `ogaude` and repo `glyphforge`.

## One-time setup (private first)

1. Create the empty **private** repo `github.com/ogaude/glyphforge` with no README, licence or .gitignore.
2. Confirm the local identity: `git config user.name` is `ogaude` and `git config user.email` is `ogaude.code@proton.me`.
3. Add the remote and push:

   ```bash
   git remote add origin git@github.com:ogaude/glyphforge.git
   git push -u origin main
   ```

4. Do not create environments or PyPI publishers at this step.

Actions minutes are metered on private repos. The `ci` workflow runs on push; the Docker tests are in `docker-tests` (nightly and manual).

## Going public

1. Apply the history decision (publish `.planning/` and `CLAUDE.md` as is, or drop them from history). A history rewrite after a push means deleting and recreating the private repo; a force-push leaves old commits reachable by SHA.
2. Confirm the dataset gate and review the Hugging Face dataset page.
3. Squash the private Hugging Face history, then flip Hugging Face and GitHub to public in one step.
4. Tag and push:

   ```bash
   git tag -a v0.1.0 -m v0.1.0
   git push origin v0.1.0
   ```

   With `PUBLISH_PYPI` unset, the `release.yml` run checks the version, builds, runs the Docker tests and creates the GitHub release. The PyPI jobs show as skipped.

Until PyPI exists, install from git:

```bash
pip install "glyphforge[cli,hf] @ git+https://github.com/ogaude/glyphforge@v0.1.0"
```

## Releasing

1. Add a `## [X.Y.Z] - date` section to `CHANGELOG.md`.
2. Bump the version in `pyproject.toml` and `CITATION.cff`, then run `uv lock`.
3. Commit, then tag and push:

   ```bash
   git tag -a vX.Y.Z -m vX.Y.Z
   git push origin vX.Y.Z
   ```

4. When `PUBLISH_PYPI` is `true`, approve the `pypi` environment once the TestPyPI smoke job is green.

## PyPI (optional, if/when released)

Do this only once the repo is public (required reviewers need a public repo on the free plan).

GitHub environments (Settings > Environments):

- `testpypi`: no reviewers.
- `pypi`: Required reviewers `ogaude`; deployment tags `v*`.

Pending publishers (Account > Publishing > Add a new pending publisher > GitHub), on both pypi.org and test.pypi.org:

| Field | Value |
|-------|-------|
| PyPI project name | `glyphforge` |
| Owner | `ogaude` |
| Repository name | `glyphforge` |
| Workflow name | `release.yml` |
| Environment name | `pypi` on pypi.org, `testpypi` on test.pypi.org |

Switch publishing on and publish an already-tagged version:

```bash
gh variable set PUBLISH_PYPI --body true --repo ogaude/glyphforge
gh workflow run release.yml --repo ogaude/glyphforge --ref vX.Y.Z
```

The pending publisher becomes a normal one after the first upload.

## Nightly jobs

`docker-tests` runs nightly and a Pillow canary job runs alongside it. GitHub pauses scheduled workflows after long repo inactivity; start them by hand with `workflow_dispatch` (`gh workflow run docker-tests.yml --repo ogaude/glyphforge`).

## Troubleshooting

- OIDC "no matching publisher": a pending-publisher field does not match the table above (owner, repo, workflow name or environment name).
- A failing docker job blocks the GitHub release and publishing by design.
- Publish jobs shown as skipped mean `PUBLISH_PYPI` is unset.
