# Reverted session edits + open items

Current state = **pristine repo (client/proto at HEAD)** + these **kept** changes only:

- `Dockerfile` — pre-session two-stage refactor plus `mkdir -p libs` in stage 1 (the pristine client Makefile doesn't create `libs/` itself). The `FROM` line now points at our **custom z88dk image** (see below).
- `docker/z88dk.Dockerfile` + `.github/workflows/z88dk-image.yml` — new. Rebuilds z88dk from `master` HEAD on 2022-02-17 (the date the known-working `desertkun/channels-hub:latest` binary was compiled) and publishes to `ghcr.io/<owner>/channels-z88dk:2022-02-17`. Cutoff date can be overridden via workflow_dispatch input.
- `push.sh` + `.spectrum-ip` — local dev tool: build + extract + ethup-push the client binary to a networked Spectranet.

## What the user needs to do

1. Commit + push these changes.
2. GitHub → **Actions → "Build z88dk base image"** → "Run workflow" (manual dispatch). Takes ~8–15 min.
3. GitHub → **Packages → channels-z88dk** → Package settings → **Change visibility: public** (so `push.sh` on local dev machines can `docker pull` without auth).
4. `./push.sh <spectrum-ip>` — will now use the published image.

## Deferred — re-add one at a time once the pristine build is confirmed working

Keep each change on a branch/commit of its own so we can bisect if regressions return.

1. **`Makefile` hygiene fixes** (safe; not the regression):
   - `JUST_PRINT := $(findstring n,$(firstword $(MAKEFLAGS)))` — otherwise any 'n' in any variable override trips dry-run mode.
   - `libs:` target with order-only prerequisite on lib-producing rules — so `make` works from a clean checkout without the Dockerfile `mkdir -p libs` hack. Reverting the hack in `Dockerfile` becomes trivial once this lands.

2. **`client/arch/zx/zxgui_tiles.c` tile rename** (`static uchar tiles[]` inside function → file scope, renamed to `gui_tiles_data`) — only necessary on newer z88dk; may not be needed with the Feb-2022 toolchain. Re-verify before re-adding.

3. **CHANNELS_HOST bake-in** (`Makefile` generated header + `main.c` fallback + `Dockerfile` ARG + CI `build-args` + `push.sh` default).

4. **Topics-crash mitigations** (`proto/channels_proto.c` 128 → 512 static buffer, `thread_view.c` comment-blob size clamp, threads-count buffer clamp). Re-verify whether the topics-fetch crash still reproduces against a known-working baseline before re-adding.

5. **netlog debug instrumentation** — stays reverted. Spectranet's `sendto`/`recv` page the W5100 SRAM into slot PAGE_B (0x2000), which overlaps `proto_process_t`; any socket op between accesses to `process_proto->…` reads garbage. If we ever need netlog in the proto hot path, call `setpageb(0xC0)` after each socket call.
