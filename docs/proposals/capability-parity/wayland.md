# Native Wine Wayland candidate

The v1 recipe can explicitly select native Wayland for the pinned native x86_64
Wine 11.0 candidate. X11/XWayland remains the existing default. Other Wine
providers/versions report the Wayland request unsupported; a version string is
not proof that a distributor included the driver. Desktop packaging and payload
startup inspect the actual selected Wine driver modules before prefix setup.

Use both existing fields together:

```yaml
runtime:
  provider: wine
  version: '11.0'
  wineGraphics: wayland
permissions:
  requests:
    - id: window
      kind: display
      backend: wayland
      required: true
      reason: Open a native Wayland window
```

The other required application/permission fields are unchanged. An incompatible
or unavailable backend refuses rather than automatically granting X11 access.
V0 display behavior and existing X11 runtime identities remain unchanged.

Flatpak emits `--socket=wayland`; Flatseal sees the native permission. Effective
native X11 or other unexpected socket grants refuse managed launch and remain
untouched. OCI and AppImage bind only the selected owned compositor socket into
a private runtime directory, never the whole host `XDG_RUNTIME_DIR`. Socket
identity is rechecked before launching. Inherited X11 variables and the
inherited-socket descriptor mechanism are excluded from native Wayland execution.
AppImage includes the Wayland/xkb libraries in its immutable private closure.

Wayland has its own graphics/runtime identity. Changing an existing X11
installation to Wayland is a state-affecting transition: existing prefixes and
recovery runtimes are retained, and an unqualified transition refuses. Initially
use a fresh application ID/state. There is no implicit prefix migration or
native permission rewrite.

## Evidence boundaries

The `runtime-wayland` x86_64 CI job builds real OCI, Flatpak and AppImage exports,
then runs the existing filesystem/network/device-denial/rebinding and prefix
preservation probes using headless Weston with its software renderer. Build-time
Wine setup retains its disposable Xvfb path; application execution gets no X11
filesystem socket binding, cookie or display environment. A separately accepted
shared-network grant retains its documented IP/abstract-socket scope; display
selection does not narrow that independent permission. The Windows process must report that
`winewayland.drv` is loaded and `winex11.drv` is absent. Its protocol log must show
the named Wayland surface and buffer attachment; a native child separately
checks that X11 sockets/environment are absent and the granted runtime directory
is owned by the application user with mode 0700. OCI uses Podman's tmpfs-specific
ownership handling; it does not change ownership of any bound host path. All existing normal-exit,
isolation, state-counter and retained-recovery assertions remain mandatory.

Adding the job is not a qualification pass. Read the exact commit's
`v1-actual-wayland-parity-*` artifact. Source tests, native compositor behavior,
signed installed-release lifecycle and real application compatibility are
separate gates. The signed installed-release harness remains X11-only in this
stage; Wayland release signing additionally requires matching host/display
evidence and cannot consume the earlier X11 proof. Input/clipboard, GPU/3D,
physical compositor/monitor behavior, ARM/Asahi, MyHarmony login and physical USB
synchronization remain unqualified by this probe.

The original intermittent ARM AppImage shutdown failure remains unresolved and
its failed result is retained; native Wayland work does not relabel that trial.
