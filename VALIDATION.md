# Validation record

Development build: 0.1.2. Windows baseline and experimental Android adaptation.
The physical run below was performed with 0.1.0. Version 0.1.1 replaces the
version-number gate with offline API/wire checks and reads language settings
without writing them. Quest and transport behavior is unchanged.

Confirmed:

- Generic host loaded the physical client's map without Eden.
- Native entry point with PokeLDN plugin loader and guard: five logical blue
  completions, 100 computed BP, corresponding physical +100 BP confirmed.
- Goal-triggered host departure received the client's acknowledgement; the
  user confirmed Group disbanded and return to the solo map.
- 141 offline tests passed across the protocol/goal suite and native plugin
  tests, including automatic application-language selection and fixed code.
- PokeLDN 0.31.1 packaged Windows executable passed the adapter and native tool
  registration check, exposing only target BP and advanced interval inputs.
- Installation package built and validated by PokeLDN's own package builder.
- Installed 0.31.2 Windows executable passed API/wire preflight and registration
  with the plugin guard active and no radio started. A compatible runtime with
  a synthetic future version number passes too; missing required options and
  broken reliable framing are rejected. Missing language settings create no file.

Limits of this evidence:

- The physical goal test used PokeLDN 0.29.1 source runtime and code 9577.
  The final plugin always uses 4970. Code 4970, installed-GUI operation, manual
  Stop and a longer native run crossing red/gold thresholds remain unverified
  end to end in this plugin build.
- Existing predecessor-host tests exercised red and permitted gold families;
  those do not replace a physical test of the new BP ledger for those families.
- An early announcement could precede peer readiness. An attempted readiness
  gate caused a circular wait and was removed. Current startup preserves the
  known working order. A single later announcement is allowed for a peer that
  registers seat handlers but has not joined. The successful goal run did not
  require that additional announcement, so its recovery effect is unverified.
- No four-player, cross-version or long-duration validation is claimed.

Distribution contains source and generic numeric/public resources only. Runtime
captures, local settings, saves, keys and personal console identity are excluded.

Android-specific evidence (0.1.2):

- Two repeated offline runs through PokeLDN 0.31.2's real InProcess executor,
  with Android platform mode and plugin guard active, finished with exit 0.
- Status was ordinary text, with no panel protocol or panel files; no board,
  network group, physical phone or real keys were used in this simulation.
- Worker-thread unit tests forbid signal registration and panel calls, and
  verify protocol override restoration and one reusable closing hook.
- Departure-drain tests cover matching acknowledgements, client departure and
  silent timeout. The actual Android Stop/USB behavior remains unverified.
- An Android 0.31.3 user traceback identified the original panel-write denial.
  Physical validation of this adaptation on that device is still pending.
