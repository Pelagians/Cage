# syntax=docker/dockerfile:1.7
# Universal Cage Wine Staging image: build, headless, and Selkies session modes.
ARG PELAGIAN_SHELL_IMAGE=ghcr.io/pelagians/pelagian-shell@sha256:286b429c20b2515d35f8021112df32808b3cdd7e02e10c43154282412305e3cf
ARG WINE_PACKAGE_VERSION=11.10~trixie-1
FROM ${PELAGIAN_SHELL_IMAGE}
ARG PELAGIAN_SHELL_IMAGE
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
      "winehq-staging=${WINE_PACKAGE_VERSION}" \
      "wine-staging=${WINE_PACKAGE_VERSION}" \
      "wine-staging-amd64=${WINE_PACKAGE_VERSION}" \
      "wine-staging-i386:i386=${WINE_PACKAGE_VERSION}"; \
    curl -fsSL "https://raw.githubusercontent.com/Winetricks/winetricks/${WINETRICKS_COMMIT}/src/winetricks" -o /usr/local/bin/winetricks; \
    printf '%s  %s\n' "${WINETRICKS_SHA256}" /usr/local/bin/winetricks | sha256sum -c -; \
    chmod 0755 /usr/local/bin/winetricks; \
    wine --version; winetricks --version
ENV CAGE_ROOT=/opt/cage \
    WINEPREFIX=/opt/cage/prefix \
    WINEARCH=win64 \
    WINEDEBUG=-all \
    CAGE_WINE_GRAPHICS=xwayland \
    PATH=/lsiopy/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

LABEL org.pelagian.cage.session-contract="cage.selkies-wayland/v1" \
    io.pelagians.cage.pelagian-shell-image="${PELAGIAN_SHELL_IMAGE}"

COPY container/selkies/root/ /
COPY container/selkies/root/defaults/autostart /defaults/autostart_wayland
COPY container/common/wine-env.sh /opt/cage/common/wine-env.sh
COPY runtime/pixelflux.py /usr/local/bin/cage-pixelflux
RUN set -eux; \
    chmod 0755 /defaults/autostart /defaults/autostart_wayland \
      /custom-cont-init.d/10-cage-session \
      /etc/s6-overlay/s6-rc.d/svc-cage-shutdown/run \
    /etc/s6-overlay/s6-rc.d/svc-cage-task/run \
      /usr/local/libexec/cage-select-wine-graphics \
      /usr/local/bin/cage-pixelflux; \
    bash -n /defaults/autostart; \
    bash -n /defaults/autostart_wayland; \
    bash -n /custom-cont-init.d/10-cage-session; \
    bash -n /usr/local/libexec/cage-select-wine-graphics; \
    python3 -m py_compile /usr/local/bin/cage-pixelflux; \
    test -x /lsiopy/bin/selkies; \
    test -f /defaults/labwc.xml; \
    pelagian-shellctl status >/dev/null; \
    pelagian-layoutd status >/dev/null; \
    find /opt /usr/lib -name winewayland.so -print -quit | grep -q .; \
    find /opt /usr/lib -name winex11.so -print -quit | grep -q .; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /opt/cage
EXPOSE 3001
