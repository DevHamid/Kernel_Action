# Diagnosing a kconfig prompt hang in CI

A build step that produces zero compiler output, runs until the job is killed,
and surfaces as `cancelled` is almost always `make` blocked on stdin. This is the
procedure for reading the log and naming the cause, plus the shapes a fix can
take.

## Read the log first, from the right place

A step's `in_progress` state carries no information about whether work is
happening. Get the log:

```sh
# published on the kit's build-logs branch (survives cancellation)
curl -sSL https://raw.githubusercontent.com/<kit>/build-logs/build-<sha>.log
curl -sSL https://raw.githubusercontent.com/<kit>/build-logs/config-<sha>.txt

# or the run's failure artifact
curl -sSL -H "Authorization: token $TOKEN" \
  https://api.github.com/repos/<kit>/actions/artifacts/<id>/zip
```

A cancelled run's `actions/runs/<id>/logs` zip can come back ~22 bytes with no
entries — that is not "no log exists".

## Read the prompt's shape before naming a cause

The values pre-filled in the prompts tell you which stage produced them:

- **Every prompt already carries the defconfig's value** (`EXT4_FS [Y/n/?] y`,
  `F2FS_FS [Y/n/?] y`) and the walk covers a whole menu: `conf --defconfig` DID
  read the defconfig, and `syncconfig` is asking only about symbols it could not
  materialize.
- **Prompts with no values filled in** mean the defconfig was never read at all.

A `(NEW)` tag on a symbol that IS in the committed defconfig means the symbol is
unreferenced — nothing `select`s it and nothing `depends on` it — so kconfig
treats it as new regardless of the defconfig line. Confirm both halves:

```sh
git show HEAD:<defconfig> | grep <SYM>          # rules out a missing line
grep -rn 'select <SYM>\|depends on <SYM>' <tree>  # proves the real cause
```

A tristate with `default y` and no reverse dependency is the canonical case: the
defconfig line is present and correct, and the symbol still prompts.

## Which make modes prompt

Read the kit's actual make lines before theorising:

```sh
TOKEN=$(grep -m1 oauth_token ~/.config/gh/hosts.yml | awk '{print $2}')
curl -sS -H "Authorization: token $TOKEN" \
  https://api.github.com/repos/<kit>/contents/.github/workflows/<wf>.yml
```

- `make <defconfig>` → `conf --defconfig`, then `conf_set_all_new_symbols(def_default)`.
- `make olddefconfig` → materializes every valueless symbol from its default and
  never reads stdin. Cannot prompt.
- plain `make` → `syncconfig`, and `syncconfig` DOES prompt
  (`case syncconfig:` falls through to `xfgets(stdin)` for any symbol with no
  value). It stays quiet only because `.config` is already complete.

So `make <defconfig>` followed by a plain `make` is prompt-free, not
prompt-proof. The next unmaterializable symbol puts the prompt back in the build
step.

## Fix shapes

| Shape | Verdict |
| --- | --- |
| `yes '' \| make ... olddefconfig` | **Broken under `set -o pipefail`** — `yes` takes SIGPIPE when `olddefconfig` finishes without consuming stdin, and `pipefail` turns that 141 into a step failure. The log shows `# configuration written to .config` immediately followed by `yes: standard output: Broken pipe`: the config pass succeeded, the pipeline did not. Confirm locally with `bash -c 'set -o pipefail; yes "" \| true; echo $?'` → 141. |
| `make ... olddefconfig < /dev/null` | Correct. Non-interactive by construction, and closing stdin is belt-and-braces if a prompt path is ever reached. |
| `KCONFIG_ALLCONFIG=<file>` | Correct for the `all*config` family, but it is read by `conf_read_simple` in those modes only — not by `syncconfig`. |
| Changing the symbol tristate→bool in the kernel tree | Smaller blast radius, but it changes the kernel to work around a kit defect, and it cannot be verified without `bison`/`flex` locally. |

The fix belongs in the kit workflow, not the kernel tree: a kernel-tree
workaround fixes the symptom on this tree and leaves the next tree exposed.

## Confirm the fix landed

A green run is not proof the config is right. Check the resolved `.config` that
the run actually produced:

```sh
curl -sSL https://raw.githubusercontent.com/<kit>/kbuilds/config.txt | grep <SYM>
```

and confirm the run published artifacts (`boot.img` starting with `ANDROID!`,
plus `Image.gz-dtb` and `config.txt`) rather than merely exiting 0.
