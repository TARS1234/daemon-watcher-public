# DAEMON WATCHER

**Turn any machine with a camera into a live surveillance node. Controlled entirely from Telegram. No subscriptions. No cloud. No BS.**

Run it on your laptop, a spare Mac, a Raspberry Pi — anything with a camera. Get motion alerts, snapshots, and video clips straight to your phone. Add a second machine and they find each other automatically. Everything is configured by texting your bot.

---

## WHAT IT DOES

- Detects motion and sends you a photo + video instantly via Telegram
- Runs on any machine — Mac, Linux, Windows, Raspberry Pi
- Control everything from Telegram — no app, no dashboard, no login
- Multi-node: run on 5 machines, they sync and stay aware of each other
- No mandatory cloud — your data goes from your camera to your Telegram, nowhere else
- One-time setup, runs forever

---

## SETUP IN 5 MINUTES

### Step 1 — Get a Telegram bot (2 min)

- Message **@BotFather** → `/newbot` → copy the token
- Message **@userinfobot** → `/start` → copy your Chat ID

### Step 2 — Install

```bash
python3 install_wizard.py
```

Four prompts: passcode, bot token, chat ID, machine name. Done. The daemon starts automatically.

---

## CONTROL FROM TELEGRAM

Everything runs through your bot. No interface to open, no config file to edit.

| Command | What happens |
|---------|-------------|
| `/snap` | Sends a snapshot from every camera right now |
| `/watch` | Records and sends a video clip right now |
| `/status` | Every node reports its live status |
| `/edit` | View current settings on every node |
| `/edit 1 20` | Change video clip length to 20s on all nodes |
| `/edit OFFICE 4 0.3` | Set motion sensitivity on OFFICE only |
| `/logs` | View recent activity |
| `/kill` | Shut down the daemon |
| `/help` | Show all commands |

Target any machine by name — put the machine name anywhere in the command:

```
/snap OFFICE            → snapshot from OFFICE only
/edit OFFICE 6 high     → set video quality to high on OFFICE
/status OFFICE          → get live status from OFFICE
```

---

## SETTINGS

| # | Setting | Values |
|--:|---------|--------|
| 1 | Video clip length | 5–30 seconds |
| 2 | Record video on motion | `true` / `false` |
| 3 | Alert hours only | `true` / `false` |
| 4 | Motion sensitivity | 0.0–1.0 |
| 5 | Snapshot quality | 50–100 |
| 6 | Video quality | `low` / `medium` / `high` |
| 7 | Cooldown between alerts | 30–300 seconds |
| 8 | Alert text | any text |
| 9 | Send snapshot on motion | `true` / `false` |
| 10 | Check interval | 1–60 seconds |
| 11 | Passcode | 6–16 alphanumeric |

---

## MULTI-NODE

Add Daemon Watcher to a second machine using the same bot token and chat ID. They discover each other on the same network automatically — no config, no pairing, nothing to set up. Both machines appear in `/nodes` within seconds.

```
/snap               → snapshots from both
/snap KITCHEN       → snapshot from KITCHEN only
/watch OFFICE       → video from OFFICE only
```

**Cross-network (optional):** if your machines are on different networks, you can run `relay_server.py` on any internet-accessible server to bridge them. See the advanced section below.

---

## CAMERA DETECTION

On startup, Daemon Watcher scans all available cameras and picks the best one automatically — it runs a brightness and variance test to skip idle or dark cameras. If you want to lock in a specific camera:

```
/edit 15 1      → pin camera index 1
/edit 15 -1     → back to auto
```

---

## ADVANCED: CROSS-NETWORK RELAY

Only needed if your nodes are on **different networks** (home + office, different cities). Host `relay_server.py` on any internet-accessible machine — a cheap VPS, a home server, or a free Render instance.

**Start the relay:**
```bash
python3 relay_server.py --host 0.0.0.0 --port 8000
```

**Add one line to each node's config** (`~/.daemon_watcher/daemon_config_<hostname>_local.yaml`):
```yaml
daemon:
  relay_url: https://your-server-domain.com
```

Restart the daemon. Nodes will find each other across networks within 30 seconds. No new credentials — the relay uses your existing bot token to namespace your nodes.

**Verify:**
```bash
curl https://your-server-domain.com/health
# {"ok": true, "namespaces": 1, "nodes": 2}
```

---

## TROUBLESHOOTING

**No motion alerts:**
- Lower the sensitivity: `/edit 4 0.3` (lower = more sensitive)
- Run `/snap` to confirm the camera is working

**Camera not detected:**
- Run `/snap` and check the log for brightness readings
- Pin a specific index: `/edit 15 1`
- If using a Mac, disconnect iPhone Continuity Camera from System Settings

**Node shows offline:**
- Confirm both nodes use the same bot token and chat ID
- Check heartbeat interval: `/edit 16 15`
- For cross-network nodes, configure a relay (see above)

**Telegram not connecting:**
- Verify bot token from @BotFather and chat ID from @userinfobot

**Relay not syncing:**
- Test: `curl https://your-relay-domain.com/health`
- Confirm `relay_url` is set in the config on **all** nodes
- Both nodes must use the same bot token and chat ID

---

## LEGAL

Video and audio surveillance laws vary by location. You are responsible for ensuring your use of this system complies with all applicable local, state, and federal laws. In some jurisdictions, recording without consent is illegal.

---

**Any machine. Any camera. Total control from your phone. No mandatory cloud.**
