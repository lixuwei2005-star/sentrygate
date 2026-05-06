# Step 8 GitHub Release Preparation Spec

## 1. Goal

Prepare SentryGate for GitHub publication as a credible internship portfolio project.

This step is documentation-only. It defines the final checks and release workflow before publishing the existing local repository to GitHub.

## 2. Pre-push checks

Before pushing to GitHub, confirm the repository is in a clean and reviewable state.

### Git state

Run from the repository root:

```bash
git status
git log --oneline --decorate --graph -n 10
```

Expected result:

- `git status` should be clean after all intended files are committed.
- `git log` should show meaningful commits that explain the project progression.

### Backend checks

Run:

```bash
cd backend
uv run pytest
uv run ruff check .
uv run mypy app
```

Expected result:

- Tests pass.
- Ruff reports no lint errors.
- Mypy reports no type errors for `app`.

### Demo check

Run:

```bash
cd backend
uv run python scripts/demo_sentrygate.py
```

Expected result:

- The demo runs successfully.
- The output clearly demonstrates SentryGate's privacy masking, policy risk scoring, safe tool audit, and MCP-only boundary.

## 3. Repository content check

Confirm the following important files and directories exist before release:

- `README.md`
- `docs/demo-output.md`
- `docs/resume-bullets.md`
- `docs/interview-notes.md`
- `backend/app/`
- `backend/tests/`
- `backend/scripts/demo_sentrygate.py`
- `.gitignore`

These files support the portfolio story:

- `README.md` introduces the project and explains the boundary.
- `docs/demo-output.md` provides a quick review artifact.
- `docs/resume-bullets.md` supports resume usage.
- `docs/interview-notes.md` prepares interview explanations.
- `backend/app/`, `backend/tests/`, and `backend/scripts/demo_sentrygate.py` show implementation, verification, and demonstration.

## 4. Sensitive file check

Before pushing, confirm sensitive, local, generated, or cache files are not tracked:

- `.env`
- `.env.*`
- `backend/.venv/`
- `.claude/`
- `__pycache__/`
- `.pytest_cache/`
- `.mypy_cache/`
- `.ruff_cache/`

Suggested commands:

```bash
git status --ignored
git ls-files
```

Expected result:

- No secrets are tracked.
- No virtual environment files are tracked.
- No local assistant, Python cache, test cache, type-check cache, or lint cache directories are tracked.

## 5. GitHub repository creation

Recommended GitHub repository name:

- `sentrygate`

Recommended visibility:

- Public if ready for portfolio review.
- Private if still polishing.

Important:

- Do not initialize the GitHub repository with a README, `.gitignore`, or license if the local repository already has files.
- Create an empty GitHub repository, then push the existing local repository to it.

## 6. Push commands

Use either SSH or HTTPS, depending on the local GitHub authentication setup.

### SSH

```bash
git remote add origin git@github.com:lixuwei2005-star/sentrygate.git
git branch -M main
git push -u origin main
```

### HTTPS

```bash
git remote add origin https://github.com/lixuwei2005-star/sentrygate.git
git branch -M main
git push -u origin main
```

If `origin` already exists, inspect it before changing it:

```bash
git remote -v
```

## 7. Optional license

If SentryGate will be public and reusable, consider adding an MIT License.

MIT is a common choice for portfolio projects because it clearly permits reuse while preserving attribution and warranty disclaimers.

Do not add a license automatically in this step. License choice should be intentional before release.

## 8. Final portfolio checklist

Before sharing the GitHub repository link, confirm:

- README explains the MCP-only boundary.
- README does not overclaim production security.
- Demo runs.
- Tests pass.
- Docs explain resume and interview usage.
- No secrets are committed.
- GitHub repo link can be added to resume.

## Release checklist

Use this final checklist before publishing:

- [ ] `git status` is clean.
- [ ] `git log` shows meaningful commits.
- [ ] `uv run pytest` passes from `backend`.
- [ ] `uv run ruff check .` passes from `backend`.
- [ ] `uv run mypy app` passes from `backend`.
- [ ] `uv run python scripts/demo_sentrygate.py` runs from `backend`.
- [ ] Required repository files and directories exist.
- [ ] Sensitive and generated files are not tracked.
- [ ] GitHub repository is created as `sentrygate`.
- [ ] GitHub repository is public if ready for portfolio use, or private if still polishing.
- [ ] GitHub repository was not initialized with duplicate README, `.gitignore`, or license files.
- [ ] Remote origin is configured correctly.
- [ ] Local `main` branch is pushed to GitHub.
- [ ] Optional license decision is made.
- [ ] Final GitHub repository link is ready for resume use.

## Acceptance criteria

- This spec exists at `docs/specs/STEP_8_GITHUB_RELEASE_SPEC.md`.
- No backend code is changed.
- No README is changed.
- No tests are changed.
- No scripts are changed.
- Release checklist is clear.
