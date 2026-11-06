# Publishing the hermes-memos-integration plugin repo

Repo: `github.com/DevHamid/hermes-memos-integration` (public, default branch `main`).

## Git root quirk
Git root is `/opt/data` (the whole Hermes home), NOT the plugin dir. `git -C /opt/data/plugins/usememos` resolves to `/opt/data/.git`. Stage plugin files relative to that root:

```bash
git -C /opt/data add plugins/usememos/__init__.py plugins/usememos/plugin.yaml plugins/usememos/README.md
git -C /opt/data commit -m "..."
git -C /opt/data push origin main
```

`git ls-files plugins/` is often empty — the repo initially tracked only skill docs under `skills/`. Verify the runnable code (`__init__.py`, `plugin.yaml`) is actually committed, not just the docs.

## GitHub auth (this host)
- `gh` CLI: `/opt/data/.local/bin/gh` v2.x. `/opt/data/.gitconfig` sets `credential.helper` → `gh auth git-credential` for github.com and gist.github.com.
- If `gh auth status` reports not logged in, log in via device flow:
  ```bash
  /opt/data/.local/bin/gh auth login --hostname github.com --git-protocol https --web --insecure-storage
  ```
  Answer `Y` to "Authenticate Git with your GitHub credentials?". Copy the one-time code from the output and give it to the user; they authorize at `https://github.com/login/device`. Device flow polls GitHub directly, so it completes even though the host browser is headless (the `xdg-open` failure message is harmless).
- After login, strip any stale embedded token from remote URLs so pushes use the credential helper instead:
  ```bash
  git -C /opt/data remote set-url origin https://github.com/DevHamid/hermes-memos-integration.git
  ```
- Verify: `gh auth status` shows "Logged in to github.com account DevHamid" with token scopes including `repo` (+ `workflow`).

## Secret scan before every push
Scan the staged diff for token patterns: `gho_`/`ghp_`/`github_pat_`, `sk-`, `Bearer <long>`, `access_token="literal"`, `password="literal"`. Benign hits: README placeholders (`your-token`) and code reads (`os.environ.get`, `self._config.get`). Only real literals are problems:

```bash
git diff --cached | grep -iE 'gho_|ghp_|github_pat_|sk-|access_token[\"' ]*[:=]' | grep -v 'your-token\|os.environ'
```
