#!/bin/bash
# Poll a GitHub Actions publish branch until it advances past a known-good SHA.
# The branch (e.g. `kbuilds`) is force-pushed only on a successful build, so a
# new head SHA means a bootable artifact exists. No API/gh auth required.
#
# usage: watch_kbuilds.sh <repo-dir> <branch> <old-sha> [interval_s] [tries]
#   watch_kbuilds.sh /srv/ssd/kaction kbuilds b03e51a... 60 90
set -u
export GIT_SSH_COMMAND="ssh -i ${KA_KEY:-$HOME/.ssh/id_ed25519_github_ka} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

REPO=${1:?repo dir}; BRANCH=${2:?branch}; OLD=${3:?baseline sha}
INTERVAL=${4:-60}; TRIES=${5:-90}

cd "$REPO" || exit 2
for _ in $(seq 1 "$TRIES"); do
  NEW=$(timeout 40 git ls-remote origin "refs/heads/$BRANCH" 2>/dev/null | cut -f1)
  if [ -n "$NEW" ] && [ "$NEW" != "$OLD" ]; then
    echo "NEW BUILD: $NEW"
    # one ref per fetch; multi-ref fetch with a deploy key can fail outright
    timeout 120 git fetch origin "$BRANCH" --depth=1 2>&1 | tail -1
    git log --format='%h %ci %s' -1 FETCH_HEAD
    git ls-tree -r --long FETCH_HEAD
    exit 0
  fi
  sleep "$INTERVAL"
done
echo "TIMEOUT: $BRANCH still $OLD"
exit 1
