# z88dk toolchain image, pinned to the commit that was HEAD on 2022-02-17.
# That date matches the known-working desertkun/channels-hub binary; using
# a newer z88dk produces subtly broken ZX code for this client.
#
# Build args let you bump the cutoff without rewriting the recipe.

FROM alpine:3.15 AS build

ARG Z88DK_BEFORE=2022-02-18

RUN apk add --no-cache git build-base make perl gcc g++ libxml2-dev m4 bison flex ragel re2c texinfo bash ca-certificates

RUN git clone --recursive https://github.com/z88dk/z88dk.git /z88dk \
    && cd /z88dk \
    && HASH=$(git rev-list -n 1 --before="$Z88DK_BEFORE" master) \
    && echo "Using z88dk commit $HASH" \
    && git checkout "$HASH" \
    && git submodule update --init --recursive \
    && chmod +x build.sh \
    && ./build.sh -p zx \
    && make install \
    && echo "$HASH" > /usr/local/share/z88dk/COMMIT

# ---------------------------------------------------------------------------
# Runtime image — just z88dk, no build toolchain.
# The main project Dockerfile runs `make` here so needs make + perl + gcc
# (spectranet submake compiles a C tool) + bash.
# ---------------------------------------------------------------------------
FROM alpine:3.15

RUN apk add --no-cache make perl gcc musl-dev bash

COPY --from=build /usr/local/bin/z88dk-* /usr/local/bin/
COPY --from=build /usr/local/bin/zcc     /usr/local/bin/zcc
COPY --from=build /usr/local/share/z88dk /usr/local/share/z88dk

# The spectranet submake calls `z80asm`, `z80nm`, etc. unprefixed. z88dk's
# `make install` only places `z88dk-*` — create shim symlinks so those
# invocations resolve.
RUN for f in /usr/local/bin/z88dk-*; do \
        name="${f##*/z88dk-}" ; \
        ln -sf "$f" "/usr/local/bin/$name" ; \
    done

ENV ZCCCFG=/usr/local/share/z88dk/lib/config
ENV PATH="/usr/local/bin:${PATH}"

LABEL org.opencontainers.image.source="https://github.com/z88dk/z88dk"
LABEL org.opencontainers.image.description="z88dk pinned to master HEAD on 2022-02-17, for the Channels ZX Spectrum client"
