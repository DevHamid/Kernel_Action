# Q6 subsystem bring-up contract (sdm660 / wayne)

Scope: what it actually takes to boot the modem MSS — and with it the WLAN,
which shares the MSS's servreg/QMI transport — on a non-Android userspace.
Companion to `missing-device-probe.md` §6d/§6e; this file carries the exact
firmware contract, the ops-table swap, and the order of work.

## 1. Who boots a subsystem

- `modem_powerup()` (`pil-q6v5-mss.c:146`) is the ONLY thing that starts the
  modem: sets `drv->q6->desc.fw_name = subsys->fw_name`, then
  `pil_boot(&drv->q6->desc)`.
- Reached only via `__subsystem_get(name, fw_name)`
  (`subsystem_restart.c:945`) → `subsys_start()` (`:836`) →
  `desc->powerup()`. A second call site of the same powerup is
  `subsystem_powerup()` (`:773`), used by the SSR/restart path.
- `pil_subsys_init()` (`pil-q6v5-mss.c:231`) ends at `subsys_register()`
  (`:274`) — that only allocates the device, adds it to `subsys_bus_type`
  ("msm_subsys"), creates the sysfs attrs and the `/dev/subsys_<name>` node.
  It does not power anything on.
- Grep the whole tree for `subsys_boot(` / `rproc_boot(` / callers of
  `subsystem_get(`: only unrelated drivers (`st_fdma.c`, `wkup_m3_ipc.c`)
  appear. **Nothing in the tree boots a subsystem.** Scope the grep to
  `drivers/` with an explicit `timeout` — a whole-tree run exceeds the tool
  timeout and its exit 124 reads as "no matches". Record what the enumeration
  actually returns so the next session does not re-derive it: IPA asks only for
  `ipa_fws` / `ipa_uc`, and wcnss / cdsp / spss / slpi / the zap shaders each
  ask for their own. `"modem"` is requested by nothing.
- **There is no userspace boot interface.** `subsys_device_fops`
  (`subsystem_restart.c:1411`) is `.open`/`.release` only — no `.read`,
  `.write`, or `.unlocked_ioctl`. `subsys_attrs[]` (`:382`: `name`, `state`,
  `crash_count`, `restart_level`, `firmware_name`, `system_debug`) are all
  read-only. `subsystem_get()` is `EXPORT_SYMBOL` kernel-only with no wrapper.
  Exposing the trigger requires a source patch to `subsystem_restart.c` plus
  a rebuild — never promise a userspace program.

## 2. Confirm the DT is correct and the modem is loadable (cheap checks first)

All four are one-grep answers, and each one can invalidate a plan before it
costs a build:

- `qcom,is-not-loadable` ABSENT from the mss node → `pil_mss_loadable_init()`
  runs and `drv->q6` is populated. Present would mean `is_not_loadable` and a
  completely different (no-firmware) path.
- `qcom,firmware-name = "modem"` → this is `desc->fw_name`, so the files are
  `modem.mdt` / `modem.bNN`.
- `qcom,pil-self-auth` PRESENT → requires an `IORESOURCE_MEM` named
  `rmb_base` in the node's `reg-names`. If it is missing,
  `pil_mss_loadable_init()` returns the error and PROBE FAILS before any
  firmware is ever read. Check this before anything else.
- `qcom,mba-image-is-not-elf` ABSENT → `non_elf_image` false
  (`pil-q6v5.c:764`) → the MBA filename is `mba.mbn`, not `mba.b00`.

## 3. Two firmware loads, in a fixed order — both mandatory

**(a) MBA, loaded FIRST** by `pil_mss_reset_load_mba()`
(`pil-msa.c:651`):

```
mba.mbn     REQUIRED  (hard fail: "Failed to locate %s")
msadp       optional  (dev_warn "Debug policy not present", continues)
```

`msadp` is the only genuinely optional file in the whole contract.

**(b) Modem image, loaded SECOND** by `pil_boot()`
(`peripheral-loader.c:1252`):

```
modem.mdt   REQUIRED   snprintf("%s.mdt", desc->fw_name)
modem.b00   REQUIRED
modem.b01   REQUIRED   ... through the highest segment
             (snprintf("%s.b%02d", desc->fw_name, num), peripheral-loader.c:1024)
```

The `.mdt` is the ELF header describing the segments; `.bNN` are the
payloads. **The full segment set is required** — an `.mdt` with no `.bNN`
will not boot, and a gap in the numbering is fatal. Do not cherry-pick a
subset. `qcom,sequential-fw-load` changes the ORDER in which the segments are
loaded and authenticated, not the file list.

Read the exact segment count out of the `.mdt` once it is on disk rather than
guessing the `.bNN` range.

NOT needed for the modem, despite the intuition:

```
wlanmdsp.mbn     WLAN FW is fetched by the Q6 over QMI; icnss.c has zero
                 request_firmware calls
bdwlan.*         icnss2 only (icnss2/qmi.c:40-46); CONFIG_ICNSS2 unset here
```

## 4. `qcom,pil-self-auth` swaps the whole reset-ops table

`pil-q6v5-mss.c:330-340` reads the property and replaces `q6_desc->ops`:

```
pil_msa_mss_ops            (pil-msa.c:1023)  .auth_and_reset = pil_mss_reset
pil_msa_mss_ops_selfauth   (pil-msa.c:1035)  + .init_image, .mem_setup,
                                              .verify_blob, .deinit_image,
                                              .auth_and_reset = pil_msa_mba_auth
```

The self-auth path authenticates the MBA blob through the `rmb_base` register
block by TrustZone (`pil_msa_mba_verify_blob()`, `pil-msa.c:951-975`, writes
RMB_PMI_CODE_START/LENGTH and reads RMB_MBA_STATUS). **If the TrustZone app on
this device rejects the blob, boot fails there and no kernel change fixes
it.** That is the single genuinely non-static question in the whole contract —
answerable only by a boot test. Everything else above is deterministic.

## 5. Order of work — firmware BEFORE any trigger patch

1. **Firmware on disk first.** An empty `/lib/firmware/` is a hard blocker:
   `pil_boot()` fails at `request_firmware()`, and `subsystem_powerup()`
   (`subsystem_restart.c:773`) then **panics** on powerup failure unless
   `dev->desc->ignore_ssr_failure` is set. A boot-trigger patch that runs
   before the firmware is in place therefore risks a panic, not a clean
   error. Rootfs is writable and should persist, but a reflash wipes
   `/lib/firmware/` — verify with `ls -la /lib/firmware/` after every reflash
   rather than trusting a staging note.
2. **Then a kernel patch exposing the boot trigger** — a writable sysfs attr
   or an `.unlocked_ioctl` on `subsys_device_fops`, calling
   `subsystem_get(name)` / `subsystem_put()`. Handle `ignore_ssr_failure` so a
   missing-firmware failure is a clean error.
3. **Only then the OpenWrt integration** — a procd service that calls it at
   boot so it survives reboot. This is the "userspace" work, and it does not
   exist until step 2 lands.

## 6. Getting the firmware out of a vendor image with no root

When the firmware must come from an Android vendor image and the host cannot
install `simg2img`/`unzip`/`file` (no root, no sudo), everything is doable in
pure stdlib Python:

- **sparse → raw:** `python3 scripts/simg2img.py in.sparse out.raw`. Handles
  RAW / FILL / DONTCARE / CRC32 chunk types; verified against a synthetic
  image carrying all four.
- **CRC32 chunk trap:** `total_sz` covers the 12-byte header AND the trailing
  4-byte CRC word, so the image payload is `total_sz - 12 - 4`. Do NOT derive
  it from `nblks * blk_sz - 4` — some encoders pad the chunk, and trusting
  `nblks` overruns the stream and silently produces a short image. The
  symptom is an output file a few bytes short with every content check
  passing, which is easy to dismiss as a rounding error.
- **zip archives:** `zipfile` handles them; confirm the archive layout rather
  than guessing member paths.
- **A/B devices:** settle whether the firmware lives in `vendor.img` or
  `super.img` before extracting — SDM660 wayne is usually plain `vendor.img`,
  but a full fastboot package may be dynamic-partitioned.
  **That assumption was wrong on wayne and cost a full session.** The upload
  was an OTA payload (`*.new.dat.br` + `*.patch.dat` + `*.transfer.list`),
  not a sparse image, and the resulting `vendor.img` contains NO modem
  firmware at all — it carries the cnss-daemon binary and the SELinux
  `file_contexts` but not `mba.mbn` / `modem.mdt` / `modem.bNN`. On
  sdm660/wayne those live in the **`modem` partition**, a VFAT filesystem
  mounted at `/vendor/firmware_mnt`. Learn the partition layout by scanning
  the vendor image for `by-name/<name>` (the `file_contexts` enumerates every
  partition) and ask for the `modem` partition image by name. The full
  pipeline, the `transfer.list` grammar, and the two verification gates are
  in `references/ota-payload-extraction.md`.

## 7. Reporting discipline

- "The subsystem is registered" and "the subsystem booted" are different
  claims; `/sys/class/subsys/subsys_modem` existing proves only the first.
- The chain from a dead peer to a missing interface is long and every link
  must be cited: no trigger → Q6 down → servloc `-ETIME` at exactly its 300 s
  timeout → no WLFW server → `wlfw_new_server()` never fires →
  `ICNSS_FW_READY` never set → `register_driver()` bails → `pld_snoc_probe`
  never runs → no wiphy → no `wlan0`.
- Grade the TrustZone question as unverifiable, not as unlikely. It is the
  one place a real Android-vs-OpenWrt wall can sit.

## 8. rmtfs: the daemon that must answer before the modem boots

`CONFIG_UIO_MSM_SHAREDMEM=y` binds `qcom,rmtfs_sharedmem@0`
(`compatible = "qcom,sharedmem-uio"`, `qcom,client-id = <1>`) to
`drivers/uio/msm_sharedmem/msm_sharedmem.c`, producing `/dev/uio*`. Nothing in
the kernel serves the modem's file requests over that device — that is rmtfs's
job, and on Android it is a vendor daemon that is not in this rootfs.

- **Check the node's base `reg` before assuming the UIO device exists.** A zero
  base is rejected outright: `msm_sharedmem.c:153` returns `-EINVAL` when
  `shared_mem_pyhsical == 0`, so `reg = <0x0 0x200000>` binds nothing and the
  daemon has no device to open. Derive a replacement region from the
  reserved-memory map — enumerate every sibling region's `reg`, find a
  provably free gap, and align it for `qcom,guard-memory` — never by inventing
  an address.
- **Boot order is rmtfs-then-modem, and it is mandatory.** Reversed, the MBA
  hand-off succeeds and the modem then stalls waiting for a shared-memory
  buffer that never arrives — a failure that looks like a firmware fault and
  sends the next session auditing the `.bNN` set instead of the daemon.

## 9. The data plane: QMI over QRTR, not MBIM

sdm660 carries the modem control plane over QRTR (glink `IPCRTR`, the
`qcom,modem_qrtr` node in `sdm660.dtsi`) and the data plane over rmnet + IPA
(`qcom,rmnet-ipa`). MBIM is a USB framing protocol and appears nowhere in this
tree.

- **`uqmi` is unusable here.** It speaks only `/dev/cdc-wdmX`, a USB WWAN
  control device this platform does not expose, so the familiar OpenWrt QMI
  client has nothing to open.
- The working stack is `libqmi` with QRTR transport (`qrtr-ns` +
  `qmi-proxy`), then hand `rmnet_data0` to netifd.
- So the userspace gap is three packages, not one: rmtfs, `qrtr-ns`,
  `qmi-proxy`. Naming all three up front stops a session from closing the
  milestone after shipping rmtfs alone.
