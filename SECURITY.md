# Security

Xotira deletes files, so safety is the first design rule.

## What Xotira will and won't do

- Deletes only what you confirm in a dialog that lists every item and its size.
- Moves files to the Recycle Bin unless you explicitly choose permanent deletion.
- Refuses to delete drive roots, `Windows`, `Program Files`, system files (`pagefile.sys`, `hiberfil.sys`, `swapfile.sys`) and the main user folders themselves.
- Smart cleanup removes only the *contents* of known cache/temp folders; files in use are skipped and temp files newer than 24 hours are kept.
- Never runs as administrator unless you press **Full access** and approve the Windows prompt.
- Listens on `127.0.0.1` only. State-changing requests need a custom `X-Xotira` header, so a web page cannot trigger them (the browser blocks the cross-origin preflight), and requests with a foreign `Host` header are rejected.
- Sends nothing over the network. No telemetry, no update pings, fonts are bundled.

## Reporting a vulnerability

Please report privately on Telegram: [@humoyunsafarov](https://t.me/humoyunsafarov). Describe the issue and how to reproduce it; you'll get a reply within a few days. Please don't open a public issue for security problems.
