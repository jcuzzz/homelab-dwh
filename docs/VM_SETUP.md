# Warehouse VM setup

Builds the Linux server that runs the extract-load pipeline: a Proxmox VM running Ubuntu
Server LTS, with PostgreSQL, a read-only mount of the network share holding the CASES CSV
exports, and the loader.

**Status:** written 2026-10-23, not yet run end to end. Correct this file as steps are proven.

The VM never runs this public repository. It runs `PRIVATE_REPO`, a private copy made from
this repository's `v1.0.0` release, and it always runs a tagged release.

## What is sensitive and where it lives

Real data and real infrastructure details exist only on the VM. The repository holds
placeholders only.

| Item | Lives in | Protection |
|---|---|---|
| Student, family and staff records | PostgreSQL data directory; `/srv/warehouse/archive` | Directories readable only by their service user; encrypted disk; restricted backups |
| Network share password | `/etc/warehouse/smb.cred` | Owned by root, mode 600; read-only service account |
| Share path, server names, VM IP address | `/etc/fstab` on the VM | Never committed to the repository |
| Database password | Nowhere: peer authentication over a local socket | PostgreSQL listens on localhost only |
| Loader output and logs | The VM terminal | Database errors are redacted by the loader, but keep output on the VM anyway |

The archive directory is the irreplaceable copy: the share is overwritten by each new
export, and every bronze table can be rebuilt from the archive.

## Placeholders

Replace these on the VM only. Never write the real values into this file.

| Placeholder | Replace with |
|---|---|
| `//FILESERVER/SHARE/CASES-EXPORTS` | UNC path of the folder holding the CASES CSV exports |
| `SVC_ACCOUNT` / `DOMAIN` | Dedicated service account with read-only access to that folder only |
| `ADMIN_SUBNET` | IP address or subnet of the machines allowed to SSH in, e.g. `192.0.2.0/24` |
| `VM_IP` | The VM's IP address |
| `TIMEZONE` | The VM's time zone, e.g. `Etc/UTC` (list them with `timedatectl list-timezones`) |
| `PRIVATE_REPO` | Name of the private GitHub repository the VM runs |
| `vX.Y.Z` | The release tag to run, e.g. `v1.0.0` |

**Ask IT for:** a dedicated service account (not a personal login) with read-only access
to the export folder only, and SMB3 encryption enabled on that share.

## 1. Create the VM in Proxmox

Upload the Ubuntu Server LTS ISO to Proxmox storage, then **Create VM**:

| Tab | Setting |
|---|---|
| General | Name `warehouse`; tick *Start at boot* |
| OS | Ubuntu Server LTS ISO, type Linux |
| System | Machine `q35`; tick *QEMU Agent* |
| Disks | VirtIO SCSI single; 60 GB; tick *Discard* (and *SSD emulation* on SSD storage) |
| CPU | 2 cores, type `host` |
| Memory | 4096 MB |
| Network | VirtIO, bridge `vmbr0` |

That is enough for PostgreSQL and the loader. All three can be increased later.

Limit who has Proxmox permissions on this VM: console access and backups expose its data.

## 2. Install Ubuntu Server

- **Network:** give the VM a static IP or a DHCP reservation. Record it as `VM_IP`.
- **Storage:** *Use an entire disk*, *Set up this disk as an LVM group*, and tick
  *Encrypt the LVM group with LUKS*. Store the passphrase in your organisation's password manager.
  Every reboot then waits for the passphrase in the Proxmox console. If that is not
  acceptable, use encrypted Proxmox storage instead, agreed with IT. Do not skip both.
- **Profile:** your own admin account. Not `warehouse`.
- **SSH:** tick *Install OpenSSH server*.
- **Featured snaps:** none.

## 3. Base hardening

Log in on the console or by SSH as your admin account.

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y qemu-guest-agent unattended-upgrades ufw
sudo systemctl enable --now qemu-guest-agent
sudo dpkg-reconfigure -plow unattended-upgrades
sudo timedatectl set-timezone TIMEZONE
```

Copy your SSH key from your Windows PC (PowerShell):

```powershell
ssh-keygen -t ed25519            # only if you have no key yet
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh <admin>@VM_IP "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

Confirm key login works in a **new** window, then turn off password logins on the VM:

```bash
sudo tee /etc/ssh/sshd_config.d/10-hardening.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sudo systemctl reload ssh
```

Keep the current session open until a fresh SSH login succeeds. Then the firewall:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from ADMIN_SUBNET to any port 22 proto tcp
sudo ufw enable
```

## 4. Service account and directories

The loader runs as a dedicated `warehouse` user, never as your admin account.

```bash
sudo useradd --system --create-home --shell /bin/bash warehouse
sudo install -d -o warehouse -g warehouse -m 700 /srv/warehouse /srv/warehouse/archive
sudo install -d -o root -g warehouse -m 750 /etc/warehouse
```

## 5. PostgreSQL

```bash
sudo apt install -y postgresql
psql --version
sudo -u postgres createuser warehouse
sudo -u postgres createdb --owner warehouse warehouse
sudo ss -ltnp | grep 5432        # must show 127.0.0.1 / ::1 only
```

The `warehouse` Linux user connects as the `warehouse` database role through the local
socket using peer authentication, Ubuntu's default for local connections. No database
password exists to leak. CI tests against PostgreSQL 17; any version from 14 up works.

## 6. Connect the export share

The real share path is written in exactly one place: `/etc/fstab` on the VM. The loader
only ever sees the mount point `/mnt/exports/cases`, so its commands never change.

```bash
sudo apt install -y cifs-utils
sudo install -m 600 -o root -g root /dev/null /etc/warehouse/smb.cred
sudo nano /etc/warehouse/smb.cred
```

```text
username=SVC_ACCOUNT
password=<password>
domain=DOMAIN
```

```bash
sudo install -d -m 755 /mnt/exports/cases
sudo nano /etc/fstab
```

Add one line. Write any space in the path as `\040`:

```text
//FILESERVER/SHARE/CASES-EXPORTS  /mnt/exports/cases  cifs  ro,credentials=/etc/warehouse/smb.cred,uid=warehouse,gid=warehouse,file_mode=0440,dir_mode=0550,seal,_netdev,nofail,x-systemd.automount  0  0
```

| Option | Why |
|---|---|
| `ro` | The VM can never modify or delete exports |
| `uid`, `gid`, `file_mode`, `dir_mode` | Only the `warehouse` user can read the files |
| `seal` | Encrypts SMB traffic, since the network is not segmented |
| `_netdev`, `nofail`, `x-systemd.automount` | Boot does not hang if the file server is unreachable |

```bash
sudo systemctl daemon-reload
sudo mount /mnt/exports/cases
sudo -u warehouse ls /mnt/exports/cases
```

**If the mount fails**, `sudo dmesg | tail -20` shows why:

- *Permission denied:* wrong account, password or domain, or the account lacks folder access.
- *Host not found:* use the file server's full domain name or IP address.
- *Error mentioning encryption or `seal`:* the share does not support SMB3 encryption. Ask
  IT to enable it. Remove `seal` only with IT's agreement, because exports then cross the
  network unencrypted.

### Changing the path later

```bash
sudo nano /etc/fstab                  # edit only the //FILESERVER/... part of the line
sudo umount /mnt/exports/cases
sudo systemctl daemon-reload
sudo mount /mnt/exports/cases
sudo -u warehouse ls /mnt/exports/cases
```

To change the share password, edit `/etc/warehouse/smb.cred`, then unmount and mount
again. To add another source later, such as Edval, create `/mnt/exports/edval` and add a
second fstab line.

## 7. Install the loader

The VM clones `PRIVATE_REPO`, not this public repository. Give the VM a read-only deploy
key for it:

```bash
sudo -iu warehouse
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N "" -C "warehouse-vm"
cat ~/.ssh/github_deploy.pub
```

In GitHub, open `PRIVATE_REPO`'s **Settings → Deploy keys → Add deploy key**, paste the
key, and leave *Allow write access* unticked. Then, still as `warehouse`:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/github_deploy
  IdentitiesOnly yes
EOF
git clone git@github.com:<owner>/PRIVATE_REPO.git ~/warehouse
cd ~/warehouse && git checkout vX.Y.Z && uv sync
exit
```

Create the environment file as your admin account:

```bash
sudo install -m 640 -o root -g warehouse /dev/null /etc/warehouse/warehouse.env
sudo nano /etc/warehouse/warehouse.env
```

```text
DATABASE_URL=postgresql:///warehouse?host=/var/run/postgresql
ARCHIVE_DIR=/srv/warehouse/archive
```

## 8. First load

```bash
sudo -iu warehouse
cd ~/warehouse
set -a; . /etc/warehouse/warehouse.env; set +a
uv run python -m ingest init-db
uv run python -m ingest load --source cases /mnt/exports/cases
```

Each file prints `loaded`, `skipped` or `FAILED`. If files are reported as not valid UTF-8,
add `--encoding cp1252`. A header-change failure means the export's columns changed since
the last load; decide whether that is expected before going further.

Check what landed:

```bash
psql "$DATABASE_URL" -c "select load_id, table_name, row_count, source_modified_at, loaded_at from bronze.load_log order by load_id;"
```

Run the same load command again. Every file should report `skipped`, because nothing
changed since the last load.

**Updating the code later** to a new release:

```bash
cd ~/warehouse && git fetch --tags && git checkout vX.Y.Z && uv sync && uv run python -m ingest init-db
```

`git checkout` of a tag leaves a detached HEAD. That is expected: the VM runs a named
release, never a moving branch.

## 9. Backups

- A Proxmox backup of this VM contains the real data. Send it only to a restricted target.
  Proxmox Backup Server with client-side encryption is the best option.
- The backup must include `/srv/warehouse/archive`. A whole-VM backup does.
- A scheduled `pg_dump` arrives with scheduling, when loads stop being run by hand.

## Before loading live data

- [ ] Approval from the data owner to store this data on this server.
- [ ] Disk encryption in place: LUKS in the VM, or encrypted Proxmox storage.
- [ ] SSH keys only, root login off, firewall limited to `ADMIN_SUBNET`.
- [ ] PostgreSQL listening on localhost only.
- [ ] Share account is read-only and dedicated; `smb.cred` is mode 600.
- [ ] SMB encryption (`seal`) working, or IT has accepted the alternative in writing.
- [ ] Backups go to a restricted, encrypted target.
- [ ] Only named administrators have VM logins or Proxmox access to this VM.
