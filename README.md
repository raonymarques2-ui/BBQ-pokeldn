# Union Circle BBQ Host — PokeLDN plugin

This plugin adds **Union Circle BBQ Host** to PokeLDN's Scarlet/Violet tools.
It hosts a local Union Circle through the ESP32 and generates a stationary,
generic host world. The physical Switch joins as a client. No emulator, PC game
process, PC save, memory editor or private session reference is needed.

## Download

[Download the experimental Android adaptation (0.1.2)](dist/union-circle-bbq-0.1.2.pokeplugin).
Choose the raw/download button on GitHub, then install the file in PokeLDN Plugins.
Windows 0.1.1 was confirmed working; the 0.1.2 Android adaptation still needs a physical-device test.

## Requirements and installation

- PokeLDN plugin API **1.8 or compatible**, with the SV host/transport interfaces
  required by this adapter. Releases 0.29.1, 0.31.1 and 0.31.2 were inspected.
  **There is no version-number allowlist.** Later releases can start when the
  required API/source contracts and offline wire-format checks pass. Before
  opening the radio, the plugin checks host options/symbols, transport methods
  and state, compression, reliable delivery/ordering, channel registration,
  session departure and Pia packet framing. Failed checks report the incompatible
  capability. Passing this preflight is not a guarantee of compatibility with
  every future internal refactor or a substitute for a physical game test.
- A compatible ESP32 and working PokeLDN radio setup. Firmware 1.6.1 on a USB
  ESP32 was used for the existing physical tests. Do not run Eden or another
  host against the same board at the same time.
- Your own local keys file configured in **PokeLDN Settings**. Keys are not
  included. The plugin receives the configured path through PokeLDN's standard
  keys argument. It never uploads keys.
- One physical Switch running a compatible Scarlet/Violet version with the
  Terarium and BBQs unlocked. The Switch needs its own game and save progress;
  the PC does not need a game save. Local wireless mode is required.

Open **Plugins → Add a plugin**, select the `.pokeplugin` file and review the
native installation screen. Enable the plugin, then select its Scarlet/Violet
tool. Choose your ESP32/port in PokeLDN's existing board controls. No separate
serial selector or keys store is maintained by this plugin.

## Running

1. Set **Target BP earned**, for example 1000. This is new BP during this run,
   starting from zero, not your console's total balance.
2. The local group code is always **4970**. There is no code input or override
   in the plugin's interface or entry-point parser.
3. The tool follows **PokeLDN's application language**, including its field
   labels, instructions and status cards. There is no separate language option.
   English and Portuguese text is included; selected language packs can supply
   `plugins.union_circle_bbq.*` translations. Missing translations use English,
   following PokeLDN's fallback behavior. This documentation remains in English.
4. Press **Start**. On the Switch, join that local group manually. Map loading
   starts automatically after admission; completions wait for world readiness.
5. Leave the game connected and avoid completing quests manually during a run.
   The status card shows computed BP and accounted logical quests.
6. On reaching or exceeding the target, new completions stop. The host sends
   its normal departure notification, waits for acknowledgement or client
   departure, then closes the connection and releases the ESP32.

The final quest can overshoot the target because rewards are indivisible.
**Stop** uses the same bounded departure path. Do not force-kill the application
while it is closing. A missing response is reported as unconfirmed, not as a
successful normal disband.

## Quests and accounting

Blue and red quests are eligible, along with the mapped gold photo, Ditto and
clue-capture families. A gold sandwich is never completed, deleted, replaced or
counted. While it occupies the gold slot, blue/red work continues. The automatic
gold generator itself excludes the three sandwich variants.

BP is **computed from the mission reward table**, not read from the console.
Only one logical completion may be pending. All its required reliable frames
must be acknowledged, and the client must send the expected next BBQ snapshot
with the corresponding shared gold state/counter. Red's two messages count as
one reward. Duplicate receipts/retransmissions do not add BP. This correlation
is based on observed single-client behavior; it is not a unique game-issued
transaction receipt or a direct balance measurement.

If an unexpected snapshot, timeout or disconnect makes a result uncertain, the
run stops and does not automatically replay the pending reward. Check the
console balance before starting a new run. Concurrent manual quest completion
is intentionally unsupported because it can invalidate response correlation.

## How it was built

The standalone host was developed by observing controlled reference sessions,
then implementing admission, identity transfer, reliable channels, world-load
handshakes, handler registration, stationary presence and BBQ state transitions.
Reference-game memory automation was used only during research to obtain
controlled examples. It is not used by this plugin.

The generated host uses public PokeLDN identity resources, a public appearance
preset, constructed transforms/environment/objects and numeric state. One
fixed companion descriptor scalar retains permitted non-personal scene state
from the downloaded reference save; its exact field meaning remains unmapped.
No raw private reference, physical console identity, capture or save is shipped.

`plugin.py` registers a native tool. `run.py` provides an import-safe argument
parser. `ucbbq/native.py` preserves the radio chosen by the application, validates
the installed adapter and reports native status cards. Namespaced protocol
modules provide the generic world, quest catalogue/planner, BP ledger and
bounded host departure handshake. PokeLDN supplies crypto, radio and session
transport. See `POKELDN-LICENSE` for its upstream license.

## Validation and limitations

- Existing generic host tests confirmed map entry, a single +20 BP reward and
  five +20 BP rewards on the physical client. The host departure exchange was
  physically confirmed to display **Group disbanded** and return to solo.
- A native-entry-point run, with PokeLDN's plugin loader and guard enabled,
  completed five blue quests, accounted for 100 BP and automatically disbanded.
  The physical client confirmed +100 BP, the normal disband notification and
  return to the solo map. That test used the 0.29.1 source runtime and test code
  9577, before the interface was changed to the fixed code 4970.
- The installed Windows 0.31.1 executable passed a read-only plugin-registration,
  fixed-code and adapter check through its own packaged Python runtime. Its
  relevant Pia, reliable, radio and SV protocol modules match the tested source;
  the reviewed host-script changes concern trading, not this Union Circle path.
  The user subsequently confirmed that plugin 0.1.1 worked through the installed
  Windows app with fixed code 4970. No additional exact BP amount or separate
  manual Stop result was recorded for that confirmation.
- Plugin 0.1.1 replaces the version allowlist with capability and wire-format
  preflight checks. The packaged 0.31.2 executable passed those checks and native
  registration with the plugin filesystem guard active. Language selection now
  reads the app's settings without creating or rewriting them. Quest and radio
  behavior is unchanged. A synthetic future version number was accepted by the
  tests when the runtime contracts remained compatible; missing host options
  and changed reliable payload behavior were correctly rejected.
- Unit checks cover the target ledger, retransmissions, red reward accounting,
  target overshoot, sandwich persistence, unexpected responses, departure gates,
  native registration, fixed code and application-language selection.
- One physical client only. Four-player behavior, other game builds, repeated
  generic reconnects and long unattended sessions are not established.
- The host is not a full simulated game. There is no player movement, complete
  world simulation, online matchmaking or automatic console-menu navigation.
- Inputs are bounded to 1–1,000,000 BP and intervals of 3–60 seconds. A seven-day
  session watchdog exists independently of the target; reaching it is not proof
  that the requested goal was achieved.
- Local diagnostics under the plugin's data folder may contain runtime network
  identifiers and received game data. They are private; do not redistribute
  them. The package itself excludes runtime logs, captures, settings, keys,
  saves, environments and local machine paths.

## Android adaptation (0.1.2, experimental)

On Android the application runs a tool inside its own process. Native status
cards can synchronously call the GUI's panel-file saver while the plugin remains
on the stack. The app's filesystem guard then blocks the panel write. Version
0.1.2 proactively uses ordinary session text on Android, with no `[panel]`
messages or panel-file writes. The filesystem guard remains enabled. Desktop
child-process runs keep their normal status cards.

The plugin does not install process signal handlers from a worker thread.
It listens for the app's closing hook and, when an in-process interruption
reaches the host's cleanup, attempts a bounded normal departure before stopping
the transport. Temporary overrides of shared protocol functions are restored
after every run, including failed/interrupted runs. Mobile host launchers use
the application's module importer so compiled Chaquopy assets can be loaded.

Two repeated runs through PokeLDN's actual in-process executor were simulated
on Windows with Android mode, plugin guard active and an offline host stub.
Both finished successfully, produced text status, created no panel files and
opened no radio. Unit checks cover worker execution, signal/panel avoidance,
repeat-run cleanup, importer selection and departure acknowledgement/leave/
timeout cases. **This is not physical Android or Android USB-radio validation.**

Install 0.1.2 through the Android app's Plugins page. For the first device test,
use a 20 BP target, join local group 4970 manually and confirm the credit and
normal return to the solo map. Keep the device/app available for this first
test; Android suspension behavior and manual Stop still need physical checks.
The radio and keys continue to come from PokeLDN's existing settings.

The unsigned development package is intended for local review. Nothing is
uploaded or published by installing or running it.

## Source and rebuilding

All plugin source is included as plain Python. `tests/test_native.py` contains
offline parser, registration, settings and adapter checks; it does not open a
radio. Run it in a development Python environment where PokeLDN is importable.
The protocol modules are under `ucbbq/` and the mission table under `ucbbq/data/`.

Use PokeLDN's official `scripts/pack_plugin.py` against this plugin directory to
rebuild the `.pokeplugin`. The manifest excludes tests and Python caches from
the installable package. A separate source ZIP can retain tests. Never include
your plugin-data directory, local settings, keys or runtime diagnostics.

## Upstream project

This plugin uses [PokeLDN](https://github.com/Decryptu/pokeldn). The upstream
license is included as `POKELDN-LICENSE`; this repository retains the AGPL-3.0
license text in `LICENSE`.
