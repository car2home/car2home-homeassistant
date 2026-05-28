# Security Policy

We take the security of the Car 2 Home integration seriously, both for the
data flowing between the mobile app and the Home Assistant instance, and for
the integrity of every Home Assistant installation that runs this plugin.

## Supported versions

| Version | Supported |
|---|---|
| latest | ✅ |
| older | ❌ best-effort only, please upgrade first |

We only ship security fixes on the latest release. Older versions are not
patched. Upgrading is the recommended response to any disclosed issue.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security reports.** A public
issue would expose the vulnerability before a fix is available and put every
existing user at risk.

Instead, use one of the private channels below:

1. **Preferred:** the GitHub Private Vulnerability Reporting flow on this
   repository. Go to the **Security** tab, click **Report a vulnerability**,
   and fill in the form. Only repository maintainers receive the report.
2. **Email:** `contact@car2home.ai` if the GitHub flow does not work
   for you. Encrypt with the GPG key published in the same repo if you are
   sending exploit details.

In your report, please include:

- A short description of the issue and the impact you observed.
- Steps to reproduce or a minimal proof of concept.
- The version of the integration, of Home Assistant and of the mobile app
  where you reproduced it.
- Whether the issue is exploitable remotely, requires local network access
  or requires physical access to the phone.

## What to expect

- We acknowledge new reports within 5 business days.
- We aim to confirm or rule out the issue within 15 business days.
- We coordinate the disclosure timeline with you before publishing any
  advisory. Default window is 90 days from acknowledgement, shorter if
  active exploitation is observed in the wild.
- We publish a GitHub Security Advisory and a CVE when the fix ships.
- We credit reporters publicly unless they prefer to stay anonymous.

## Scope

In scope:

- Code in this repository (`custom_components/car2home/` and helpers).
- The wire protocol between the Car 2 Home mobile app and this integration
  (HTTP pairing endpoint, persistent WebSocket, HTTP ingest fallback).
- Token handling, authentication and authorization paths.
- Anything that could lead to unauthorized data exfiltration, denial of
  service against Home Assistant or remote code execution inside HA via
  this integration.

Out of scope:

- Home Assistant core vulnerabilities (please report those to
  https://www.home-assistant.io/security/).
- Issues that require an attacker to already have full administrative access
  to the Home Assistant instance.
- Issues that require modifying the integration source code at install time.
- Social engineering, phishing, or physical attacks on the phone or HA host.
- Vulnerabilities in third-party transports (Nabu Casa, Cloudflare Tunnel,
  Tailscale, etc.). Please report those to the respective vendors.

## Hardening recommendations for operators

- Keep Home Assistant up to date.
- Pair the integration over a trusted network when possible. The pairing
  endpoint is unauthenticated by design (the 6-digit code is the auth) and
  has a 5 minute TTL.
- Treat the integration token like any other Home Assistant credential.
  Do not share it, do not paste it into logs, do not commit it to git.
- Enable two-factor authentication on the Home Assistant user account that
  owns the integration.
- If you expose Home Assistant publicly, place it behind a reverse proxy
  with TLS. The integration works fine over `wss://`.
