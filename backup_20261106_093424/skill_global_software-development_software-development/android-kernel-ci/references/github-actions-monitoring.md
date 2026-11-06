# GitHub Actions: carrying workflows + monitoring runs

## Un-ignoring `.github/` when the repo has a blanket `.*` ignore rule

Many kernel repos' `.gitignore` starts with `.*` (ignores every dotfile/dir).
That silently excludes `.github/`, so a workflow cannot be committed. Add
negation rules AFTER the blanket line — and un-ignore each PARENT directory,
not just the file (a path inside an ignored dir stays ignored unless the dir
itself is re-included):

    !.github/
    !.github/workflows/
    !.github/workflows/*.yml

Confirm with `git check-ignore -v .github/workflows/*.yml` and a dry-run
`git add -n .github/workflows/*.yml` before committing. Spot-check for a
duplicate negation line (appending the same rule twice is harmless but sloppy —
clear it before landing).

## Auto-trigger + manual dispatch

Trigger on push to the feature branch, not all branches:
`on.push.branches: [<branch>]`. Also expose `workflow_dispatch` inputs so a run
can be fired on demand (full kernel build vs single target).

## Monitoring runs and reading logs

Check for a `gh` CLI AND a stored OAuth token BEFORE declaring CI logs
inaccessible. On this host `gh` lives at `/opt/data/.local/bin/gh` and
`~/.config/gh/hosts.yml` holds a token (scopes gist/read:org/repo) — so
`gh run view <run-id> --repo <owner>/<repo> --log-failed` returns the EXACT
failing compiler lines, which the unauth'd job-log endpoint (HTTP 403) never
gives you. Only fall back to the `curl` API
(`/repos/.../actions/runs?per_page=N`) when no gh auth exists. On hosts where
`gh` dies with `write tcp ... connection reset by peer` (an IPv6 route issue to
api.github.com), force IPv4 with `curl -4 -sS -H "Authorization: Bearer $(gh
auth token)" ...` — this is the working path; it is NOT a credential problem.
Piping through `python3 -c "import sys,json; ..."` keeps the JSON parseable
when the curl output would otherwise collapse.

## "The build is stuck" — establish ground truth BEFORE cancelling

Pull the job's STEP LIST first, before anything else, and re-read it immediately
before reporting. This is the only ground truth about a hang:

```sh
TOK=$(sed -n 's/.*oauth_token: //p' ~/.config/gh/hosts.yml | head -1)
curl -s -H "Authorization: token $TOK" \
  "https://api.github.com/repos/<owner>/<repo>/actions/runs/<run-id>/jobs" \
  | python3 -c "import json,sys; [print(s['number'],s['name'],s['conclusion'],s.get('started_at')) for j in json.load(sys.stdin)['jobs'] for s in j['steps']]"
```

A step with `conclusion: None` and a real `started_at` is the step in flight —
name it and quote its start time. Steps that never started also read `None`, so
distinguish them by the presence of `started_at`. A step whose timestamp moves
between two reads is progressing, not hung.

Then:

```sh
GH=<path to gh>
$GH run list --repo <owner>/<repo> --status in_progress --limit 20
$GH run list --repo <owner>/<repo> --status queued --limit 20
$GH run list --repo <owner>/<repo> --limit 5
```

- **Do not dismiss the user's report as a stale log window.** That assumption
  has been wrong: the user was watching a genuine hang while a newer run sat
  green. A hang is usually real and is usually on an OLDER run — the one the
  user is actually looking at in the UI. When the user names a run id or an
  ordinal, that id IS the task; do not substitute the newest run and do not
  answer about a different run than the one asked about.
- The newest run being green does NOT clear the run the user pointed at. A run
  dispatched from an older workflow commit can hang in the build step while the
  newest commit builds fine in 3–4 minutes. Resolve the named run's `head_sha`
  and compare it to the workflow commits you have shipped, then say plainly
  which commit the hung run is on.
- Nothing in progress → nothing to cancel. Say the newest run's
  id + conclusion + duration, name the artifacts it produced, and give the run
  URL.
- To sweep for stragglers across repos the account can see, enumerate
  `user/repos` with the token and run the `--status in_progress` query per repo
  rather than trusting one repo's list.
- Only when `in_progress` is non-empty AND the user confirms is a cancel
  legitimate: `POST /repos/<owner>/<repo>/actions/runs/<run-id>/cancel`
  (HTTP 202 = accepted; the run can stay `in_progress` for 20–60s, so verify
  with a follow-up GET). Cancelling is irreversible — never cancel a run the
  user has not explicitly confirmed.
- A `cancelled` row in history is usually EXPECTED — see the concurrency note
  below. Do not re-open a cancelled run; judge the newest one.
- A run stuck in the BUILD step for hours (not a download step) with no
  completion timestamp is consuming Actions minutes on a dead commit. Say so
  when recommending a cancel — "it will never finish and it is burning your
  Actions minutes" is the case the user needs to hear.
- A run that died before its publish-log step leaves an EMPTY log zip
  (`/actions/runs/<id>/logs` returns ~22 bytes). That is corroboration that
  the run never completed, not a permissions or path problem — do not go
  hunting for a log-reading workaround.

## Locating the gh binary and reading logs

Check for a `gh` CLI AND a stored OAuth token BEFORE declaring CI logs
inaccessible. On this host `gh` has been observed at `/opt/data/.local/bin/gh`
(also historically under `/tmp/gh_*_linux_arm64/bin/gh`, which is wiped on
restart) and `~/.config/gh/hosts.yml` holds a token with scopes
gist/read:org/repo/workflow. `gh auth status` confirms both in one call.

`gh run view --log` can fail with
`failed to get run log: creating cache directory: mkdir <HOME>/.cache: file exists`
when `$HOME/.cache` is a symlink whose target is gone or otherwise unusable —
this is a LOCAL cache-path failure, not a GitHub/permissions problem. Neither
`GH_CACHE_DIR` nor re-pointing `HOME` reliably fixes that variant. Use the
unauthenticated-free API endpoint instead, which is the working path:

```sh
TOK=$(sed -n 's/.*oauth_token: //p' ~/.config/gh/hosts.yml | head -1)
curl -s -H "Authorization: token $TOK" \
  "https://api.github.com/repos/<owner>/<repo>/actions/jobs/<job-id>/logs" \
  -o job.log
grep -c 'Bitmask of available\|Error in reading' job.log   # proof-of-clean
```

Get the job id from `gh run view <run-id> --repo <owner>/<repo>` (the JOBS
block prints it). Verify the fix by grepping the downloaded log for the exact
symptom string and reporting the hit COUNT (0 = clean) — a green run alone does
not prove the prompt stopped, and the log is the only evidence that it did.
Also check `gh run view --job=<id>` for the ANNOTATIONS block: deprecation
notices (Node 20 → forced Node 24) are noise, not build failures.

## Triggering a build (workflow_dispatch) with input overrides

Kit repos (e.g. Kernel_Action) are thin dispatcher repos whose workflow reads
the actual kernel source from a `KERNEL_SOURCE` repo at a configurable source
branch — by default the user's kitchen-sink branch. When the work to build
lives on a DIFFERENT branch (e.g. `mglru-v5`), dispatch explicitly and pass the
source-branch input; never assume the default builds what you want:

```sh
curl -4 -sS -X POST -H "Authorization: Bearer $(gh auth token)" \
  -H "Accept: application/vnd.github+json" -H "Content-Type: application/json" \
  "https://api.github.com/repos/<owner>/<kit-repo>/actions/workflows/<wf>.yml/dispatches" \
  -d '{"ref":"<kit-branch>","inputs":{"KERNEL_SOURCE_BRANCH":"<source-branch>"}}'
```

HTTP 204 means accepted (no body). Read the triggering workflow file first via
the contents API to learn which inputs exist (and their defaults) before
dispatching. Confirm the run with `.../actions/runs?per_page=3` and watch it
with a background loop that polls `status` until `completed` then prints
`conclusion`.

`gh` in this installed version rejects the JSON field name `headCommit` — the
valid field is `headSha` (list available fields with a dummy
`--json <field> --jq` probe that prints the accepted field names, then retry).
This fails the whole command with `Unknown JSON field`, NOT a partial result, so
it can look like a network/auth error — check field names first when a `gh`
query dies.

Concurrency semantics: if the workflow sets `concurrency.group` +
`cancel-in-progress: true`, a new push CANCELS the still-running run for the
same ref. A status of `cancelled` on a superseded run is EXPECTED, not a
failure — judge only the newest run. A run may sit `pending` behind an earlier
`in_progress` on the same group.
