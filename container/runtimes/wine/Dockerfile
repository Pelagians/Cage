# syntax=docker/dockerfile:1.7
# Universal Cage Wine Stable image: build, headless, and Selkies session modes.
ARG SELKIES_BASE_IMAGE=ghcr.io/linuxserver/baseimage-selkies:debiantrixie@sha256:ac7fd6d182238b4a99e66554c5e75be48a714e2a0c9da81bd18e171ff9ba3dd5
ARG WINE_PACKAGE_VERSION=11.0.0.0~trixie-1
FROM ${SELKIES_BASE_IMAGE}
ARG WINE_PACKAGE_VERSION
ARG WINETRICKS_COMMIT=5a59ea07513b24093bd90fad943ecf9543cf05bc
ARG WINETRICKS_SHA256=f35c29737ca08a583569e6a3752d52fbe23333c5acfad5f16c4177d25eaf3f4b
RUN set -eux; \
    dpkg --add-architecture i386; \
    apt-get update -o Acquire::Retries=5; \
    apt-get install --no-install-recommends -y ca-certificates curl gnupg cabextract p7zip-full unzip bzip2 xz-utils fontconfig python3; \
    install -d -m 0755 /etc/apt/keyrings; \
    curl -fsSL https://dl.winehq.org/wine-builds/winehq.key | gpg --dearmor -o /etc/apt/keyrings/winehq-archive.key; \
    curl -fsSL https://dl.winehq.org/wine-builds/debian/dists/trixie/winehq-trixie.sources -o /etc/apt/sources.list.d/winehq.sources; \
    apt-get update -o Acquire::Retries=5; \
    apt-get install --no-install-recommends -y \
      "winehq-stable=${WINE_PACKAGE_VERSION}" \
      "wine-stable=${WINE_PACKAGE_VERSION}" \
      "wine-stable-amd64=${WINE_PACKAGE_VERSION}" \
      "wine-stable-i386:i386=${WINE_PACKAGE_VERSION}"; \
    curl -fsSL "https://raw.githubusercontent.com/Winetricks/winetricks/${WINETRICKS_COMMIT}/src/winetricks" -o /usr/local/bin/winetricks; \
    printf '%s  %s\n' "${WINETRICKS_SHA256}" /usr/local/bin/winetricks | sha256sum -c -; \
    chmod 0755 /usr/local/bin/winetricks; \
    wine --version; winetricks --version
ENV CAGE_ROOT=/opt/cage \
    WINEPREFIX=/opt/cage/prefix \
    WINEARCH=win64 \
    WINEDEBUG=-all \
    START_DOCKER=false \
    PIXELFLUX_WAYLAND=true \
    RESTART_APP=false \
    CAGE_WINE_GRAPHICS=xwayland \
    PATH=/lsiopy/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

COPY container/selkies/root/ /
COPY container/common/wine-env.sh /opt/cage/common/wine-env.sh
COPY runtime/pixelflux.py /usr/local/bin/cage-pixelflux
RUN set -eux; \
    chmod 0755 /defaults/autostart_wayland \
      /custom-cont-init.d/10-cage-session \
      /usr/local/libexec/cage-select-wine-graphics \
      /usr/local/bin/cage-pixelflux; \
    bash -n /defaults/autostart_wayland; \
    bash -n /custom-cont-init.d/10-cage-session; \
    bash -n /usr/local/libexec/cage-select-wine-graphics; \
    python3 -m py_compile /usr/local/bin/cage-pixelflux; \
    test -x /lsiopy/bin/selkies; \
    test -f /defaults/labwc.xml; \
    find /opt /usr/lib -name winewayland.so -print -quit | grep -q .; \
    find /opt /usr/lib -name winex11.so -print -quit | grep -q .; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /opt/cage
EXPOSE 3001
