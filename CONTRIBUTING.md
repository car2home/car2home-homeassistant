# Contributing to Car 2 Home for Home Assistant

Thanks for taking the time to contribute. This project exists because users
extend it. Bug reports, fix PRs, translations, automation examples and
documentation improvements are all welcome.

## Before you start

- Read the [README](README.md) end to end. Most "how do I" questions are
  answered there, including pairing, supported sensors, events and reverse
  proxy compatibility.
- Search [existing issues](../../issues) and pull requests. Someone may have
  already filed the same thing.
- For larger changes (new platform, new wire frame, refactor of the
  coordinator or the pairing flow), please open an issue first to align on
  the approach. It is no fun to write a 300 line PR only to learn it does
  not match the project direction.
- For security issues, do not open a public issue. Follow
  [SECURITY.md](SECURITY.md) instead.

## Reporting bugs

Open a GitHub issue with the following info:

- Home Assistant version.
- This integration's version (see Settings → Devices & Services → OBD 2 Home).
- Mobile app version (Android or iOS) and OS version.
- Vehicle make, model and year.
- Repro steps, including whether you are on Online or Wi-Fi only sync mode.
- Relevant excerpts from `home-assistant.log` and from the app diagnostics
  log (Settings → Diagnostics → Share logs in the app).

Please redact tokens, the ws_url and any address before posting log output.

## Proposing features

Open an issue with the "feature request" template. Describe the use case
first, the proposed solution second. The use case is what helps maintainers
decide whether the feature belongs in the integration, in the mobile app,
or in an HA automation.

## Developing

### Local layout

```
custom_components/car2home/   integration code (Python)
brands/                        PNG icons for the home-assistant/brands repo
README.md                      user-facing documentation
SECURITY.md                    vulnerability disclosure policy
CODE_OF_CONDUCT.md             community standards
CONTRIBUTING.md                this file
```

### Running against a local Home Assistant

1. Install Home Assistant 2024.12 or later in a virtualenv or a container.
2. Symlink `custom_components/car2home/` into the HA config directory:
   ```sh
   ln -s "$(pwd)/custom_components/car2home" /path/to/ha/config/custom_components/car2home
   ```
3. Restart HA. Add the integration from **Settings → Devices & Services**.
4. Pair the Car 2 Home mobile app against your local HA instance.

### Style

- Python target: 3.12 (matches HA core).
- Follow the existing patterns in `coordinator.py`, `api.py` and `entity.py`.
- Type hints everywhere, `from __future__ import annotations` at the top of
  new files.
- Async by default. Anything that touches I/O must be `async def`.
- No blocking calls from the event loop. Wrap CPU heavy work in
  `hass.async_add_executor_job(...)` if needed.
- One change per pull request. If you find an unrelated bug while working
  on a feature, open a separate PR for it.

### Tests

- Add unit tests where the change has clear input/output. Wire frame
  parsing, slug generation and event payload assembly are good candidates.
- Run `python -m pytest` before opening the PR.

### Translations

- All UI text lives under `custom_components/car2home/translations/`.
- `strings.json` is the canonical English source.
- One JSON file per locale (`en.json`, `pt-BR.json`, ...). When you add a
  new key in any locale, mirror it in every other locale, even if you only
  copy the English value for now.

## Pull request checklist

Before requesting review:

- [ ] The change has a clear, single purpose.
- [ ] `manifest.json` version bumped if user-visible behavior changed.
- [ ] README updated if a feature was added, removed or renamed.
- [ ] CHANGELOG entry (in the PR description is fine for now) explains
      what changed, why, and any migration step the user needs to take.
- [ ] All translation files updated when adding new strings.
- [ ] No tokens, addresses or paths from your local environment in the diff.
- [ ] Commit message describes the change concisely. We use Conventional
      Commits for releases (`feat:`, `fix:`, `docs:`, `chore:`, etc).

## Code of conduct

By participating in this project you agree to the
[Contributor Covenant](CODE_OF_CONDUCT.md). Be respectful, be patient and
assume good faith from other contributors.
