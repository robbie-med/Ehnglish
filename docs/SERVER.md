# Server (owner's PC)

Trimmed from `/home/user/Projects/servers/README.md` and the 4-hourly snapshot in
`/home/user/Projects/monitor_all/snapshots/reports/` (section 10, item 6 of the plan). Verified 2026-09-30.

| | |
|---|---|
| Host | `PC`, HP EliteDesk 800 G1 USDT, LAN 192.168.8.200 |
| OS | Linux Mint 21.3 (Ubuntu 22.04 base), kernel 6.8 |
| CPU / RAM | 8 threads, 15 GB RAM. **No GPU.** |
| Disk | 1.8 TB, ~414 GB free (raw store lives in `data/` on this disk) |
| Docker | Docker 29.1, Compose v5.3. Postgres 14 also runs natively on 5432, so the app's Postgres 16 stays inside the compose network. |
| Node / Python | Node 24 via nvm (`~/.nvm/versions/node/v24.16.0`), Python 3.12 via uv |
| Tunnel | `cloudflared` runs as the user service `cloudflared-diet.service` with config `~/.cloudflared/diet-loggers.yml` (tunnel name `diet-loggers`). All `*.bo-bob.com` apps on this PC share it. |
| Access | Cloudflare Zero Trust team `sikoraweb` (`https://sikoraweb.cloudflareaccess.com`). Existing pattern: app per hostname, allow policy by email. |
| Ports | Registered in `/home/user/Projects/PORTS.md`: 3305 api, 3914 Vite dev, 3607 test Postgres |

Other machines (not used by this app): a Hetzner VPS (small, `kapp.robbiemed.org`) and an Umbrel box on the LAN.
