# Clean deployment direction changed — 2026-10-18

The former command using `install_vps.py` is retired and now fails without installing anything.
Use [MULTI_ACCOUNT.md](MULTI_ACCOUNT.md) and the pinned command supplied with the PR update.

The sole Clean systemd unit runs the verified Python signal producer, then the existing TypeScript multi-account backend with Supabase AES-GCM agent secrets. No systemd signing key is created or exported.
The old `mrv1-production` timer and phase68g kill switch stay disabled.
The Python portfolio modules remain only as simulation/reference code.
