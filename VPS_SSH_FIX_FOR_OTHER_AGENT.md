# VPS SSH Fix — Playbook for DESKTOP-LESJE9C Agent

> Written by the Claude session on Work PC (IP 41.136.167.43) that currently
> has working SSH to the VPS. This is a focused playbook — do the steps in
> order, stop as soon as you're in.

## TL;DR of what's wrong

Your symptom is `ssh: connect to host srv1191974.hstgr.cloud port 22: Unknown error`.
On Windows OpenSSH, **"Unknown error"** almost always means one of:

1. **IPv6 resolution is succeeding but the IPv6 route is broken.** The VPS has
   both A and AAAA records. Windows tries IPv6 first and bails with that exact
   error string instead of falling back to IPv4.
2. **DNS resolver returning nothing / stale cache** after network changes.
3. **ISP blocking outbound port 22** (rare but real — common on some mobile/
   residential networks).

Firewall on the VPS side is **already disabled**, so this is almost certainly
client-side. Don't chase the VPS.

---

## Step 1 — Force IPv4 and try again (fixes it 90% of the time)

```bash
ssh -4 -o ConnectTimeout=10 root@srv1191974.hstgr.cloud 'echo OK'
```

If that works, make it permanent by adding one line to `~/.ssh/config`:

```
Host markai-vps markai
    HostName srv1191974.hstgr.cloud
    User root
    Port 22
    AddressFamily inet          # <-- add this line
    ServerAliveInterval 60
    ServerAliveCountMax 3
    StrictHostKeyChecking accept-new
```

Then: `ssh markai 'echo OK'` — done.

---

## Step 2 — If Step 1 still fails: bypass DNS, use raw IPv4

```bash
ssh -4 -o ConnectTimeout=10 root@72.61.215.110 'echo OK'
```

- If **this works but the hostname doesn't** → DNS problem. Flush it:
  ```powershell
  # In PowerShell (not Git Bash)
  ipconfig /flushdns
  ```
  Then retry Step 1.
- If **this also fails** → go to Step 3.

---

## Step 3 — Prove port 22 reachability at the TCP layer

From **PowerShell** (more reliable than Git Bash for this):

```powershell
Test-NetConnection -ComputerName 72.61.215.110 -Port 22
```

Interpret results:

| Result | Meaning | Fix |
|---|---|---|
| `TcpTestSucceeded : True` | Port is reachable, problem is in OpenSSH client | Go to Step 4 |
| `TcpTestSucceeded : False`, `PingSucceeded : True` | ICMP works but port 22 blocked | ISP is blocking port 22 outbound → Step 5 |
| `TcpTestSucceeded : False`, `PingSucceeded : False` | Host unreachable entirely | Network/routing problem — check VPN, proxy, or try tethering |

---

## Step 4 — OpenSSH client in weird state

If TCP works but `ssh` says "Unknown error":

```bash
# Verbose SSH — look for what it's actually doing
ssh -vvv -4 root@72.61.215.110 2>&1 | head -40
```

Common fixes:
- **Stale agent:** `ssh-add -D` then retry.
- **Corrupted known_hosts entry:** `ssh-keygen -R srv1191974.hstgr.cloud && ssh-keygen -R 72.61.215.110`, then retry.
- **Wrong OpenSSH binary on PATH:** check `where ssh` in PowerShell. If
  `C:\Windows\System32\OpenSSH\ssh.exe` comes after a broken copy, fix PATH.

---

## Step 5 — ISP is blocking port 22 outbound

Options (in order of effort):
1. **Tether off your phone / switch networks** to confirm. If it works on
   tethering, your current ISP is the problem.
2. **Ask the user to ask Hostinger to enable port 443 SSH** (many providers
   let you SSH over 443). Not a fast fix — skip unless desperate.
3. **Use a different machine** to push the public key, then come back to this
   one (Work PC can do this — see Step 6).

---

## Step 6 — Once you're in (any method), install the key

You don't need the password more than once. Do this in the very first
successful session:

```bash
ssh root@srv1191974.hstgr.cloud "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys << 'KEY'
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPUygpj7z2HiszsZ1kl9M6JOVUDrarYwomwSkMEso6nS Ngeks@DESKTOP-LESJE9C
KEY
chmod 600 ~/.ssh/authorized_keys"
```

Then verify passwordless auth:
```bash
ssh markai 'uptime && whoami'
```

Expected: prints uptime + `root`, **no password prompt**.

> **Alternative if you can't SSH from DESKTOP-LESJE9C at all:**
> Ask the user to run that exact `cat >> ~/.ssh/authorized_keys …` block from
> the Work PC session (which already has SSH working). That agent can paste
> the public key on your behalf.

---

## How I (Work PC agent) actually connect — the efficient pattern

For reference, this is what works reliably for me. Port 22 is currently
whitelisted for my IP in Hostinger, and I'm on an ISP that doesn't block
outbound 22.

```bash
# Non-interactive one-shot — no prompts, short timeout, no known_hosts friction
ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no root@srv1191974.hstgr.cloud '<command>'
```

Key ingredients:
- `ConnectTimeout=10` — fail fast instead of waiting 60s
- `StrictHostKeyChecking=no` — avoid interactive host-key prompts on first
  contact (safe inside an agent because the host key is already pinned)
- **No `-t`** unless you explicitly need a TTY (e.g. for `psql` interactive).
  Running commands without `-t` lets output stream cleanly to the log file.

For long-running or multi-command work, batch everything into ONE ssh call
using `'bash -s' <<'EOF' … EOF` or `'cmd1 && cmd2 && cmd3'` — each new `ssh`
call pays the handshake cost (~1-2s).

---

## If you get in: deploys

The **only** sanctioned deploy path is the redeploy script — never a manual
`git reset --hard` to a feature branch, and never `build --no-cache` (it only
bloats the already-huge BuildKit cache):

```bash
ssh markai 'cd /var/www/markai && bash scripts/vps-redeploy.sh'
```

After deploy, smoke test:
```bash
ssh markai 'docker compose -f /var/www/markai/docker-compose.yml -f /var/www/markai/docker-compose.vps.yml ps'
ssh markai 'curl -sf https://api.markai.srv1191974.hstgr.cloud/health'
```

---

## Current VPS state (as of this playbook — for context)

- Host: Ubuntu 24.04.3 LTS, 4 CPU, 16 GB RAM, 193 GB disk
- **Disk 81% full (156/193 GB)** — primary cause: `/var/lib/containerd`
  BuildKit cache at 123 GB. A separate cleanup plan is in progress — don't
  run `docker builder prune` unilaterally, it's part of a coordinated fix.
- Load average: 0.12/0.23/0.25 — idle
- 21 docker containers + 19 PM2 native apps running across multiple projects
  (markai, francais, mls, rideshare, etc.)
- Traefik on 80/443 proxies everything; no other host ports exposed
- Hostinger firewall is currently **disabled** (per user)

---

## Dead ends — don't waste time on these

- ❌ `sshpass` on Windows — not in MSYS2, not in Chocolatey. Don't try to install it.
- ❌ `choco install openssh` — Windows already ships a working OpenSSH.
- ❌ Regenerating the key pair — the existing `id_ed25519` is fine.
- ❌ Editing `/etc/hosts` on Windows to pin the IP — `AddressFamily inet` in
  `~/.ssh/config` is cleaner and survives DNS changes.
- ❌ Rebooting the VPS — it's up 5 days serving other projects, SSH daemon is
  healthy (I'm connected to it right now).
