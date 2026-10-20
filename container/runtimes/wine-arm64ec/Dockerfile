# syntax=docker/dockerfile:1.7
FROM registry.fedoraproject.org/fedora@sha256:d458dbabce9d9400db66c046ec07bec6b75759f85ea737b1e3235ef2b702f036
ARG WINE_VERSION=11.20
ARG RUNTIME_LOCK_SHA256
RUN test "$(uname -m)" = aarch64 && test "$WINE_VERSION" = 11.20 && \
    dnf -y --setopt=install_weak_deps=False install python3 xorg-x11-server-Xvfb shadow-utils findutils procps-ng dejavu-sans-fonts && \
    dnf clean all
COPY runtime/__init__.py runtime/arm64ec.py runtime/desktop_launch.py runtime/wine-arm64ec-11.20-fex-2610.json /usr/lib/cage-runtime/runtime/
RUN --mount=type=cache,target=/tmp/cage-arm-rpms PYTHONPATH=/usr/lib/cage-runtime python3 -m runtime.arm64ec --container-install && \
    PYTHONPATH=/usr/lib/cage-runtime python3 -c 'from runtime.arm64ec import runtime_target; from runtime.desktop_launch import digest_json; import os; assert digest_json(runtime_target()) == os.environ["RUNTIME_LOCK_SHA256"]' && \
    wine --version && dnf clean all
COPY container/runtimes/wine-arm64ec/entrypoint.py /usr/local/bin/cage-native-init
COPY container/common/wine-env.sh /opt/cage/common/wine-env.sh
RUN chmod 0755 /usr/local/bin/cage-native-init && \
    mkdir -p /usr/local/libexec && \
    printf '#!/bin/sh\n[ "${CAGE_WINE_GRAPHICS:-xwayland}" = xwayland ]\n' > /usr/local/libexec/cage-select-wine-graphics && \
    chmod 0755 /usr/local/libexec/cage-select-wine-graphics && \
    mkdir -p /opt/cage /var/lib/cage/state /exports
LABEL org.pelagian.cage.session-contract="cage.native-wine/v1" \
      io.cage.runtime.target-sha256="${RUNTIME_LOCK_SHA256}"
ENV WINEARCH=win64 WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml=;winemenubuilder.exe=d" \
    CAGE_WINE_GRAPHICS=xwayland
WORKDIR /opt/cage
ENTRYPOINT ["/usr/local/bin/cage-native-init"]
