# Rules for agents and contributors in aikos-home/aikos

Claude Code reads this file automatically. Every agent and every person working in this repository follows it.

## Who owns what

| Path | Owner |
|---|---|
| `custom_components/aikos/` | aikos core |
| `esphome/components/` | intercom and roomkey maintainers, jointly |
| `services/` (when it exists) | aikos core; the owner of each service's logic is named in its README |
| `docs/`, `tools/`, `.github/`, `homeassistant/`, `CLAUDE.md`, `FROZEN.md` | aikos core |

Don't change another owner's part. Propose the change to them instead.

## `main` is protected

- Changes only through a pull request; the required checks must be green. This applies to admins too.
- Never force-push, never delete or move a tag, never change or switch off the branch protection. Only the project owner does that.
- Tags are versions that devices and services pin. A tag, once set, stays.

## Frozen building blocks

Everything listed in [`FROZEN.md`](FROZEN.md) is frozen at its version. Before you edit any file of a frozen block:

1. Read `FROZEN.md` and the block's README (its interface).
2. Don't change behaviour in place. A change goes: proposal → pull request → the block's regression tests green →
   review at the quality gate (aikos core and the project owner) → new version tag. Old tags stay usable.
3. If you only need something new, add it next to the existing behaviour (new function or option, default off)
   instead of changing what is there.

## Architecture rules (quality gate)

- **One building block, one job.** No monofile code: split into modules with a clear responsibility each.
- **Small public interface,** internals private. Callers depend on the interface only.
- **Configuration from outside** (options, environment, entities). Nothing in the code knows a particular house.
- **Dependencies point inward:** devices use shared blocks, never the other way round. Household logic belongs in the
  integration, not in device firmware.
- **Tests next to the code,** at least one regression test per behaviour rule.
- **Every block has a README** describing its interface, configuration and error cases.

## Privacy and secrets

- Run `tools/privacy_scan.py` with the private denylist before every push. The denylist is never committed; CI runs the
  built-in checks only.
- Never commit secrets (keys, tokens, passwords, Wi-Fi data), private IP or MAC addresses, e-mail addresses, names or
  addresses of residents, or Home Assistant entity ids of a real home.
- Commit with your GitHub noreply address.

## Naming

- Devices: `aikos-<family>-<role|room>`; ESPHome `project: aikos-home.<family>[-<part>]` with a semantic version.
  Software recognises devices by `project`, never by their name.
- Component tags: `<short-name>-vMAJOR.MINOR.PATCH`, e.g. `voice-v1.0.0`.
