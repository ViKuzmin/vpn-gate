[Русский](README.md) | English

# VPN Gate

A wrapper for any Linux application that refuses to start unless a VPN is up. Useful for apps that must never run without a VPN (torrent clients, messengers, browsers, etc.) — the block happens at launch time instead of relying on you remembering to turn the VPN on yourself.

Works with any VPN client — WireGuard, Amnezia, OpenVPN, Tailscale, etc. — the check is based on the network interface name you configure.

There are two equally capable ways to manage it: a **CLI script** and a **GUI app** (GTK4/Adwaita). Both store settings in the same place on disk, so you can use either one, or switch between them freely.

## How it works

1. The installer locates the real application binary (`REAL_BIN`) and replaces the `~/.local/bin/<app>` command with its own wrapper.
2. On launch, the wrapper checks whether the configured VPN interface is up (`wg0` by default; optionally with a check that the default route actually goes through it).
3. If the VPN is down — a notification is shown, the event is logged, and the app **does not start** (`exit 126`).
4. If the VPN is up — the wrapper transparently hands off control to the real binary (`exec`), passing through all command-line arguments.
5. The app's `.desktop` file is replaced too, so launching from the menu/dock also goes through the gate.

Everything the installer generates is plain bash with no external dependencies, so the launch-time check itself is instant and doesn't pull in Python/GTK.

## Requirements

- Linux with systemd/XDG paths (`~/.local/bin`, `~/.local/share/applications`, `~/.config`)
- bash, `ip` (the `iproute2` package) — for the VPN check
- For the GUI: `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1` (already present on most modern GNOME distros)

## Installation — .deb (Debian/Ubuntu)

```bash
sudo apt install dpkg-dev   # if not already installed
packaging/build-deb.sh
sudo apt install ./packaging/build/vpn-gate_*.deb
```

The package installs `vpn-gate-install` and `vpn-gate-ui` into `/usr/bin`, registers the GUI in the system menu, and pulls in all dependencies (`python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`). To remove: `sudo apt remove vpn-gate`.

## Setting up protection — CLI

From the repo — `./install-vpn-gate.sh`; after installing the `.deb` — the `vpn-gate-install` command (same thing, just a different path).

```bash
# Auto-detect the binary in PATH
./install-vpn-gate.sh telegram-desktop

# Point to the binary explicitly
REAL_BIN=/opt/myapp/bin/myapp ./install-vpn-gate.sh myapp

# Set the VPN interfaces (space-separated), if not wg0 — e.g. amn0 for Amnezia
VPN_IFACES="wg0 amn0" ./install-vpn-gate.sh myapp

# Remove protection
./install-vpn-gate.sh --uninstall myapp

# Remove protection and the app's config
./install-vpn-gate.sh --uninstall myapp --purge
```

## Setting up protection — GUI

```bash
./vpn-gate-ui        # from the repo
vpn-gate-ui           # after installing the .deb, or from the app menu
```

In the window:

- VPN status with auto-refresh and a manual check button;
- a list of protected apps with quick edit/remove;
- **+ Add application** — set up protection, with name autocomplete from `PATH` and a file picker for the binary;
- **Block log** — history of launch attempts made without VPN;
- **Settings** — default interfaces and strict-route mode, notifications, autostart.

After the first run, the app registers itself in the system menu ("VPN Gate").

## Configuration

Each protected app gets its own directory: `~/.config/<app>-vpn-gate/`:

| File | Purpose |
|---|---|
| `real-bin` | path to the real binary |
| `config` | `VPN_IFACES` (space-separated interfaces) and `VPN_STRICT_ROUTE` (0/1 — require a route through the VPN) |

The launch-block log is shared across all apps: `~/.local/state/vpn-gate/events.log` (auto-trimmed, keeps the last ~300 events).

## Repository layout

```
install-vpn-gate.sh       CLI installer (bash, no dependencies)
vpn-gate-ui               GUI app launcher
vpn_gate_ui/              GUI sources (GTK4 + libadwaita)
├── core.py                install/uninstall/list/config business logic
├── vpncheck.py             VPN status check
├── settings.py             UI settings, autostart
├── window.py                main window
├── dialogs.py                dialogs (add/edit/settings/log)
├── sizing.py                  screen-aware adaptive window sizing
└── app.py                     entry point (single-instance)
packaging/                .deb build
├── build-deb.sh            builds the package from the current sources
└── debian/                 control/postinst/postrm/copyright/changelog/.desktop
```

## License

[MIT](LICENSE) — use it, fork it, change it however you like.
