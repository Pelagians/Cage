# syntax=docker/dockerfile:1.7
# Universal Cage UMU + GE-Proton image: build, headless, and Selkies session modes.
ARG GE_PROTON_TAG=GE-Proton11-1
ARG UMU_LAUNCHER_VERSION=1.4.0

FROM ghcr.io/pelagians/pelagian-shell@sha256:5ad8e46d11bac94a5f7202c0f4cee5872f2f731b8602bac42329d42717d65122
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

ENV PELAGIAN_SHELL_PROFILE=legacy-apps \
    CAGE_ROOT=/opt/cage \
    WINEPREFIX=/opt/cage/prefix \
    STEAM_COMPAT_DATA_PATH=/opt/cage/prefix \
    STEAM_COMPAT_CLIENT_INSTALL_PATH=/opt/cage \
    PROTONPATH=/opt/proton-ge \
    WINEDEBUG=-all \
    CAGE_WINE_GRAPHICS=xwayland

LABEL org.pelagian.cage.session-contract="cage.selkies-wayland/v1" \
    io.pelagians.cage.pelagian-shell-image="ghcr.io/pelagians/pelagian-shell@sha256:5ad8e46d11bac94a5f7202c0f4cee5872f2f731b8602bac42329d42717d65122"

COPY container/selkies/root/ /
COPY container/common/wine-env.sh /opt/cage/common/wine-env.sh
COPY runtime/pixelflux.py /usr/local/bin/cage-pixelflux
RUN set -eux; \
    chmod 0755 /usr/local/bin/pelagian-shell-consumer \
      /custom-cont-init.d/10-cage-session \
      /etc/s6-overlay/s6-rc.d/svc-cage-shutdown/run \
    /etc/s6-overlay/s6-rc.d/svc-cage-task/run \
      /usr/local/libexec/cage-select-wine-graphics \
      /usr/local/bin/cage-pixelflux; \
    bash -n /usr/local/bin/pelagian-shell-consumer; \
    bash -n /custom-cont-init.d/10-cage-session; \
    bash -n /usr/local/libexec/cage-select-wine-graphics; \
    python3 -m py_compile /usr/local/bin/cage-pixelflux; \
    pelagian-shellctl status >/dev/null; \
    pelagian-layoutd status >/dev/null; \
    test -x /opt/proton-ge/files/bin/wine; \
    if test -f /opt/proton-ge/files/lib64/wine/x86_64-unix/winex11.so; then \
      :; \
    else \
      test -f /opt/proton-ge/files/lib/wine/x86_64-unix/winex11.so; \
    fi

WORKDIR /opt/cage
