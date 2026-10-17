# Code signing policy

**Status:** release installers are currently **unsigned**. An application to the free [SignPath Foundation](https://signpath.org) open-source program is planned; this page will say so once signing is active.

When signing is active: *Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org).*

## What is signed

Only the release installer `Xotira-Setup-<version>.exe`, built by the [Release workflow](.github/workflows/release.yml) from a tagged commit in this repository. Nothing built on a personal computer is ever signed.

The installer bundles the official Python runtime from python.org. Its `python.exe`, `pythonw.exe` and DLLs already carry the Python Software Foundation's own signature; the build stops if that signature is missing or invalid.

## Team roles

| Role | Members |
|---|---|
| Committers and reviewers | [Humoyun Safarov](https://github.com/humoyun200108) |
| Approvers | [Humoyun Safarov](https://github.com/humoyun200108) |

## Privacy policy

This program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it.

Xotira runs a local server bound to `127.0.0.1`, bundles its fonts and makes no network requests. The only outside connections are ones you start yourself: links you click (Telegram, GitHub) and Steam/Windows dialogs you open from the app.

## Verifying a download

1. Compare the file's SHA-256 with `SHA256SUMS.txt` from the same release:
   `Get-FileHash .\Xotira-Setup-1.0.0.exe -Algorithm SHA256`
2. Check the build provenance (requires the GitHub CLI):
   `gh attestation verify .\Xotira-Setup-1.0.0.exe -R humoyun200108/xotira`
3. Once signing is active: right-click the file → Properties → Digital Signatures.
