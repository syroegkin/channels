# ---------------------------------------------------------------------------
# Stage 1: build the ZX Spectrum client using a pre-built z88dk toolchain.
# Avoids the ~8-minute z88dk-from-source compile on every cold build.
# ---------------------------------------------------------------------------
# z88dk publishes weekly date-tagged images; pin to a specific one for
# reproducibility. Bump when needed.
FROM z88dk/z88dk:20260406 AS client-builder

# z88dk image is Alpine-based without perl or make; the client Makefile and
# spectranet submake both need them. Also symlink /opt/z88dk to the
# /usr/local/share/z88dk path the client Makefile hard-codes.
RUN apk add --no-cache make perl \
    && mkdir -p /usr/local/share && ln -s /opt/z88dk /usr/local/share/z88dk

RUN mkdir -p /channels/tnfsd
ADD proto /channels/proto
ADD client /channels/client

WORKDIR /channels/client
RUN make && cp boot/boot.zx /channels/tnfsd && cp bin/channels /channels/tnfsd

# ---------------------------------------------------------------------------
# Stage 2: hub + runtime. Pulls the client artifacts from stage 1.
# ---------------------------------------------------------------------------
FROM alpine:3

RUN apk update && apk add --no-cache cmake git build-base python3 py3-pip python3-dev py3-setuptools \
    libxml2 libxml2-dev m4 perl

RUN mkdir -p /channels/hub/bin/cache /channels/tnfsd

COPY --from=client-builder /channels/tnfsd/boot.zx   /channels/tnfsd/boot.zx
COPY --from=client-builder /channels/tnfsd/channels  /channels/tnfsd/channels
RUN chmod 0444 -R /channels/tnfsd

ADD proto /channels/proto

# hub
ADD hub/configurations /channels/hub/configurations
ADD hub/tnfsd /channels/hub/tnfsd
# The hub/pybind11 submodule is pinned to a 2021-era commit that predates
# Python 3.12's opaque PyFrameObject and fails to compile against the alpine:3
# python3 (3.12). Override it with a modern release here. Once the submodule
# itself is bumped upstream this whole clone can go back to `ADD`.
RUN git clone --depth 1 --branch v2.13.6 https://github.com/pybind/pybind11.git /channels/hub/pybind11
ADD hub/img2spec /channels/hub/img2spec
ADD hub/src /channels/hub/src
ADD hub/CMakeLists.txt /channels/hub
RUN mkdir /build
WORKDIR /channels/hub/tnfsd
RUN make OS=LINUX TARGET_DIR=/channels/tnfsd
WORKDIR /build
# CMAKE_POLICY_VERSION_MINIMUM=3.5 — the pinned pybind11 submodule predates
# CMake's removal of pre-3.5 compat and its `cmake_minimum_required` trips
# modern CMake; this flag forces the old policies.
RUN cmake -DCMAKE_BUILD_TYPE=Release -DSKIP_PACKAGE_DEVELOP=ON -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    -S /channels/hub -B /build && make

# hub packages
# pip install instead of `python3 setup.py install` — the latter doesn't
# resolve install_requires (requests, beautifulsoup4) in modern setuptools.
# --break-system-packages needed because Alpine's Python 3.12 is PEP 668
# externally-managed; this is a container so it's fine.
ADD hub/channels /channels-packages
WORKDIR /channels-packages
RUN pip3 install --break-system-packages --no-cache-dir .

WORKDIR /channels/hub/bin
ADD docker/start.sh /start.sh
EXPOSE 9493
EXPOSE 16384/udp
ENTRYPOINT ["/bin/sh", "/start.sh"]
