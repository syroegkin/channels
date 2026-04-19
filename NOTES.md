# Session progress + deferred items

## Current state (all confirmed working on real hardware)

- **z88dk toolchain pin** via dedicated image: `ghcr.io/syroegkin/channels-z88dk:2022-02-17`, produced by `.github/workflows/z88dk-image.yml` + `docker/z88dk.Dockerfile`. z88dk built from `master` HEAD on 2022-02-17. Newer z88dk releases produce a broken ZX client — root cause of the UI and connect/recv regressions chased earlier in the session.
- **`Dockerfile`** — multi-stage; stage 1 pulls the z88dk image above, stage 2 is the hub runtime. No `mkdir -p libs` hack (see Makefile change).
- **`Makefile` hygiene**
  - `JUST_PRINT := $(findstring n,$(firstword $(MAKEFLAGS)))` — avoids tripping dry-run mode when a command-line variable value contains the letter 'n'.
  - `libs:` target with order-only prerequisite on lib-producing rules — clean checkout builds without external `mkdir`.
- **CHANNELS_HOST bake-in** — `Makefile` `CHANNELS_HOST ?=` var + generated `src/channels_default_host.h`, `main.c` fallback `strcpy` when cartridge mount path is empty, `Dockerfile` `ARG CHANNELS_HOST=tnfs://channels.zx.in.net`, `ci.yml` `build-args`, `push.sh` default `tnfs://104.197.16.212`.
- **Proto object buffer** — `proto/channels_proto.c`: `uint8_t object_buffer[128]` → `static uint8_t object_buffer[512]` using `sizeof(object_buffer)` instead of the literal. Needed for larger boards/topics objects from the real hub.
- **Board-count overflow guard** — `client/src/channel_view.c` `process_board`: bail out when `scene_objects->board.buffer_offset + needed > SPECTRANET_BLOB_SIZE`. Without this, the 1024-byte heap blob overflows for channels with many boards (endchan returns ~128), corrupts adjacent Spectranet-paged memory (PROTO_PAGE), and trips a downstream `proto_assert` = red border stripes.

## Skipped / not needed on this toolchain

- **`arch/zx/zxgui_tiles.c` tile rename** — originally added to fix UI garbling on the newer z88dk (20260406). With the Feb-2022 z88dk the UI renders correctly without it. Kept out.

## Deferred — known issues to address later

- **thread_view.c clamps** (from the earlier "topics crash" mitigation set): comment-blob size clamp to `SPECTRANET_BLOB_SIZE - 1`, threads-count buffer clamp + null-terminator reorder. Re-evaluate once the actual failure mode is observed on the correct toolchain.
- **Other user-reported issues** noted post-boards-fix — "still some issues left"; details TBD.

## Tools / dev loop

- `push.sh <spectrum-ip>` — builds the client, extracts `bin/channels__.bin`, ethup-pushes to a networked Spectranet at address 25000. Caches IP in `.spectrum-ip` (gitignored).
- ethup source: `spectranet/devtools/ethup` (build from the spectrumero/spectranet repo clone next to this one).

## netlog caveat

Spectranet's UDP `sendto` and TCP `recv` temporarily page the W5100 SRAM into slot PAGE_B (0x2000), which overlaps `proto_process_t`. Any socket op between accesses to `process_proto->…` reads garbage unless you `setpageb(0xC0)` after each. If netlog is ever re-added to the proto hot path, restore PAGE_B explicitly.
