# Termux kit delivery and push loop

The user works from an Android tablet in Termux: unzip kit, copy into a fresh
clone, commit, push. Their device never compiles. Give ONE copy-paste block
with explicit `cd` between stages, and state the expected output of each
verification step. Guide; don't do it for them.

## Standard delivery block

```bash
cd ~
rm -rf kit repo
mkdir kit && cd kit
unzip "$(find /storage/emulated/0 -name '<kit-file>.zip' 2>/dev/null | head -1)"
ls        # must list the kit contents before continuing
cd ~
git clone https://github.com/<user>/<repo>.git repo
cp -r ~/kit/. ~/repo/
cd ~/repo
git add .
git commit -m "<version>: <one-line fix summary>"
git push -u origin main
git log --oneline -1   # MUST show the new commit message before checking Actions
```

## Update delivery (repo already exists)

Once the user's repo is established, later kits ship as UPDATES: fresh-clone
instructions and `-u` push flags no longer apply, and the block should say
explicitly which artifact is new and that old images stay untested until the
new control passes.

```bash
cd ~
rm -rf kit repo
mkdir kit && cd kit
unzip "$(find /storage/emulated/0 -name '<kit-file>.zip' 2>/dev/null | head -1)"
ls        # must list the kit contents before continuing
cd ~
git clone https://github.com/<user>/<repo>.git repo
cp -r ~/kit/. ~/repo/
cd ~/repo
git status    # should list only the intended files as modified
git add .
git commit -m "<version>: <one-line fix summary>"
git push origin main
git log --oneline -1   # MUST show the new commit message before checking Actions
```

The `git status` gate between copy and add is what catches a bad unpack on an
update: an empty or flattened kit shows as few or no modified files here,
before a wrong commit reaches the remote.

## Pitfalls (recurring)

- Git commands run from `~` fail with `fatal: not a git repository`. Every
  block must `cd` into the repo dir; end with the `git log --oneline -1` check
  and name the expected message.
- A `root@host` prompt means a proot/chroot distro, not vanilla Termux, so
  `pkg` is absent: give `pkg install git unzip || apt-get install -y git unzip`.
- Shared storage is invisible until `termux-setup-storage` runs once (Android
  permission popup, tap Allow). Locate downloads with
  `find /storage/emulated/0 -name '<file>'` instead of guessing the chat app's
  save subfolder — it varies. If find returns nothing, have the user re-save
  the file "to Downloads" from the chat app first.
- After a failed unzip, `cp -r kit/. repo/` copies nothing: commit says
  "nothing to commit", push says "Everything up-to-date". That output means the
  remote never received files — do not celebrate it as success. The `ls` gate
  after unzip exists to catch this.
- GitHub HTTPS push needs a personal access token (classic, `repo` scope) as
  the password, not the account password; after first success suggest
  `git config --global credential.helper store`.
- Restate on delivery that all compilation happens on CI runners and the tablet
  only moves files — users conflate kernel builds with local CPU load and worry
  about device heat.
