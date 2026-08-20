# VPS SSH Access Troubleshooting — For Claude Code Agent

## Context

A Claude Code session on the user's Windows 11 PC (DESKTOP-LESJE9C) is trying to establish SSH access to the MARK AI VPS. The Hostinger firewall has been **disabled** but SSH still fails.

## Machine Details

- **OS**: Windows 11 Pro 10.0.22631
- **Shell**: Git Bash (MSYS2)
- **SSH client**: OpenSSH (bundled with Git for Windows)
- **VPS Host**: `srv1191974.hstgr.cloud`
- **VPS IPv4**: `72.61.215.110`
- **VPS IPv6**: `2a02:4780:59:5637::1`
- **User's current public IPv4**: `175.158.242.235`
- **VPS User**: `root`
- **VPS Port**: `22`

## What was done

### Step 1: SSH config created

```bash
mkdir -p ~/.ssh && cat > ~/.ssh/config << 'EOF'
Host markai-vps markai
    HostName srv1191974.hstgr.cloud
    User root
    Port 22
    ServerAliveInterval 60
    ServerAliveCountMax 3
    StrictHostKeyChecking accept-new
EOF
chmod 600 ~/.ssh/config
```
**Result**: Success — file created at `~/.ssh/config`

### Step 2: sshpass installation attempted

```bash
which sshpass
# NOT_INSTALLED

pacman -S --noconfirm sshpass
# CANNOT_INSTALL (not in MSYS2 repos)

choco install sshpass -y
# Package not found in Chocolatey repository
```
**Result**: sshpass is not available on Windows/Git Bash. Cannot do automated password auth.

### Step 3: SSH key pair generated

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N "" -q
```
**Result**: Success — key pair generated.

**Public key**:
```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPUygpj7z2HiszsZ1kl9M6JOVUDrarYwomwSkMEso6nS Ngeks@DESKTOP-LESJE9C
```

### Step 4: Attempted to copy public key to VPS

User ran this manually from PowerShell:
```bash
ssh root@srv1191974.hstgr.cloud "mkdir -p ~/.ssh && echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPUygpj7z2HiszsZ1kl9M6JOVUDrarYwomwSkMEso6nS Ngeks@DESKTOP-LESJE9C' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

**Error**:
```
ssh: connect to host srv1191974.hstgr.cloud port 22: Unknown error
```

### Step 5: Earlier direct SSH attempts (same session, different times)

Earlier in this session, the user successfully SSHed from the same PowerShell:
```bash
ssh root@srv1191974.hstgr.cloud
# Prompted for password → entered → connected successfully
# Multiple successful sessions throughout the day
```

The SSH connection worked earlier but now fails with "Unknown error".

## Errors encountered

| Command | Error | Notes |
|---------|-------|-------|
| `ssh markai 'uptime'` | `Could not resolve hostname markai` | Before SSH config was created |
| `ssh root@srv1191974.hstgr.cloud "..."` | `connect to host srv1191974.hstgr.cloud port 22: Unknown error` | After config created, firewall disabled |

## Current state of `~/.ssh/`

```
~/.ssh/
├── config          (SSH alias for markai)
├── id_ed25519      (private key, just generated)
├── id_ed25519.pub  (public key, needs to be added to VPS)
├── known_hosts     (VPS host key already trusted from earlier sessions)
└── known_hosts.old
```

## What the VPS-connected agent needs to do

1. **Diagnose why SSH is failing** — The firewall is disabled but port 22 is unreachable. Possible causes:
   - DNS resolution failing for `srv1191974.hstgr.cloud`
   - ISP blocking port 22 outbound
   - VPS SSH service (sshd) crashed or stopped
   - Hostinger network issue
   - IPv6 vs IPv4 routing issue (VPS has both)

2. **Add the public key to the VPS** — Once SSH is working again, add this key to `/root/.ssh/authorized_keys`:
   ```
   ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPUygpj7z2HiszsZ1kl9M6JOVUDrarYwomwSkMEso6nS Ngeks@DESKTOP-LESJE9C
   ```

3. **Test that key auth works** — After adding the key, verify:
   ```bash
   ssh markai 'uptime'
   ```
   Should connect without password prompt.

## VPS password

Available in the project `.env` file as `SSH_PW` (line 82). The agent with VPS access can read it from there.

## Deploys

The **only** sanctioned way to deploy is the redeploy script, run on the VPS:

```bash
ssh markai 'cd /var/www/markai && bash scripts/vps-redeploy.sh'
```

It pulls `main`, backs up the database first, builds before stopping anything,
and recreates only changed containers. Do not hand-roll `git reset --hard` to
feature branches or `docker compose build --no-cache` deploys — stale-branch
resets have shipped old code to prod before, and `--no-cache` just burns disk
on the BuildKit cache for no benefit.
