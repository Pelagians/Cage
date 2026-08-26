# syntax=docker/dockerfile:1.7
# Universal Cage UMU + GE-Proton image: build, headless, and Selkies session modes.
ARG SELKIES_BASE_IMAGE=ghcr.io/linuxserver/baseimage-selkies:debiantrixie@sha256:ac7fd6d182238b4a99e66554c5e75be48a714e2a0c9da81bd18e171ff9ba3dd5
ARG GE_PROTON_TAG=GE-Proton11-1
ARG UMU_LAUNCHER_VERSION=1.4.0

FROM ${SELKIES_BASE_IMAGE}
ARG GE_PROTON_TAG
ARG UMU_LAUNCHER_VERSION
ARG UMU_DEB_SHA256=3de80fdcffdc5daabd65e7c9567aff4b8beeecc238eae11529fe737c0b4083f7

RUN set -eux; \
    case "${GE_PROTON_TAG}" in \
      GE-Proton11-1) GE_DIGEST=ce6dd663ea01725a31805ed5c165723a253cdf0945a6642907330742ae2de5e4; GE_ALGO=sha256sum ;; \
      GE-Proton10-34) GE_DIGEST=51c580b66a833c73998fe00f0717eeac57197654040a2f2ed5189e3ee68d773d; GE_ALGO=sha256sum ;; \
      GE-Proton9-27) GE_DIGEST=86a2b2962a2509104201b3532bc829d058d666bc8220417f71bd4af660b6d05781e9f684b3982339d695a5fd4babe19e97ec42a82a78311faf99fc1257280623; GE_ALGO=sha512sum ;; \
      *) echo "Unsupported unpinned GE-Proton release: ${GE_PROTON_TAG}" >&2; exit 2 ;; \
    esac; \
    dpkg --add-architecture i386; \
    apt-get update -o Acquire::Retries=5; \
    apt-get install --no-install-recommends -y \
      ca-certificates curl cabextract p7zip-full unzip bzip2 xz-utils fontconfig python3; \
    curl -fsSL -o /tmp/proton-ge.tar.gz \
      "https://github.com/GloriousEggroll/proton-ge-custom/releases/download/${GE_PROTON_TAG}/${GE_PROTON_TAG}.tar.gz"; \
    printf '%s  %s\n' "${GE_DIGEST}" /tmp/proton-ge.tar.gz | "${GE_ALGO}" -c -; \
    install -d -m 0755 /opt/proton-ge; \
    tar -xzf /tmp/proton-ge.tar.gz -C /opt/proton-ge --strip-components=1; \
    curl -fsSL -o /tmp/umu.deb \
      "https://github.com/Open-Wine-Components/umu-launcher/releases/download/${UMU_LAUNCHER_VERSION}/python3-umu-launcher_${UMU_LAUNCHER_VERSION}-1_amd64_debian-13.deb"; \
    printf '%s  %s\n' "${UMU_DEB_SHA256}" /tmp/umu.deb | sha256sum -c -; \
    apt-get install --no-install-recommends -y /tmp/umu.deb; \
    command -v umu-run; \
    /usr/bin/umu-run --help >/tmp/umu-run-help.txt; \
    rm -rf /tmp/proton-ge.tar.gz /tmp/umu.deb /var/lib/apt/lists/*

ENV CAGE_ROOT=/opt/cage \
    WINEPREFIX=/opt/cage/prefix \
    STEAM_COMPAT_DATA_PATH=/opt/cage/prefix \
    STEAM_COMPAT_CLIENT_INSTALL_PATH=/opt/cage \
    PROTONPATH=/opt/proton-ge \
    WINEDEBUG=-all \
    START_DOCKER=false \
    PIXELFLUX_WAYLAND=true \
    RESTART_APP=false \
    CAGE_WINE_GRAPHICS=xwayland \
    PATH=/lsiopy/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

LABEL org.pelagian.cage.session-contract="cage.selkies-wayland/v1"

COPY container/selkies/root/ /
COPY container/common/wine-env.sh /opt/cage/common/wine-env.sh
COPY runtime/pixelflux.py /usr/local/bin/cage-pixelflux
RUN set -eux; \
    chmod 0755 /defaults/autostart_wayland \
      /custom-cont-init.d/10-cage-session \
      /custom-services.d/cage-shutdown \
      /usr/local/libexec/cage-select-wine-graphics \
      /usr/local/bin/cage-pixelflux; \
    bash -n /defaults/autostart_wayland; \
    bash -n /custom-cont-init.d/10-cage-session; \
    bash -n /usr/local/libexec/cage-select-wine-graphics; \
    python3 -m py_compile /usr/local/bin/cage-pixelflux; \
    test -x /lsiopy/bin/selkies; \
    test -f /defaults/labwc.xml; \
    test -x /opt/proton-ge/files/bin/wine; \
    if test -f /opt/proton-ge/files/lib64/wine/x86_64-unix/winex11.so; then \
      :; \
    else \
      test -f /opt/proton-ge/files/lib/wine/x86_64-unix/winex11.so; \
    fi

WORKDIR /opt/cage
EXPOSE 3001
