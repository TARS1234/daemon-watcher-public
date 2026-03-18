# DAEMON WATCHER

Multi-node motion surveillance daemon. Runs on any machine with a camera. Controlled entirely via Telegram. Nodes stay in sync automatically via a built-in heartbeat mesh.

---

## SETUP (5 Minutes)

### 1. Get Telegram Credentials

**Bot Token:**
- Open Telegram → find @BotFather → send `/newbot`
- Copy the token

**Chat ID:**
- Open Telegram → find @userinfobot → send `/start`
- Copy your Chat ID number

### 2. Run Install Wizard

```
python3 install_wizard.py
```

Follow 4 steps:
1. Create a passcode (6-16 characters)
2. Paste Telegram bot token
3. Paste Telegram chat ID
4. Name your machine (optional)

Done. Daemon starts automatically.

---

## CONTROL VIA TELEGRAM

Unqualified commands run on every node. Targeted commands run only on the named machine.

| Command | What it does |
|---------|-------------|
| `/edit` | Show settings for every node (each responds) |
| `/edit 1 20` | Change video duration to 20s on every node |
| `/edit BEAST 1 20` | Change video duration on BEAST only |
| `/edit 1 BEAST 20` | Same — order of machine name and number is flexible |
| `/status` | Every node reports its own live status |
| `/status BEAST` | Only BEAST responds with its live status |
| `/nodes` | List all known nodes and online/offline state |
| `/snap` | Take a snapshot on every node |
| `/snap BEAST` | Take a snapshot on BEAST only |
| `/watch` | Record video now on every node |
| `/watch BEAST` | Record video on BEAST only |
| `/test` | Send a test alert |
| `/logs` | View recent log lines |
| `/kill` | Stop this daemon |
| `/help` | Show all commands |

---

## SETTINGS (`/edit` numbers)

| # | Setting | Options |
|---|---------|---------|
| 1 | Video duration | 5–30 seconds |
| 2 | Record video on motion | true/false |
| 3 | Alert hours only | true/false |
| 4 | Motion sensitivity | 0.0–1.0 |
| 5 | Snapshot quality | 50–100 |
| 6 | Video quality | low/medium/high |
| 7 | Cooldown between alerts | 30–300 seconds |
| 8 | Alert text | any text |
| 9 | Send snapshot on motion | true/false |
| 10 | Check interval | 1–60 seconds |
| 11 | Passcode | 6–16 alphanumeric |
| 12 | Machine name | any name |
| 13 | Edit machine target | machine name |
| 14 | — | `/nodes` |
| 15 | Camera index | -1=auto, 0/1/2=pin specific |
| 16 | Heartbeat interval | 5–60 seconds |

---

## MULTI-NODE MESH

Multiple machines share the same Telegram bot and chat. Each node runs its own daemon with its own config. They discover each other automatically — no relay required for nodes on the same network.

**How sync works:**

| Layer | Mechanism | Scope | Setup required |
|-------|-----------|-------|----------------|
| 1 | UDP broadcast (port 7779) | Same LAN — instant, ~15s | None |
| 2 | Shared filesystem (`heartbeat.json`) | USB/NFS mounts only | Mount a shared drive |
| 3 | Relay server | Any network — ~30s | Optional, see below |

A `NodeSyncWorker` on each machine checks peers every 30 seconds and marks a node offline after 3 missed heartbeats. Machine names persist in a local `state.json` and survive config resets and restarts.

**For most setups (same network), no relay is needed.** Nodes discover each other via UDP automatically within one heartbeat interval.

---

### Cross-network relay (optional, advanced)

Only needed if your nodes are on **different networks** (e.g. home + office). You must host this yourself — on any machine that's accessible from the internet (a cheap VPS, a home server with port forwarding, or a free cloud instance).

**Step 1 — Start the relay on your server:**

```
python3 relay_server.py --host 0.0.0.0 --port 8000
```

The relay uses no database. All state is in memory and expires automatically. Restart it any time — nodes reconnect within one heartbeat interval.

**Step 2 — Add one line to each node's config:**

Edit `~/.daemon_watcher/daemon_config_<hostname>_local.yaml` on each machine:

```yaml
daemon:
  relay_url: https://your-server-domain.com
```

Then restart the daemon. Each node will push its heartbeat to the relay every 15 seconds using the Telegram credentials it already has — no new accounts or tokens needed. Nodes on the same LAN still use UDP as the primary path; the relay is only the cross-network fallback.

**Verify it's working:**

```
curl https://your-server-domain.com/health
# → {"ok": true, "namespaces": 1, "nodes": 2}
```

Once both nodes are posting, `/nodes` will show them both online within one reconcile cycle (~30s).

**Note on free hosting (e.g. Render free tier):** the relay process spins down after 15 minutes of inactivity and loses its in-memory state. Nodes reconnect and re-register automatically on the next heartbeat — expect a one-time ~30–60s delay after a cold start. Paid tiers stay always-on.

**Targeting commands:**
```
/edit BEAST 6 high         # set video quality to high on BEAST only
/edit MONSTER 15 1         # pin camera to index 1 on MONSTER only
/snap BEAST                # take snapshot from BEAST only
/watch MONSTER             # queue a recording on MONSTER only
/status BEAST              # get live status from BEAST only
```

Targeted commands work via Telegram as the shared context — the named machine self-applies the change and confirms. All other nodes stay silent.

**Renaming a node:**
```
/edit 12 BEAST             # rename this node to BEAST
/edit MONSTER 12 BEAST     # rename MONSTER to BEAST
```
The rename persists to `state.json` on the target machine and propagates to all nodes via the next heartbeat.

---

## CAMERA DETECTION

On startup, each node automatically finds the best available camera using a 10-frame warmup + brightness/variance scan:
- Idle or dark cameras (e.g. iPhone Continuity Camera) are skipped
- The camera with the highest live-frame variance is selected
- Pin a specific camera index with `/edit 15 <index>` if needed

---

## RECORDING NOTICE

⚠️ Video and audio surveillance laws vary by location. In some jurisdictions, recording individuals without consent — including video in private spaces or audio in any setting — is illegal. In one-party consent regions, only one participant must consent. In all-party consent regions, everyone being recorded must consent. You are responsible for ensuring your use of this system complies with all applicable local, state, and federal laws.

---

## TROUBLESHOOTING

**Camera not starting:**
- Run `/snap` to test — check the log for brightness readings
- If an iPhone Continuity Camera is hijacking the feed, pin the correct index: `/edit 15 1`
- Disconnect unused iPhone Continuity Camera sources from System Settings

**Telegram not connecting:**
- Verify token from @BotFather and chat ID from @userinfobot

**Node shows offline but is running:**
- Check heartbeat interval: `/edit 16 15`
- Ensure both nodes use the same Telegram bot token and chat ID
- If nodes are on different networks, a relay server is required (see Cross-network relay above)

**UDP heartbeat failing (No route to host):**
- This can happen on some network configs — the system falls back to other sources automatically
- Nodes on the same LAN will still discover each other within one heartbeat interval

**Relay not syncing (if configured):**
- Test the relay is reachable: `curl https://your-relay-domain.com/health`
- Confirm `daemon.relay_url` is set correctly in **both** `~/.daemon_watcher/daemon_config_<hostname>_local.yaml` and `~/.daemon_watcher_nodes/<hostname>/daemon_config.yaml` on each machine (the sync config overrides the local config)
- Check logs for `[Heartbeat] Relay POST failed` or `[NodeSync] Relay poll failed`
- Both nodes must use the same Telegram bot token and chat ID — the relay uses these to namespace nodes
- On free hosting: a brief `Relay: 0 node(s)` after idle is normal — nodes recover on the next heartbeat

**Targeted command not responding:**
- Confirm the machine name matches exactly (case-insensitive): `/nodes` shows registered names
- If the target was recently renamed, wait one heartbeat interval for the name to propagate

**No motion detected:**
- Adjust sensitivity: `/edit 4 0.3` (lower = more sensitive)
- Check lighting and camera angle

---

**PLUG. INSTALL. WATCH.**
