#!/usr/bin/env python3
"""Daemon Watcher - Phase 1: USB Surveillance System with self-update, logo branding, machine tracking"""

import os, sys, platform, subprocess, json, yaml, time, logging, threading, signal, socket, shutil, base64
from collections import deque
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime
try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None

# BLACK CROW EMOJI (fallback if logo not found)
CROW_EMOJI = "🐦‍⬛"
# Heartbeat prefix — first line of every heartbeat message starts with this
HEARTBEAT_PREFIX = "🫀HB"
# Message schema version — increment when the envelope format changes
MSG_SCHEMA_VERSION = 1
# UDP port for LAN heartbeat broadcasts (node-to-node discovery across machines)
UDP_HEARTBEAT_PORT = 7779


def load_logo_base64(usb_mount: Path) -> Optional[str]:
    """Load daemon watcher logo as base64 from USB or repo"""
    logo_paths = [
        usb_mount / "daemon_watcher.jpg",
        usb_mount.parent / "daemon_watcher.jpg",
        Path.cwd() / "daemon_watcher.jpg",
        Path.home() / "motion-daemon" / "daemon_watcher.jpg",
    ]

    for logo_path in logo_paths:
        if logo_path.exists():
            try:
                with open(logo_path, 'rb') as f:
                    return base64.b64encode(f.read()).decode('utf-8')
            except Exception as e:
                pass
    return None


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"daemon_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger = logging.getLogger("daemon_watcher")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        logger.handlers.clear()
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


class SafeConfig:
    def __init__(self, shared_config_file: Path, local_config_file: Path, sync_config_file: Path, logger: logging.Logger):
        self.shared_config_file = shared_config_file
        self.local_config_file = local_config_file
        self.sync_config_file = sync_config_file
        self.logger = logger
        self.lock = threading.RLock()
        self.config = {}
        self.last_local_mtime = 0
        self.last_sync_mtime = 0
        self.load_from_disk()

    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        result = dict(base or {})
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _load_yaml(self, path: Path) -> Dict:
        try:
            if path.exists():
                with open(path, 'r') as f:
                    return yaml.safe_load(f) or {}
        except Exception:
            pass
        return {}

    def load_from_disk(self) -> None:
        with self.lock:
            try:
                shared_cfg = self._load_yaml(self.shared_config_file)
                local_cfg = self._load_yaml(self.local_config_file)
                sync_cfg = self._load_yaml(self.sync_config_file)

                merged = {}
                merged = self._deep_merge(merged, shared_cfg)
                merged = self._deep_merge(merged, local_cfg)
                merged = self._deep_merge(merged, sync_cfg)
                self.config = merged

                if self.local_config_file.exists():
                    self.last_local_mtime = self.local_config_file.stat().st_mtime
                if self.sync_config_file.exists():
                    self.last_sync_mtime = self.sync_config_file.stat().st_mtime
            except Exception as e:
                self.logger.error(f"Config load failed: {e}")

    def save_to_disk(self) -> None:
        with self.lock:
            try:
                self.local_config_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.local_config_file, 'w') as f:
                    yaml.dump(self.config, f, default_flow_style=False)

                self.sync_config_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.sync_config_file, 'w') as f:
                    yaml.dump(self.config, f, default_flow_style=False)

                if self.local_config_file.exists():
                    self.last_local_mtime = self.local_config_file.stat().st_mtime
                if self.sync_config_file.exists():
                    self.last_sync_mtime = self.sync_config_file.stat().st_mtime
            except Exception as e:
                self.logger.error(f"Config save failed: {e}")

    def reload_if_changed(self) -> bool:
        with self.lock:
            try:
                local_changed = self.local_config_file.exists() and self.local_config_file.stat().st_mtime > self.last_local_mtime
                sync_changed = self.sync_config_file.exists() and self.sync_config_file.stat().st_mtime > self.last_sync_mtime

                if not local_changed and not sync_changed:
                    return False

                self.load_from_disk()
                return True
            except Exception as e:
                self.logger.error(f"Config reload check failed: {e}")
                return False

    def get(self, path: str, default: Any = None) -> Any:
        with self.lock:
            keys = path.split('.')
            value = self.config
            try:
                for key in keys:
                    value = value[key]
                return value
            except (KeyError, TypeError):
                return default

    def set(self, path: str, value: Any) -> None:
        with self.lock:
            keys = path.split('.')
            config = self.config
            for key in keys[:-1]:
                if key not in config or not isinstance(config[key], dict):
                    config[key] = {}
                config = config[key]
            config[keys[-1]] = value
            self.save_to_disk()

    def update_all(self, new_config: Dict) -> None:
        with self.lock:
            self.config = new_config
            self.save_to_disk()


class VersionChecker:
    """Check for daemon updates"""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.current_version = "1.0.0"

    def get_current_version(self) -> str:
        return self.current_version

    def check_for_updates(self) -> Optional[str]:
        """Check GitHub releases for newer version"""
        try:
            import requests
            response = requests.get(
                "https://api.github.com/repos/TARS1234/daemon-watcher/releases/latest",
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                latest_version = data.get('tag_name', 'v1.0.0').lstrip('v')

                if self._version_newer(latest_version, self.current_version):
                    self.logger.info(f"Update available: {self.current_version} → {latest_version}")
                    return latest_version
        except Exception as e:
            self.logger.debug(f"Update check failed: {e}")

        return None

    def _version_newer(self, v1: str, v2: str) -> bool:
        """Compare semantic versions (v1 > v2)"""
        try:
            v1_parts = tuple(map(int, v1.split('.')))
            v2_parts = tuple(map(int, v2.split('.')))
            return v1_parts > v2_parts
        except:
            return False


class PasscodeManager:
    """Encrypt/decrypt and validate passcodes"""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.encryption_key = self._get_or_create_key()
        self.cipher = Fernet(self.encryption_key) if Fernet else None

    def _get_or_create_key(self) -> bytes:
        """Get encryption key from environment or create one"""
        key_str = os.environ.get('DAEMON_WATCHER_KEY')
        if key_str:
            return key_str.encode()
        import hashlib
        seed = f"{socket.gethostname()}-daemon-watcher-phase1".encode()
        key_hash = hashlib.sha256(seed).digest()[:32]
        import base64
        return base64.urlsafe_b64encode(key_hash)

    def encrypt_passcode(self, passcode: str) -> Optional[str]:
        """Encrypt passcode for storage"""
        if not self.cipher or not Fernet:
            self.logger.warning("Cryptography not available, passcode will be stored plaintext")
            return passcode
        try:
            encrypted = self.cipher.encrypt(passcode.encode())
            return encrypted.decode()
        except Exception as e:
            self.logger.error(f"Encryption failed: {e}")
            return None

    def decrypt_passcode(self, encrypted: str) -> Optional[str]:
        """Decrypt passcode from storage"""
        if not self.cipher or not Fernet:
            return encrypted
        try:
            decrypted = self.cipher.decrypt(encrypted.encode())
            return decrypted.decode()
        except Exception as e:
            self.logger.error(f"Decryption failed: {e}")
            return None

    def validate_passcode(self, input_passcode: str, stored_encrypted: str) -> bool:
        """Validate user input against stored encrypted passcode"""
        if not stored_encrypted:
            return False
        decrypted = self.decrypt_passcode(stored_encrypted)
        if not decrypted:
            return False
        return input_passcode == decrypted


class DependencyManager:
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def check_and_install_all(self) -> bool:
        deps = [
            ('cv2', 'opencv-python>=4.5.0'),
            ('requests', 'requests>=2.25.0'),
            ('yaml', 'pyyaml>=5.3'),
            ('PIL', 'pillow>=8.0.0'),
        ]

        for import_name, pip_name in deps:
            if not self._check_package(import_name):
                if not self._install_pip_package(pip_name):
                    return False
        return True

    def _check_package(self, package_name: str) -> bool:
        try:
            __import__(package_name)
            return True
        except ImportError:
            return False

    def _install_pip_package(self, package_name: str) -> bool:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", package_name],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except:
            return False


class CameraDetector:
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def find_best_camera(self) -> Optional[int]:
        try:
            import cv2
        except ImportError:
            return None
        candidates = []  # (brightness, frame_variance, camera_index)
        # Suppress OpenCV's internal stderr noise (e.g. "out device of bound") during probing.
        # VideoCapture() writes directly to fd 2 before we can check isOpened(); redirect
        # only for the constructor call, then restore immediately.
        import os as _os
        for camera_index in range(4):
            try:
                _null_fd = _os.open(_os.devnull, _os.O_WRONLY)
                _saved_stderr = _os.dup(2)
                _os.dup2(_null_fd, 2)
                _os.close(_null_fd)
                try:
                    cap = cv2.VideoCapture(camera_index)
                finally:
                    _os.dup2(_saved_stderr, 2)
                    _os.close(_saved_stderr)
                if not cap.isOpened():
                    continue
                # Warmup: collect frames to assess camera quality
                frames = []
                for _ in range(10):
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        frames.append(frame)
                    time.sleep(0.1)
                cap.release()
                if not frames:
                    continue
                last = frames[-1]
                h, w = last.shape[:2]
                b, g, r = cv2.mean(last)[:3]
                brightness = (b + g + r) / 3
                # Frame variance: live cameras change between reads (sensor noise);
                # idle/disconnected devices return identical frames
                frame_variance = 0.0
                if len(frames) >= 2:
                    diff = cv2.absdiff(frames[0], frames[-1])
                    frame_variance = cv2.mean(diff)[0]
                self.logger.info(f"  Camera index {camera_index}: {w}x{h}, brightness={brightness:.1f}, variance={frame_variance:.2f}")
                candidates.append((brightness, frame_variance, camera_index))
            except:
                continue
        if not candidates:
            self.logger.error("No camera found")
            return None
        # Prefer live cameras (variance > 0.5) with highest variance — variance measures
        # frame dynamism and is a better proxy for "real camera" than raw brightness.
        # iPhone Continuity Cameras often win on brightness but lose on variance.
        live = [(b, v, i) for b, v, i in candidates if v > 0.5]
        if live:
            best = max(live, key=lambda x: x[1])
            self.logger.info(f"✓ Found camera at index {best[2]} (brightness={best[0]:.1f}, variance={best[1]:.2f})")
            return best[2]
        # All cameras returning identical frames — fall back to brightest
        best = max(candidates, key=lambda x: x[0])
        self.logger.warning(
            f"No live camera detected (frames not changing) — using index {best[2]} as fallback. "
            f"Tip: set camera.index in config (or /edit 15 <index>) to pin a specific camera."
        )
        return best[2]


class MotionDetector:
    def __init__(self, config: SafeConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.last_frame = None
        self.is_running = False
        self.camera_index = None

    def start_monitoring(self, callback, camera_index: int, fps: int, resize_factor: float) -> None:
        try:
            import cv2
        except ImportError:
            return
        try:
            self.camera_index = camera_index
            cap = cv2.VideoCapture(camera_index)
            if not cap.isOpened():
                return
            self.logger.info(f"Camera opened, monitoring for motion")
            self.is_running = True
            frame_skip = 0
            target_skip = max(1, 30 // fps)
            while self.is_running:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(1)
                    continue
                frame_skip += 1
                if frame_skip < target_skip:
                    continue
                frame_skip = 0
                small_frame = cv2.resize(frame, (320, 240))
                if self.detect_motion(small_frame):
                    callback(frame, camera_index)
                self.last_frame = small_frame
                time.sleep(0.01)
        except Exception as e:
            self.logger.error(f"Motion detection error: {e}")
        finally:
            try:
                cap.release()
            except:
                pass

    def detect_motion(self, frame) -> bool:
        if self.last_frame is None:
            return False
        try:
            import cv2
        except ImportError:
            return False
        gray1 = cv2.cvtColor(self.last_frame, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray1 = cv2.GaussianBlur(gray1, (5, 5), 0)
        gray2 = cv2.GaussianBlur(gray2, (5, 5), 0)
        diff = cv2.absdiff(gray1, gray2)
        _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
        changed_pixels = cv2.countNonZero(thresh)
        total_pixels = thresh.shape[0] * thresh.shape[1]
        change_percentage = changed_pixels / total_pixels
        sensitivity = self.config.get('motion.sensitivity', 1.0)
        threshold = 1 - sensitivity
        return change_percentage > threshold

    def stop_monitoring(self) -> None:
        self.is_running = False


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, logger: logging.Logger, logo_base64: Optional[str] = None):
        self.token = token
        self.chat_id = chat_id
        self.logger = logger
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.logo_base64 = logo_base64
        self.crow = CROW_EMOJI

    def send_message(self, text: str, include_logo: bool = True) -> bool:
        try:
            import requests
            if include_logo:
                text = f"{self.crow} {text}"

            self.logger.debug(f"Sending message: {text[:50]}...")
            response = requests.post(f"{self.api_url}/sendMessage",
                json={"chat_id": self.chat_id, "text": text}, timeout=10)
            response.raise_for_status()
            self.logger.debug("Message sent successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send message: {e}")
            return False

    def send_photo(self, photo_path: str, caption: str = "") -> bool:
        try:
            import requests
            file_size = os.path.getsize(photo_path)
            self.logger.debug(f"Sending photo: {photo_path} ({file_size} bytes)")
            caption = f"{self.crow} {caption}"
            with open(photo_path, 'rb') as f:
                files = {'photo': f}
                data = {'chat_id': self.chat_id, 'caption': caption}
                response = requests.post(f"{self.api_url}/sendPhoto",
                    files=files, data=data, timeout=30)
                response.raise_for_status()
            self.logger.debug("Photo sent successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send photo: {e}")
            return False

    def send_video(self, video_path: str, caption: str = "") -> bool:
        try:
            import requests
            file_size = os.path.getsize(video_path)
            self.logger.info(f"Uploading video: {file_size / 1024 / 1024:.2f}MB")

            # 50MB SAFETY GATE
            if file_size > 50 * 1024 * 1024:
                self.logger.error(f"Video too large: {file_size / 1024 / 1024:.2f}MB (max 50MB)")
                self.send_message(
                    f"File too large ({file_size / 1024 / 1024:.1f}MB). "
                    f"Video discarded. Increase video quality or reduce duration.",
                    include_logo=True
                )
                return False

            caption = f"{self.crow} {caption}"
            with open(video_path, 'rb') as f:
                files = {'video': f}
                data = {'chat_id': self.chat_id, 'caption': caption}
                self.logger.debug("Uploading to Telegram API...")
                response = requests.post(f"{self.api_url}/sendVideo",
                    files=files, data=data, timeout=120)

                if response.status_code != 200:
                    self.logger.error(f"Telegram API error: {response.text}")

                response.raise_for_status()

            self.logger.info("Video uploaded successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send video: {type(e).__name__}: {e}")
            return False

    def send_photo_with_caption(self, photo_bytes: bytes, caption: str) -> bool:
        """Send photo from bytes (used for logo)"""
        try:
            import requests
            caption = f"{self.crow} {caption}"
            files = {'photo': ('logo.jpg', photo_bytes)}
            data = {'chat_id': self.chat_id, 'caption': caption}
            response = requests.post(f"{self.api_url}/sendPhoto",
                files=files, data=data, timeout=30)
            response.raise_for_status()
            return True
        except Exception as e:
            self.logger.error(f"Failed to send logo: {e}")
            return False

    def test_connection(self) -> bool:
        try:
            import requests
            response = requests.get(f"{self.api_url}/getMe", timeout=5)
            data = response.json()
            if data.get('ok'):
                self.logger.info(f"✓ Telegram bot connected: {data['result']['first_name']}")
                return True
        except Exception as e:
            self.logger.error(f"Telegram connection failed: {e}")
        return False


CONFIG_MAP = {
    "1": ("motion.video_duration", "int", "5-30"),
    "2": ("motion.video_on_motion", "bool", "true/false"),
    "3": ("motion.alert_hours.enabled", "bool", "true/false"),
    "4": ("motion.sensitivity", "float", "0.0-1.0"),
    "5": ("motion.snapshot_quality", "int", "50-100"),
    "6": ("motion.video_quality", "string", "low/medium/high"),
    "7": ("motion.cooldown", "int", "30-300"),
    "8": ("motion.alert_text", "string", "any text"),
    "9": ("motion.snapshot", "bool", "true/false"),
    "10": ("daemon.check_interval", "int", "1-60"),
    "11": ("security.passcode", "string", "6-16 alphanumeric"),
}

# Numeric (int/float) range enforcement — values outside range are rejected with an error.
CONFIG_RANGES = {
    "1":  (5, 30),
    "4":  (0.0, 1.0),
    "5":  (50, 100),
    "7":  (30, 300),
    "10": (1, 60),
}


class MachineRegistry:
    def __init__(self, registry_file: Path, logger: logging.Logger):
        self.registry_file = registry_file
        self.logger = logger
        self.lock = threading.RLock()

    def load(self) -> Dict:
        with self.lock:
            try:
                if self.registry_file.exists():
                    with open(self.registry_file, 'r') as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            return data
            except Exception as e:
                self.logger.error(f"Registry load failed: {e}")
            return {"machines": {}}

    def save(self, data: Dict) -> None:
        with self.lock:
            try:
                self.registry_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.registry_file, 'w') as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                self.logger.error(f"Registry save failed: {e}")

    def upsert_machine(self, machine_id: str, payload: Dict) -> None:
        data = self.load()
        data.setdefault("machines", {})
        existing = data["machines"].get(machine_id, {})
        existing.update(payload)
        data["machines"][machine_id] = existing
        self.save(data)

    def get_all(self) -> Dict:
        return self.load().get("machines", {})

    def find_machine(self, target: str) -> Optional[Dict]:
        target = str(target).strip().lower()
        machines = self.get_all()
        for machine_id, machine in machines.items():
            names = {
                machine_id.lower(),
                str(machine.get("hostname", "")).lower(),
                str(machine.get("custom_name", "")).lower(),
            }
            if target in names:
                result = dict(machine)
                result["machine_id"] = machine_id
                return result
        return None


class HeartbeatManager:
    """Broadcasts this node's status via Telegram every N seconds so other nodes can stay in sync."""

    def __init__(self, token: str, chat_id: str, daemon, safe_config, logger: logging.Logger):
        self.token = token
        self.chat_id = chat_id
        self.daemon = daemon
        self.safe_config = safe_config
        self.logger = logger
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.is_running = False
        self.message_id = self._load_message_id()

    def _msg_id_file(self) -> Path:
        return self.daemon.machine_dir / ".heartbeat_msg_id"

    def _load_message_id(self) -> Optional[int]:
        """Tiny helper: load persisted heartbeat message_id so we edit instead of spam."""
        try:
            f = self._msg_id_file()
            if f.exists():
                return int(f.read_text().strip())
        except Exception:
            pass
        return None

    def _save_message_id(self, msg_id: int) -> None:
        try:
            self._msg_id_file().parent.mkdir(parents=True, exist_ok=True)
            self._msg_id_file().write_text(str(msg_id))
        except Exception as e:
            self.logger.error(f"[Heartbeat ERROR] Failed to save message_id: {e}")

    def _build_text(self) -> str:
        name     = self.daemon.get_machine_name()
        host     = self.daemon.hostname
        plat     = platform.system()
        running  = self.daemon.is_running
        status   = "🟢 Online" if running else "🔴 Offline"
        ts_str   = datetime.now().strftime("%a %b %d  ·  %H:%M:%S")

        return (
            f"🫀HB {name}\n"
            f"{status}  ·  {plat}\n"
            f"📍 {host}\n"
            f"🕐 {ts_str}"
        )

    @staticmethod
    def _validate(payload: dict) -> bool:
        """Tiny helper: validate required heartbeat fields before applying. Signal on failure."""
        required = {"id", "ts", "run", "type"}
        missing = required - payload.keys()
        if missing:
            return False
        if payload.get("type") != "hb":
            return False
        if not isinstance(payload.get("ts"), (int, float)):
            return False
        if not isinstance(payload.get("id"), str) or not payload["id"]:
            return False
        return True

    def _write_local_heartbeat(self) -> None:
        """Write this node's status to heartbeat.json on the shared filesystem.
        This is the primary mechanism other nodes use to detect online/offline state."""
        try:
            hb = {
                "machine_id": self.daemon.machine_id,
                "custom_name": self.daemon.get_machine_name(),
                "hostname": self.daemon.hostname,
                "platform": platform.system(),
                "is_running": self.daemon.is_running,
                "last_seen": time.time(),
            }
            hb_file = self.daemon.machine_dir / "heartbeat.json"
            hb_file.parent.mkdir(parents=True, exist_ok=True)
            with open(hb_file, 'w') as f:
                json.dump(hb, f)
            self.logger.debug(f"[Heartbeat] ✓ Local heartbeat written → {hb_file.name}")
        except Exception as e:
            self.logger.error(f"[Heartbeat ERROR] _write_local_heartbeat failed: {e}")

    @staticmethod
    def _get_broadcast_address() -> str:
        """Get the subnet broadcast address for the active interface.
        Uses a UDP connect trick — no packets are sent, just gets the routing decision.
        Falls back to 255.255.255.255 if unable to determine."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            local_ip = s.getsockname()[0]
            s.close()
            parts = local_ip.split('.')
            return f"{parts[0]}.{parts[1]}.{parts[2]}.255"
        except Exception:
            return '255.255.255.255'

    def _send_udp_broadcast(self) -> None:
        """Tiny helper: broadcast this node's status via UDP to all LAN peers.
        Works across different machines without a shared filesystem."""
        try:
            port = self.safe_config.get('daemon.heartbeat_port', UDP_HEARTBEAT_PORT)
            payload = json.dumps({
                "machine_id": self.daemon.machine_id,
                "custom_name": self.daemon.get_machine_name(),
                "hostname": self.daemon.hostname,
                "platform": platform.system(),
                "is_running": self.daemon.is_running,
                "last_seen": time.time(),
            }).encode()
            broadcast_addr = self._get_broadcast_address()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(1.0)
            sock.sendto(payload, (broadcast_addr, port))
            sock.close()
            self.logger.debug(f"[Heartbeat] UDP broadcast sent → {broadcast_addr}:{port}")
        except Exception as e:
            self.logger.error(f"[Heartbeat ERROR] UDP broadcast failed: {e}")

    def _send_relay_heartbeat(self) -> None:
        """Push this node's status to the relay for cross-network peers.
        No-op if daemon.relay_url is not configured."""
        relay_url = self.safe_config.get('daemon.relay_url', '').strip()
        if not relay_url:
            return
        try:
            import requests as _requests
            payload = {
                "chat_id":     self.chat_id,
                "machine_id":  self.daemon.machine_id,
                "custom_name": self.daemon.get_machine_name(),
                "hostname":    self.daemon.hostname,
                "platform":    platform.system(),
                "is_running":  self.daemon.is_running,
                "last_seen":   time.time(),
            }
            r = _requests.post(
                f"{relay_url.rstrip('/')}/heartbeat",
                json=payload,
                headers={"X-Bot-Token": self.token},
                timeout=5,
            )
            if r.status_code >= 500:
                self._relay_confirmed = False
                self.logger.warning(f"[Heartbeat] Relay POST failed: HTTP {r.status_code} (server error)")
                return
            if r.status_code != 200:
                self._relay_confirmed = False
                self.logger.warning(f"[Heartbeat] Relay POST failed: HTTP {r.status_code}")
                return
            if not getattr(self, '_relay_confirmed', False):
                self.logger.info(f"[Heartbeat] ✓ Relay connected ({relay_url})")
                self._relay_confirmed = True
            else:
                self.logger.debug("[Heartbeat] ✓ Relay updated")
        except _requests.exceptions.Timeout:
            self._relay_confirmed = False
            self.logger.warning("[Heartbeat] Relay POST timeout")
        except Exception as e:
            self._relay_confirmed = False   # reset so reconnect is logged
            self.logger.warning(f"[Heartbeat] Relay send failed: {e}")

    def send(self) -> None:
        name = self.daemon.get_machine_name()
        self.logger.info(f"[Heartbeat] ♥ {name} — broadcasting")
        try:
            # PRIMARY: UDP broadcast to all LAN nodes (works across different machines)
            self._send_udp_broadcast()
            # SECONDARY: relay for cross-network nodes
            self._send_relay_heartbeat()
            # TERTIARY: write heartbeat file for nodes on a shared filesystem
            self._write_local_heartbeat()

            # DISPLAY: update the Telegram message so humans can see node status in chat
            import requests
            text = self._build_text()
            if self.message_id:
                resp = requests.post(
                    f"{self.api_url}/editMessageText",
                    json={"chat_id": self.chat_id, "message_id": self.message_id, "text": text},
                    timeout=10
                )
                if resp.status_code == 200:
                    self.logger.info(f"[Heartbeat] ✓ Telegram updated (msg_id={self.message_id})")
                    return
                self.logger.debug(f"[Heartbeat] Edit failed ({resp.status_code}), sending fresh")
                self.message_id = None  # message gone, send fresh
            resp = requests.post(
                f"{self.api_url}/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "disable_notification": True},
                timeout=10
            )
            if resp.status_code == 200:
                self.message_id = resp.json()['result']['message_id']
                self._save_message_id(self.message_id)
                self.logger.info(f"[Heartbeat] ✓ Telegram message created (id={self.message_id})")
            else:
                self.logger.error(f"[Heartbeat ERROR] sendMessage failed: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            self.logger.error(f"[Heartbeat ERROR] send failed: {e}")

    def run(self) -> None:
        self.is_running = True
        interval  = self.safe_config.get('daemon.heartbeat_interval', 15)
        relay_url = self.safe_config.get('daemon.relay_url', '').strip()
        self.logger.info(
            f"[Heartbeat] ✓ Started (interval={interval}s, "
            f"relay={'enabled' if relay_url else 'not configured'})"
        )
        while self.is_running:
            self.send()
            interval = self.safe_config.get('daemon.heartbeat_interval', 15)
            time.sleep(interval)

    def stop(self) -> None:
        self.is_running = False

    @staticmethod
    def parse(text: str) -> Optional[dict]:
        """Tiny helper: parse a human-readable heartbeat message, return payload dict or None."""
        try:
            lines = text.strip().splitlines()
            if len(lines) < 3:
                return None
            # Line 0: "🫀HB <name>"
            if not lines[0].startswith(HEARTBEAT_PREFIX + " "):
                return None
            name = lines[0][len(HEARTBEAT_PREFIX) + 1:].strip()

            # Line 1: "🟢 Online  ·  Darwin"  or  "🔴 Offline  ·  Darwin"
            run = lines[1].startswith("🟢")
            plat_part = lines[1].split("·", 1)
            plat = plat_part[1].strip() if len(plat_part) > 1 else ""

            # Line 2: "📍 my-machine.local"
            host = lines[2].lstrip("📍").strip()

            # Derive machine_id the same way _get_machine_id() does
            machine_id = host.replace(".", "_").replace(" ", "_")

            return {
                "v": MSG_SCHEMA_VERSION,
                "type": "hb",
                "id": machine_id,
                "name": name,
                "host": host,
                "plat": plat,
                "run": run,
                "ts": time.time(),   # use receipt time as last_seen — accurate enough
            }
        except Exception:
            pass
        return None


class NodeSyncWorker:
    """Background worker on each machine: syncs node status by reading peer heartbeat.json
    files from the shared filesystem. Runs at 2x heartbeat interval.
    Three missed heartbeats (stale file) = node considered offline."""

    PULSE_INTERVAL = 60  # seconds between periodic relay "still alive" INFO logs per peer

    def __init__(self, daemon, safe_config, logger: logging.Logger):
        self.daemon = daemon
        self.safe_config = safe_config
        self.logger = logger
        self.is_running = False
        self._relay_pulse: dict = {}  # machine_id → last relay INFO log timestamp

    def run(self) -> None:
        self.is_running = True
        self.logger.info("[NodeSync] ✓ Started")
        while self.is_running:
            try:
                self._reconcile()
            except Exception as e:
                self.logger.error(f"[NodeSync ERROR] reconcile failed: {e}")
            interval = self.safe_config.get('daemon.heartbeat_interval', 15)
            time.sleep(interval * 2)

    def stop(self) -> None:
        self.is_running = False

    def _poll_relay(self) -> dict:
        """Fetch all peer statuses from the relay. Returns {} if relay not configured or unreachable."""
        relay_url = self.safe_config.get('daemon.relay_url', '').strip()
        if not relay_url:
            return {}
        try:
            import requests as _requests
            token   = self.safe_config.get('telegram.token', '')
            chat_id = self.safe_config.get('telegram.chat_id', '')
            resp = _requests.get(
                f"{relay_url.rstrip('/')}/nodes",
                params={"chat_id": chat_id},
                headers={"X-Bot-Token": token},
                timeout=5,
            )
            if resp.status_code == 200:
                nodes = resp.json().get('nodes', {})
                prev_count = getattr(self, '_relay_poll_last_count', -1)
                if len(nodes) != prev_count:
                    names = [v.get('custom_name') or mid for mid, v in nodes.items()]
                    self.logger.info(f"[NodeSync] Relay: {len(nodes)} node(s) — {', '.join(names) or 'none'}")
                else:
                    self.logger.debug(f"[NodeSync] Relay poll: {len(nodes)} node(s)")
                self._relay_poll_last_count = len(nodes)
                return nodes
            if resp.status_code >= 500:
                self.logger.warning(f"[NodeSync] Relay poll failed: HTTP {resp.status_code} (server error) — falling back to registry")
            else:
                self.logger.warning(f"[NodeSync] Relay poll failed: HTTP {resp.status_code}")
        except Exception as e:
            if "timed out" in str(e).lower() or "timeout" in type(e).__name__.lower():
                self.logger.warning("[NodeSync] Relay poll timeout — falling back to registry")
            else:
                self.logger.debug(f"[NodeSync] Relay poll failed: {e}")
        return {}

    def _reconcile(self) -> None:
        """Audit peer liveness and update local registry.

        Source precedence per peer (first match wins):
          1. heartbeat.json on a shared filesystem (USB/NFS mounts)
               → highest trust; direct file written by the peer
          2. relay API — cross-network, requires daemon.relay_url in config
               → fallback for nodes on different networks; stale_after = interval*6
          3. registry last_seen — kept fresh by UDPHeartbeatReceiver (same LAN)
               → UDP wins on same LAN; this is the cold-start historical state

        UDP (UDPHeartbeatReceiver) updates the registry directly and is the
        primary same-LAN path. _reconcile() is the auditor that catches stale
        nodes and promotes relay data for cross-network peers.

        All writes go through upsert_machine() so they never overwrite a
        concurrent fresher update written by _process_heartbeat.
        """
        now = time.time()
        interval = self.safe_config.get('daemon.heartbeat_interval', 15)
        stale_after = interval * 3  # 3 missed heartbeats = offline

        # Read a snapshot just to get the list of known peers.
        # Per-machine liveness decisions re-read live data before writing.
        machines = self.daemon.registry.get_all()

        # Poll relay once for all peers (one HTTP call per reconcile cycle)
        relay_nodes = self._poll_relay()

        for machine_id, machine in list(machines.items()):
            if machine_id == self.daemon.machine_id:
                continue  # self is managed by update_registry()

            name = machine.get('custom_name') or machine.get('hostname') or machine_id

            # PRIMARY: shared filesystem heartbeat file (USB/NFS mount)
            hb_path = self.daemon.usb_mount / ".daemon_watcher_nodes" / machine_id / "heartbeat.json"
            if hb_path.exists():
                try:
                    with open(hb_path) as f:
                        hb = json.load(f)
                    last_seen = float(hb.get('last_seen', 0))
                    file_age = now - last_seen
                    now_running = hb.get('is_running', False) and (file_age <= stale_after)
                    was_running = machine.get('is_running', False)

                    update = {
                        "custom_name": hb.get('custom_name', machine.get('custom_name', machine_id)),
                        "hostname":    hb.get('hostname', machine.get('hostname', '')),
                        "platform":    hb.get('platform', machine.get('platform', '')),
                        "is_running":  now_running,
                        "last_seen":   last_seen,
                    }
                    self.daemon.registry.upsert_machine(machine_id, update)

                    if now_running != was_running:
                        state = "ONLINE" if now_running else "OFFLINE"
                        self.logger.info(
                            f"[NodeSync] {name} → {state} "
                            f"(source=heartbeat-file, age={file_age:.0f}s, threshold={stale_after:.0f}s)"
                        )
                    else:
                        self.logger.debug(
                            f"[NodeSync] {name}: {('online' if now_running else 'offline')} "
                            f"(source=heartbeat-file, age={file_age:.0f}s)"
                        )
                except Exception as e:
                    self.logger.error(f"[NodeSync ERROR] Reading heartbeat for {machine_id}: {e}")

            elif machine_id in relay_nodes:
                # SECONDARY: relay — cross-network heartbeat
                rd = relay_nodes[machine_id]
                relay_last_seen = float(rd.get('last_seen', 0))
                relay_age = int(now - relay_last_seen)
                relay_stale_after = interval * 6  # loosen for cross-network latency (matches relay TTL)
                relay_fresh = (now - relay_last_seen) <= relay_stale_after
                was_running = machine.get('is_running', False)
                now_running = rd.get('is_running', False) and relay_fresh
                if not relay_fresh:
                    self.logger.debug(
                        f"[NodeSync] {name}: stale relay data ignored "
                        f"(age={relay_age}s > threshold={relay_stale_after}s) — falling back to registry"
                    )

                update = {
                    "custom_name": rd.get('custom_name') or machine.get('custom_name', machine_id),
                    "hostname":    rd.get('hostname')    or machine.get('hostname', ''),
                    "platform":    rd.get('platform')    or machine.get('platform', ''),
                    "is_running":  now_running,
                    "last_seen":   relay_last_seen,
                }
                self.daemon.registry.upsert_machine(machine_id, update)

                if now_running != was_running:
                    state = "ONLINE" if now_running else "OFFLINE"
                    self.logger.info(
                        f"[NodeSync] {name} → {state} "
                        f"(source=relay, age={relay_age}s, threshold={int(relay_stale_after)}s)"
                    )
                    self._relay_pulse[machine_id] = time.time()
                elif now_running and time.time() - self._relay_pulse.get(machine_id, 0) >= self.PULSE_INTERVAL:
                    self.logger.info(f"[NodeSync] ♥ {name} (source=relay, age={relay_age}s)")
                    self._relay_pulse[machine_id] = time.time()
                else:
                    self.logger.debug(
                        f"[NodeSync] {name}: {'online' if now_running else 'offline'} "
                        f"(source=relay, age={relay_age}s)"
                    )

            else:
                # FALLBACK: no shared filesystem, no relay — use registry last_seen.
                # IMPORTANT: re-read the live registry entry here, not the loop snapshot.
                # UDPHeartbeatReceiver may have written a fresher last_seen since the
                # snapshot was taken at the top of this loop.
                was_running_snapshot = machine.get('is_running', False)
                live = self.daemon.registry.get_all().get(machine_id, machine)
                last_seen = float(live.get('last_seen', 0))
                age = int(now - last_seen)
                now_running = live.get('is_running', False)
                fresh = (now - last_seen) <= stale_after

                self.logger.debug(
                    f"[NodeSync] {name}: source=registry, last_seen={age}s ago, "
                    f"threshold={int(stale_after)}s, running={now_running}"
                )

                if now_running and not fresh:
                    # Three missed heartbeats — mark offline
                    self.daemon.registry.upsert_machine(machine_id, {'is_running': False})
                    self.logger.info(
                        f"[NodeSync] {name} → OFFLINE "
                        f"(source=registry, last_seen={age}s ago, threshold={int(stale_after)}s)"
                    )
                elif not was_running_snapshot and now_running and fresh:
                    # Was offline in snapshot, UDP updated last_seen while we slept — log recovery
                    self.logger.info(
                        f"[NodeSync] {name} → ONLINE "
                        f"(source=registry, last_seen={age}s ago)"
                    )

        # RELAY DISCOVERY: register machines seen in relay that aren't in the local registry yet.
        # This handles the cross-network case where two nodes have never shared a LAN and the
        # peer was never learned via UDP — the loop above only processes known machines.
        relay_stale_after = interval * 6
        for relay_mid, rd in relay_nodes.items():
            if relay_mid == self.daemon.machine_id or relay_mid in machines:
                continue
            relay_last_seen = float(rd.get('last_seen', 0))
            relay_age = int(now - relay_last_seen)
            now_running = rd.get('is_running', False) and (now - relay_last_seen) <= relay_stale_after
            name = rd.get('custom_name') or rd.get('hostname') or relay_mid
            entry = {
                "custom_name": rd.get('custom_name') or relay_mid,
                "hostname":    rd.get('hostname', ''),
                "platform":    rd.get('platform', ''),
                "is_running":  now_running,
                "last_seen":   relay_last_seen,
            }
            self.daemon.registry.upsert_machine(relay_mid, entry)
            state = "ONLINE" if now_running else "OFFLINE"
            self.logger.info(
                f"[NodeSync] {name} → {state} "
                f"(source=relay/discovered, age={relay_age}s)"
            )
            self._relay_pulse[relay_mid] = time.time()


class UDPHeartbeatReceiver:
    """Listens for UDP heartbeat broadcasts from other nodes on the LAN.
    Works across different machines without a shared filesystem."""

    PULSE_INTERVAL = 60  # seconds between periodic "still alive" INFO logs per peer

    def __init__(self, daemon, safe_config, logger: logging.Logger):
        self.daemon = daemon
        self.safe_config = safe_config
        self.logger = logger
        self.is_running = False
        self._last_pulse: dict = {}   # machine_id → last INFO log timestamp

    def run(self) -> None:
        self.is_running = True
        port = self.safe_config.get('daemon.heartbeat_port', UDP_HEARTBEAT_PORT)
        self.logger.info(f"[UDPReceiver] ✓ Listening on UDP port {port}")
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(2.0)
            sock.bind(('', port))
            while self.is_running:
                try:
                    data, addr = sock.recvfrom(4096)
                    payload = json.loads(data.decode())
                    machine_id = payload.get('machine_id')
                    if machine_id and machine_id != self.daemon.machine_id:
                        prev = self.daemon.registry.get_all().get(machine_id, {})
                        was_running = prev.get('is_running', False)
                        self.daemon.registry.upsert_machine(machine_id, payload)
                        name = payload.get('custom_name') or machine_id
                        now_running = payload.get('is_running', False)
                        if not was_running and now_running:
                            self.logger.info(f"[UDPReceiver] {name} → ONLINE (source=udp, from {addr[0]})")
                            self._last_pulse[machine_id] = time.time()
                        elif time.time() - self._last_pulse.get(machine_id, 0) >= self.PULSE_INTERVAL:
                            self.logger.info(f"[UDPReceiver] ♥ {name} (source=udp, from {addr[0]})")
                            self._last_pulse[machine_id] = time.time()
                        else:
                            self.logger.debug(f"[UDPReceiver] Heartbeat from {name} (source=udp, {addr[0]})")
                except socket.timeout:
                    continue
                except Exception as e:
                    self.logger.error(f"[UDPReceiver ERROR] {e}")
        except Exception as e:
            self.logger.error(f"[UDPReceiver ERROR] Failed to bind UDP port {port}: {e}")
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

    def stop(self) -> None:
        self.is_running = False


class TelegramCommandListener:
    # Handler dispatch table — maps command prefix → method name.
    # Add new commands here; no changes needed to handle_message.
    _HANDLERS = {
        "/edit":     "handle_edit",
        "/nodes":    "handle_nodes",
        "/node":     "handle_nodes",
        "/status":   "handle_status",
        "/watch":    "handle_watch",
        "/snap":     "handle_snap",
        "/test":     "handle_test",
        "/logs":     "handle_logs",
        "/kill":     "handle_kill",
        "/confirm":  "handle_confirm",
        "/passcode": "handle_passcode_attempt",
        "/help":     "handle_help",
    }
    # Max number of processed heartbeat msg IDs to track in memory
    _MAX_SEEN_IDS = 200

    def __init__(self, token: str, chat_id: str, daemon, safe_config, logger: logging.Logger):
        self.token = token
        self.chat_id = chat_id
        self.daemon = daemon
        self.safe_config = safe_config
        self.logger = logger
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.last_update_id = 0
        self.is_running = False
        self.pending_kill = False
        # Idempotency: track processed heartbeat msg IDs to prevent duplicate applies
        self._seen_msg_ids: deque = deque(maxlen=self._MAX_SEEN_IDS)
        self._seen_ids_set: set = set()

    def _is_duplicate(self, mid: str) -> bool:
        """Tiny helper: return True if this msg id was already processed (idempotency gate)."""
        if mid in self._seen_ids_set:
            return True
        # Track it — deque auto-evicts oldest when full, keep set in sync
        if len(self._seen_msg_ids) >= self._MAX_SEEN_IDS:
            evicted = self._seen_msg_ids[0]
            self._seen_ids_set.discard(evicted)
        self._seen_msg_ids.append(mid)
        self._seen_ids_set.add(mid)
        return False

    def poll_for_commands(self) -> None:
        self.is_running = True
        self.logger.info("Telegram listener active")
        while self.is_running:
            try:
                # PIPELINE: receive
                updates = self.get_updates()
                for update in updates:
                    # PIPELINE: decode — support both new messages and edits
                    # (heartbeats arrive as edited_message since they reuse one Telegram message)
                    msg_data = update.get('message') or update.get('edited_message') or {}
                    text = msg_data.get('text', '').strip()
                    if not text:
                        continue

                    # PIPELINE: route — separate node-to-node heartbeats from user commands
                    payload = HeartbeatManager.parse(text)
                    if payload is not None:
                        self.logger.debug(f"[Sync] ← Parsed heartbeat from {payload.get('name') or payload.get('id', '?')}")
                        # PIPELINE: validate → apply → log (handled inside _process_heartbeat)
                        self._process_heartbeat(payload)
                    else:
                        # PIPELINE: user command — route → apply → log (handled inside handle_message)
                        self.handle_message(text)
                # No sleep — re-poll immediately so the long-poll connection stays active.
                # The server-side timeout=10 handles the wait. A sleep here creates a gap
                # where this node has no active connection and can miss incoming commands.
            except Exception as e:
                self.logger.debug(f"Telegram polling error: {e}")
                time.sleep(5)  # Back off only on error

    def _process_heartbeat(self, payload: dict) -> None:
        """Pipeline: validate → stale-check → dedup → apply → log."""
        try:
            peer_name = payload.get('name') or payload.get('id', '?')

            # VALIDATE — reject malformed payloads before touching registry
            if not HeartbeatManager._validate(payload):
                self.logger.warning(
                    f"[Sync] Dropped invalid heartbeat from {peer_name} "
                    f"(missing/wrong fields): {list(payload.keys())}"
                )
                return

            machine_id = payload["id"]

            # ROUTE — ignore own heartbeats
            if machine_id == self.daemon.machine_id:
                return

            self.logger.info(f"[Sync] ← Heartbeat received from {peer_name}")
            self.logger.debug(f"[Sync]   validated ok — id={machine_id} run={payload.get('run')} ts={payload.get('ts'):.0f}")

            # STALE — reject messages older than 3× heartbeat interval
            stale_threshold = self.daemon.safe_config.get('daemon.heartbeat_interval', 15) * 3
            msg_age = time.time() - float(payload.get('ts', 0))
            if msg_age > stale_threshold:
                self.logger.debug(
                    f"[Sync] Stale heartbeat from {peer_name} ({msg_age:.0f}s old, "
                    f"threshold={stale_threshold}s) — skipped"
                )
                return

            # DEDUP — idempotency gate on msg id (present in v1+ schema; skip check for legacy)
            mid = payload.get("mid")
            if mid and self._is_duplicate(mid):
                self.logger.debug(f"[Sync] Duplicate mid={mid} from {peer_name} — skipped")
                return

            # APPLY — update local registry with latest state from this node
            entry = {
                "machine_id": machine_id,
                "custom_name": payload.get('name', machine_id),
                "hostname": payload.get('host', ''),
                "platform": payload.get('plat', ''),
                "is_running": payload.get('run', False),
                "last_seen": payload.get('ts', time.time()),
            }

            # Compute field-level diff for observability before writing
            existing = self.daemon.registry.get_all().get(machine_id, {})
            watch_fields = ("custom_name", "hostname", "platform", "is_running")
            diffs = [
                f"{f}: {existing.get(f)!r} → {entry.get(f)!r}"
                for f in watch_fields
                if existing.get(f) != entry.get(f)
            ]

            self.daemon.registry.upsert_machine(machine_id, entry)

            status = 'online' if payload.get('run') else 'offline'
            if diffs:
                self.logger.info(f"[Sync] ✓ {peer_name} ({status}) — changed: {', '.join(diffs)}")
            else:
                self.logger.info(f"[Sync] ✓ {peer_name} ({status}) — no field changes")
        except Exception as e:
            self.logger.error(f"[Sync ERROR] _process_heartbeat failed: {e}")

    def get_updates(self) -> list:
        try:
            import requests
            response = requests.get(f"{self.api_url}/getUpdates",
                json={"offset": self.last_update_id + 1, "timeout": 10}, timeout=15)
            data = response.json()
            updates = data.get('result', [])
            if updates:
                self.last_update_id = updates[-1]['update_id']
            return updates
        except:
            return []

    def send_message(self, text: str) -> bool:
        try:
            import requests
            response = requests.post(f"{self.api_url}/sendMessage",
                json={"chat_id": self.chat_id, "text": text}, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            self.logger.error(f"[TelegramCommandListener] send_message failed: {e}")
            return False

    def handle_message(self, text: str) -> None:
        """Route an incoming user command to its per-type handler via the dispatch table."""
        text = text.strip()
        if not text.startswith("/"):
            return
        cmd = text.split()[0].lower()
        handler_name = self._HANDLERS.get(cmd)
        if handler_name:
            self.logger.debug(f"[Command] route → {handler_name}  text={text[:60]}")
            getattr(self, handler_name)(text)
        else:
            self.logger.debug(f"[Command] unknown command: {cmd}")

    def handle_test(self, text: str) -> None:
        self.send_message(f"{CROW_EMOJI} [{self.daemon.get_machine_name()}] Test alert — online")

    def handle_kill(self, text: str) -> None:
        self.pending_kill = True
        self.send_message(f"{CROW_EMOJI} SELF-DESTRUCT?\n\nSend: /confirm yes\nOr: /confirm no")

    def handle_confirm(self, text: str) -> None:
        if self.pending_kill:
            if "yes" in text.lower():
                self.send_message(f"{CROW_EMOJI} DAEMON KILLED")
                self.daemon.is_running = False
            self.pending_kill = False

    def handle_help(self, text: str) -> None:
        msg = (
            f"{CROW_EMOJI} /edit - Show/change config\n"
            f"/edit <machine> <number> <value> - Edit specific machine\n"
            f"/status - All nodes status\n"
            f"/status <machine> - One node status\n"
            f"/nodes - Show nodes\n"
            f"/snap - Take snapshot from this machine\n"
            f"/snap <machine> - Take snapshot from specific machine\n"
            f"/watch - Record video from this machine\n"
            f"/watch <machine> - Queue watch on specific machine\n"
            f"/test - Test alert\n"
            f"/logs - Show logs\n"
            f"/kill - Self-destruct\n"
            f"/help - This"
        )
        self.send_message(msg)

    def handle_passcode_attempt(self, text: str) -> None:
        """Handle passcode validation attempts"""
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            self.send_message(f"{CROW_EMOJI} Usage: /passcode <code>")
            return

        attempt = parts[1].strip()
        stored_encrypted = self.safe_config.get('security.passcode', '')

        if not stored_encrypted:
            self.send_message(f"{CROW_EMOJI} Passcode not set. Please use installer to configure.")
            return

        if self.daemon.passcode_manager.validate_passcode(attempt, stored_encrypted):
            self.send_message(f"{CROW_EMOJI} Passcode correct! Daemon unlocked.")
            self.daemon.passcode_authenticated = True
        else:
            self.send_message(f"{CROW_EMOJI} Incorrect passcode. Try again.")
            self.daemon.passcode_attempts += 1
            if self.daemon.passcode_attempts >= 5:
                self.send_message(f"{CROW_EMOJI} Too many attempts. Daemon will shutdown in 30 seconds.")
                self.daemon.shutdown_timer = 30

    def _validate_range(self, idx: str, value) -> Optional[str]:
        """Return an error string if value is outside the allowed range, else None."""
        if idx not in CONFIG_RANGES:
            return None
        lo, hi = CONFIG_RANGES[idx]
        try:
            if not (lo <= value <= hi):
                return f"Value {value} out of range ({lo}–{hi})"
        except TypeError:
            pass
        return None

    def handle_edit(self, text: str) -> None:
        parts = text.split(maxsplit=3)

        if len(parts) == 1:
            target_name = self.daemon.get_machine_name()
            msg = f"{CROW_EMOJI} CONFIG [{target_name}]\n\n"
            for idx in sorted(CONFIG_MAP.keys(), key=lambda x: int(x)):
                if idx == "15":
                    msg += "14. nodes: /nodes\n"
                config_key = CONFIG_MAP[idx][0]
                value = self.safe_config.get(config_key)
                hint = f" ({CONFIG_MAP[idx][2]})" if CONFIG_MAP[idx][2] else ""
                msg += f"{idx}. {config_key}: {value}{hint}\n"
            msg += "\nSend: /edit <number> <value>"
            msg += "\nOr: /edit <machine> <number> <value>"
            self.send_message(msg)
            return

        if len(parts) == 3:
            idx = parts[1]
            value_str = parts[2]
            if idx not in CONFIG_MAP:
                self.send_message(f"Invalid: {idx}")
                return
            config_key, value_type, _ = CONFIG_MAP[idx]
            try:
                value = self.daemon.parse_config_value(value_type, value_str)
                err = self._validate_range(idx, value)
                if err:
                    self.send_message(f"{CROW_EMOJI} {err}")
                    return
                old = self.safe_config.get(config_key)
                if config_key == 'machine.custom_name':
                    self.daemon.set_machine_name(value)
                else:
                    self.safe_config.set(config_key, value)
                self.daemon.update_registry()
                self.send_message(f"{CROW_EMOJI} {self.daemon.get_machine_name()} {config_key}: {old} → {value}")
            except Exception as e:
                self.send_message(f"Error: {e}")
            return

        if len(parts) >= 4:
            # Support both /edit <machine> <n> <value> and /edit <n> <machine> <value>
            if parts[1].isdigit() and parts[1] in CONFIG_MAP:
                idx, target_machine, value_str = parts[1], parts[2], parts[3]
            else:
                target_machine, idx, value_str = parts[1], parts[2], parts[3]

            if idx not in CONFIG_MAP:
                self.send_message(f"Invalid config number: {idx}")
                return

            # Targeted edit: only the named machine applies and confirms.
            # All other nodes stay silent — the target self-applies via Telegram context,
            # same pattern as /status <machine>.
            if not self._is_this_machine(target_machine):
                return

            config_key, value_type, _ = CONFIG_MAP[idx]
            try:
                value = self.daemon.parse_config_value(value_type, value_str)
                err = self._validate_range(idx, value)
                if err:
                    self.send_message(f"{CROW_EMOJI} {err}")
                    return
                old = self.safe_config.get(config_key)
                if config_key == 'machine.custom_name':
                    self.daemon.set_machine_name(value)
                else:
                    self.safe_config.set(config_key, value)
                self.daemon.update_registry()
                self.send_message(f"{CROW_EMOJI} {self.daemon.get_machine_name()} {config_key}: {old} → {value}")
            except Exception as e:
                self.send_message(f"Error: {e}")

    def handle_status(self, text: str) -> None:
        parts = text.split(maxsplit=1)
        if len(parts) == 1:
            # Unqualified: every node reports its own live status
            status = self.daemon.get_status()
            online = status.get("is_running", False)
            icon = "🟢" if online else "🔴"
            name = status.get("custom_name") or status.get("hostname")
            uptime = int(status.get("uptime_seconds", 0))
            uptime_str = f"{uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s"
            msg = (
                f"{CROW_EMOJI} [{name}]\n"
                f"{icon} Running\n"
                f"Hostname: {status.get('hostname')}\n"
                f"Platform: {status.get('platform')}\n"
                f"Uptime: {uptime_str}"
            )
            self.send_message(msg)
            return

        target = parts[1].strip()
        # Targeted: only the specified machine responds with its live status
        if not self._is_this_machine(target):
            return
        status = self.daemon.get_status()
        online = status.get("is_running", False)
        icon = "🟢" if online else "🔴"
        name = status.get("custom_name") or status.get("hostname")
        uptime = int(status.get("uptime_seconds", 0))
        uptime_str = f"{uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s"
        msg = (
            f"{CROW_EMOJI} [{name}]\n"
            f"{icon} Running\n"
            f"Hostname: {status.get('hostname')}\n"
            f"Platform: {status.get('platform')}\n"
            f"Uptime: {uptime_str}"
        )
        self.send_message(msg)

    def handle_nodes(self, text: str) -> None:
        msg = self.daemon.build_nodes_message()
        self.send_message(msg)

    def handle_watch(self, text: str) -> None:
        parts = text.split(maxsplit=1)
        if len(parts) == 1:
            ok, msg = self.daemon.start_manual_watch()
            self.send_message(f"{CROW_EMOJI} {msg}")
            return

        target = parts[1].strip()
        ok, msg = self.daemon.queue_watch_for_machine(target)
        self.send_message(f"{CROW_EMOJI} {msg}")

    def handle_snap(self, text: str) -> None:
        """Tiny helper: capture one frame and send it to Telegram."""
        parts = text.split(maxsplit=1)
        targeted = len(parts) == 2

        # If a target is specified and it isn't this machine, skip — the target node will respond
        if targeted and not self._is_this_machine(parts[1].strip()):
            return

        machine_name = self.daemon.get_machine_name()
        self.send_message(f"{CROW_EMOJI} [{machine_name}] Taking snapshot...")
        ok, result = self.daemon.take_snapshot()
        if ok:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            caption = f"[{machine_name}] Snapshot — {timestamp}"
            sent = self.daemon.notifier.send_photo_with_caption(result, caption)
            if not sent:
                self.send_message(f"{CROW_EMOJI} [{machine_name}] Snapshot captured but failed to send")
        else:
            self.send_message(f"{CROW_EMOJI} [{machine_name}] Snapshot failed: {result}")
            self.logger.error(f"[Snap] handle_snap failed: {result}")

    def _is_this_machine(self, target: str) -> bool:
        """Tiny helper: check if a target name/id refers to this machine."""
        t = target.strip().lower()
        return t in {
            self.daemon.get_machine_name().lower(),
            self.daemon.hostname.lower(),
            self.daemon.machine_id.lower(),
        }

    def handle_logs(self, text: str) -> None:
        try:
            log_dir = self.daemon.logs_dir
            log_files = list(log_dir.glob("daemon_*.log"))
            if log_files:
                with open(sorted(log_files)[-1], 'r') as f:
                    lines = f.readlines()[-10:]
                self.send_message(f"{CROW_EMOJI} Logs:\n\n{''.join(lines)}")
        except:
            self.send_message(f"{CROW_EMOJI} Error reading logs")


class MotionDaemon:
    def __init__(self, usb_mount: Path, config_file: Optional[Path] = None):
        self.usb_mount = Path(usb_mount)
        self.shared_config_file = config_file or (self.usb_mount / "daemon_config.yaml")
        self.logs_dir = self.usb_mount / "logs"

        self.hostname = socket.gethostname()
        self.local_dir = Path.home() / ".daemon_watcher"
        self.machine_id = self._get_machine_id()

        self.machine_dir = self.usb_mount / ".daemon_watcher_nodes" / self.machine_id
        self.sync_config_file = self.machine_dir / "daemon_config.yaml"
        self.state_file = self.machine_dir / ".daemon_state.json"
        self.watch_request_file = self.machine_dir / "watch_request.json"
        self.local_config_file = self.local_dir / f"daemon_config_{self.machine_id}.yaml"
        self.registry_file = self.usb_mount / "machines.json"

        self.logger = setup_logging(self.logs_dir)
        self.safe_config = SafeConfig(self.shared_config_file, self.local_config_file, self.sync_config_file, self.logger)
        self.registry = MachineRegistry(self.registry_file, self.logger)
        self.notifier = None
        self.detector = None
        self.is_running = False
        self.last_alert_time = 0
        self.start_time = time.time()
        self.version_checker = VersionChecker(self.logger)
        self.passcode_manager = PasscodeManager(self.logger)
        self.logo_base64 = load_logo_base64(self.usb_mount)
        self.passcode_authenticated = False
        self.passcode_attempts = 0
        self.shutdown_timer = 0
        self.manual_watch_lock = threading.Lock()
        self.manual_watch_active = False
        self.last_registry_update = 0
        self.monitor_fps = 20
        self.monitor_resize_factor = 1.0
        self.monitor_camera_index = None
        self.detector_thread = None
        self.heartbeat_manager = None
        self.node_sync_worker = None
        self.udp_receiver = None

    def _get_machine_id(self) -> str:
        return socket.gethostname().replace('.', '_').replace(' ', '_')

    def get_machine_name(self) -> str:
        """Read custom name from state.json (identity store), fall back to config, then hostname."""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                name = state.get('custom_name')
                if name:
                    return name
        except Exception:
            pass
        return self.safe_config.get('machine.custom_name', self.hostname)

    def set_machine_name(self, name: str) -> None:
        """Persist custom name to state.json (survives config regeneration) and config."""
        try:
            self.machine_dir.mkdir(parents=True, exist_ok=True)
            state = {}
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
            state['custom_name'] = name
            with open(self.state_file, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            self.logger.error(f"[State] Failed to write custom_name: {e}")
        self.safe_config.set('machine.custom_name', name)

    def parse_config_value(self, value_type: str, value_str: str) -> Any:
        if value_type == "int":
            return int(value_str)
        elif value_type == "float":
            return float(value_str)
        elif value_type == "bool":
            return value_str.lower() in ['true', 'yes', 'on', '1']
        return value_str

    def get_default_config(self) -> Dict:
        return {
            "telegram": {"token": "YOUR_BOT_TOKEN", "chat_id": "YOUR_CHAT_ID"},
            "motion": {
                "enabled": True, "sensitivity": 0.5, "snapshot": True,
                "video_on_motion": True, "video_duration": 15, "video_quality": "low",
                "snapshot_quality": 75, "cooldown": 60, "alert_text": "Motion detected",
                "include_timestamp": True, "include_hostname": True,
                "alert_hours": {"enabled": False, "start": 9, "end": 17},
                "audio_enabled": False,
                "audio_format": "aac",
                "audio_bitrate": 128,
                "audio_channels": 1,
            },
            "security": {
                "passcode": "",
                "edit_machine": "",
            },
            "machine": {
                "custom_name": socket.gethostname(),
            },
            "daemon": {"auto_start": True, "check_interval": 5, "heartbeat_interval": 15, "heartbeat_port": 7779},
            "camera": {"index": -1},
        }

    def check_updates(self) -> None:
        """Check for daemon updates on startup"""
        self.logger.info("Checking for updates...")
        newer_version = self.version_checker.check_for_updates()
        if newer_version:
            self.logger.warning(f"Update available: {newer_version}")
            self.logger.info("(Auto-update available in Phase 2)")

    def load_config(self) -> bool:
        try:
            if not self.shared_config_file.exists():
                return self._create_default_config()

            if not self.local_config_file.exists():
                base_cfg = {}
                try:
                    with open(self.shared_config_file, 'r') as f:
                        base_cfg = yaml.safe_load(f) or {}
                except Exception:
                    base_cfg = self.get_default_config()
                if not base_cfg:
                    base_cfg = self.get_default_config()
                base_cfg.setdefault("machine", {})
                base_cfg["machine"]["custom_name"] = self.hostname
                self.local_config_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.local_config_file, 'w') as f:
                    yaml.dump(base_cfg, f, default_flow_style=False)

            self.safe_config.load_from_disk()
            self.logger.info(f"Configuration loaded: {self.local_config_file}")
            return True
        except Exception as e:
            self.logger.error(f"Config loading failed: {e}")
            return False

    def _create_default_config(self) -> bool:
        default = self.get_default_config()
        try:
            with open(self.shared_config_file, 'w') as f:
                yaml.dump(default, f, default_flow_style=False)

            local_default = dict(default)
            local_default["machine"] = {"custom_name": self.hostname}
            self.local_config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.local_config_file, 'w') as f:
                yaml.dump(local_default, f, default_flow_style=False)

            self.sync_config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.sync_config_file, 'w') as f:
                yaml.dump(local_default, f, default_flow_style=False)

            self.safe_config.load_from_disk()
            return True
        except Exception as e:
            self.logger.error(f"Failed to create config: {e}")
            return False

    def validate_passcode_with_user(self) -> bool:
        """Wait for user to provide correct passcode via Telegram"""
        stored_encrypted = self.safe_config.get('security.passcode', '')

        if not stored_encrypted:
            self.passcode_authenticated = True
            return True

        self.logger.info("Waiting for passcode validation...")
        if self.notifier:
            custom_name = self.safe_config.get('machine.custom_name', socket.gethostname())
            self.notifier.send_message(
                f"{CROW_EMOJI} PASSCODE REQUIRED\n\nMachine: [{custom_name}]\n\n"
                f"Send: /passcode <your_code>",
                include_logo=True
            )

        timeout = time.time() + 300
        while time.time() < timeout:
            if self.passcode_authenticated:
                self.logger.info("✓ Passcode validated")
                return True

            if self.shutdown_timer > 0:
                self.shutdown_timer -= 1
                if self.shutdown_timer == 0:
                    self.logger.warning("Shutdown timer expired after failed passcode attempts")
                    return False

            time.sleep(1)

        self.logger.error("Passcode validation timeout")
        if self.notifier:
            self.notifier.send_message(f"{CROW_EMOJI} Passcode timeout. Daemon shutting down.")
        return False

    def setup_telegram(self) -> bool:
        tg_cfg = self.safe_config.get('telegram', {})
        if tg_cfg.get('token') == "YOUR_BOT_TOKEN":
            self.logger.error("Telegram not configured")
            return False
        try:
            self.notifier = TelegramNotifier(tg_cfg['token'], tg_cfg['chat_id'], self.logger, self.logo_base64)
            return self.notifier.test_connection()
        except Exception as e:
            self.logger.error(f"Telegram setup failed: {e}")
            return False

    def setup_detector(self) -> bool:
        try:
            import cv2
            self.detector = MotionDetector(self.safe_config, self.logger)
            return True
        except ImportError:
            self.logger.error("OpenCV required")
            return False

    def start_detector_thread(self, camera_index: int) -> None:
        self.monitor_camera_index = camera_index
        self.detector_thread = threading.Thread(
            target=self.detector.start_monitoring,
            args=(self.on_motion_detected, camera_index, self.monitor_fps, self.monitor_resize_factor),
            daemon=True
        )
        self.detector_thread.start()

    def restart_detector(self) -> None:
        if not self.detector:
            return
        if self.monitor_camera_index is None:
            self.monitor_camera_index = CameraDetector(self.logger).find_best_camera()
        if self.monitor_camera_index is None:
            self.logger.error("Cannot restart detector: no camera found")
            return
        self.start_detector_thread(self.monitor_camera_index)

    def on_motion_detected(self, frame, camera_index: int) -> None:
        current_time = time.time()
        cooldown = self.safe_config.get('motion.cooldown', 60)
        if current_time - self.last_alert_time < cooldown:
            return
        self.last_alert_time = current_time
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        custom_name = self.safe_config.get('machine.custom_name', socket.gethostname())

        self.logger.info(f"Motion detected at {timestamp}")

        message = f"[{custom_name}] {self.safe_config.get('motion.alert_text', 'Motion detected')}"
        if self.safe_config.get('motion.include_timestamp'):
            message += f"\n{timestamp}"
        if self.safe_config.get('motion.include_hostname'):
            message += f"\n{socket.gethostname()}"

        if self.notifier:
            self.notifier.send_message(message, include_logo=True)

        if self.safe_config.get('motion.snapshot'):
            try:
                import cv2
                snapshot_file = f"/tmp/motion_{int(current_time)}.jpg"
                quality = self.safe_config.get('motion.snapshot_quality', 75)
                cv2.imwrite(snapshot_file, frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
                if self.notifier:
                    self.notifier.send_photo(snapshot_file, message)
                try:
                    os.remove(snapshot_file)
                except:
                    pass
            except Exception as e:
                self.logger.error(f"Snapshot failed: {e}")

        if self.safe_config.get('motion.video_on_motion'):
            self.record_motion_video(frame, message, camera_index)

        self.save_state()

    def record_motion_video(self, frame, message: str, camera_index: int) -> None:
        try:
            import cv2
        except ImportError:
            return

        duration = self.safe_config.get('motion.video_duration', 15)
        quality = self.safe_config.get('motion.video_quality', 'low')

        if quality == 'low':
            fps, w, h = 10, 320, 240
        elif quality == 'medium':
            fps, w, h = 15, 640, 480
        else:
            fps, w, h = 30, 1280, 720

        self.logger.info(f"Recording {duration}s video ({quality} quality)")

        try:
            cap = cv2.VideoCapture(camera_index)
            if not cap.isOpened():
                return

            time.sleep(2)
            frames = []
            frame_count = int(fps * duration)

            for i in range(frame_count):
                ret, f = cap.read()
                if ret and f is not None:
                    f_resized = cv2.resize(f, (w, h))
                    frames.append(f_resized)

            cap.release()

            if len(frames) < 5:
                return

            system = platform.system()
            if system == 'Darwin':
                codecs_to_try = [('avc1', '.mp4', 'H.264'), ('mp4v', '.mp4', 'MPEG-4')]
            elif system == 'Windows':
                codecs_to_try = [('mp4v', '.mp4', 'MPEG-4'), ('H264', '.mp4', 'H.264')]
            else:
                codecs_to_try = [('mp4v', '.mp4', 'MPEG-4'), ('X264', '.mp4', 'x264')]

            video_file = None
            for codec_code, ext, codec_name in codecs_to_try:
                try:
                    test_file = f"/tmp/motion_{int(time.time())}_{codec_code}{ext}"
                    fourcc = cv2.VideoWriter_fourcc(*codec_code)
                    out = cv2.VideoWriter(test_file, fourcc, fps, (w, h))

                    if out.isOpened():
                        for f in frames:
                            out.write(f)
                        out.release()

                        if os.path.exists(test_file):
                            file_size = os.path.getsize(test_file)
                            if file_size > 50000:
                                video_file = test_file
                                break
                except:
                    pass

            if not video_file:
                return

            if self.notifier:
                self.notifier.send_video(video_file, message)

            try:
                os.remove(video_file)
            except:
                pass

        except Exception as e:
            self.logger.error(f"Video recording failed: {e}")

    def get_status(self) -> Dict:
        return {
            "timestamp": datetime.now().isoformat(),
            "hostname": socket.gethostname(),
            "custom_name": self.safe_config.get('machine.custom_name', socket.gethostname()),
            "platform": platform.system(),
            "is_running": self.is_running,
            "uptime_seconds": int(time.time() - self.start_time),
            "last_motion": self.last_alert_time,
        }

    def save_state(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w') as f:
                json.dump(self.get_status(), f)
        except Exception as e:
            self.logger.error(f"State save failed: {e}")

    def update_registry(self) -> None:
        try:
            payload = {
                "hostname": self.hostname,
                "custom_name": self.get_machine_name(),
                "platform": platform.system(),
                "is_running": self.is_running,
                "last_seen": time.time(),
                "config_path": str(self.sync_config_file),
                "watch_request_file": str(self.watch_request_file),
            }
            self.registry.upsert_machine(self.machine_id, payload)
        except Exception as e:
            self.logger.error(f"Registry update failed: {e}")

    def _stale_threshold(self) -> float:
        """A node is considered offline after 3 missed heartbeats."""
        return self.safe_config.get('daemon.heartbeat_interval', 15) * 3

    def _is_online(self, machine: dict) -> bool:
        return machine.get("is_running", False) and (
            time.time() - float(machine.get("last_seen", 0)) <= self._stale_threshold()
        )

    def build_nodes_message(self) -> str:
        machines = self.registry.get_all()
        now = time.time()
        stale = self._stale_threshold()

        lines = [f"{CROW_EMOJI} NODES", ""]

        if not machines:
            lines.append("No nodes registered.")
            return "\n".join(lines)

        def sort_key(item):
            machine = item[1]
            online = machine.get("is_running", False) and (now - float(machine.get("last_seen", 0)) <= stale)
            name = str(machine.get("custom_name") or machine.get("hostname") or "Unknown")
            return (0 if online else 1, name.lower())

        for _, machine in sorted(machines.items(), key=sort_key):
            name = str(machine.get("custom_name") or machine.get("hostname") or "Unknown")
            online = machine.get("is_running", False) and (now - float(machine.get("last_seen", 0)) <= stale)
            icon = "🟢" if online else "🔴"
            status = "connected" if online else "offline"
            lines.append(f"{icon} {name} ({status})")

        return "\n".join(lines)

    def build_all_status_message(self) -> str:
        machines = self.registry.get_all()
        now = time.time()
        stale = self._stale_threshold()
        lines = [f"{CROW_EMOJI} DAEMON STATUS", ""]

        if not machines:
            lines.append("No nodes registered.")
            return "\n".join(lines)

        for _, machine in sorted(machines.items(), key=lambda x: str(x[1].get("custom_name", "")).lower()):
            online = machine.get("is_running", False) and (now - float(machine.get("last_seen", 0)) <= stale)
            icon = "🟢" if online else "🔴"
            name = machine.get("custom_name") or machine.get("hostname")
            lines.append(
                f"{icon} [{name}]\n"
                f"Hostname: {machine.get('hostname')}\n"
                f"Platform: {machine.get('platform')}\n"
                f"Running: {online}\n"
            )

        return "\n".join(lines).strip()

    def build_single_status_message(self, target: str) -> str:
        machine = self.registry.find_machine(target)
        if not machine:
            return f"{CROW_EMOJI} Machine not found: {target}"

        online = self._is_online(machine)
        icon = "🟢" if online else "🔴"
        last_seen = machine.get("last_seen", 0)
        age = int(time.time() - float(last_seen))
        age_str = f"{age}s ago" if age < 120 else f"{age // 60}m ago"
        return (
            f"{CROW_EMOJI} DAEMON STATUS\n\n"
            f"{icon} [{machine.get('custom_name') or machine.get('hostname')}]\n"
            f"Hostname: {machine.get('hostname')}\n"
            f"Platform: {machine.get('platform')}\n"
            f"Running: {online}\n"
            f"Last seen: {age_str}"
        )

    def edit_machine_config(self, target_machine: str, config_key: str, value: Any) -> tuple:
        machine = self.registry.find_machine(target_machine)
        if not machine:
            return False, None, f"Machine not found: {target_machine}"

        is_local = machine.get("machine_id", "").lower() in {
            self.machine_id.lower(), self.hostname.lower(), self.get_machine_name().lower()
        }

        config_path = machine.get("config_path")
        config_file = Path(config_path) if config_path else None

        # For remote nodes, only update registry (can't write to their filesystem).
        # For custom_name specifically, registry update is the correct action on any node.
        if not is_local or not config_file or not config_file.exists():
            if config_key == "machine.custom_name":
                old = machine.get("custom_name")
                machine["custom_name"] = value
                self.registry.upsert_machine(machine["machine_id"], machine)
                self.logger.info(f"[EditMachineConfig] Registry-only rename for {target_machine}: {old} → {value}")
                return True, old, value
            return False, None, f"Cannot write config to remote machine: {target_machine}"

        cfg = {}
        try:
            with open(config_file, 'r') as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            cfg = self.get_default_config()
            cfg["machine"]["custom_name"] = machine.get("custom_name") or machine.get("hostname") or target_machine

        keys = config_key.split('.')
        current = cfg
        for key in keys[:-1]:
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]

        old = current.get(keys[-1])
        current[keys[-1]] = value

        try:
            config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(config_file, 'w') as f:
                yaml.dump(cfg, f, default_flow_style=False)
        except Exception as e:
            self.logger.error(f"[EditMachineConfig ERROR] Failed writing config for {target_machine}: {e}")
            return False, None, f"Failed writing config for {target_machine}"

        if config_key == "machine.custom_name":
            machine["custom_name"] = value
            self.registry.upsert_machine(machine["machine_id"], machine)
            # For local machine, also write to state.json so name survives config regeneration
            if machine.get("machine_id") == self.machine_id:
                self.set_machine_name(value)

        return True, old, machine.get("custom_name") or machine.get("hostname") or target_machine

    def queue_watch_for_machine(self, target_machine: str) -> tuple:
        if target_machine.lower() in {self.hostname.lower(), self.get_machine_name().lower(), self.machine_id.lower()}:
            return self.start_manual_watch()

        machine = self.registry.find_machine(target_machine)
        if not machine:
            return False, f"Machine not found: {target_machine}"

        request_file = machine.get("watch_request_file")
        if not request_file:
            return False, f"No watch queue for machine: {target_machine}"

        try:
            request_path = Path(request_file)
            request_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "requested_at": time.time(),
                "requested_by": self.get_machine_name(),
            }
            with open(request_path, 'w') as f:
                json.dump(payload, f)
            return True, f"Watch queued for {machine.get('custom_name') or machine.get('hostname')}"
        except Exception as e:
            return False, f"Failed to queue watch: {e}"

    def process_watch_requests(self) -> None:
        try:
            if not self.watch_request_file.exists():
                return
            with open(self.watch_request_file, 'r') as f:
                payload = json.load(f)
            os.remove(self.watch_request_file)
            self.logger.info("Queued watch request found")
            self.start_manual_watch()
        except Exception as e:
            self.logger.error(f"Watch request processing failed: {e}")

    def start_manual_watch(self) -> tuple:
        with self.manual_watch_lock:
            if self.manual_watch_active:
                return False, f"Watch already in progress on {self.get_machine_name()}"
            self.manual_watch_active = True

        t = threading.Thread(target=self._manual_watch_worker, daemon=True)
        t.start()
        return True, f"Watch started on {self.get_machine_name()}"

    def _manual_watch_worker(self) -> None:
        try:
            camera = self.monitor_camera_index
            if camera is None:
                pinned = self.safe_config.get('camera.index', -1)
                if isinstance(pinned, int) and pinned >= 0:
                    camera = pinned
                else:
                    camera = CameraDetector(self.logger).find_best_camera()

            if camera is None:
                if self.notifier:
                    self.notifier.send_message(f"[{self.get_machine_name()}] Manual watch failed: no camera found", include_logo=True)
                return

            self.logger.info("Manual watch: pausing motion detector to free camera")
            if self.detector:
                self.detector.stop_monitoring()

            time.sleep(1.0)

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = f"[{self.get_machine_name()}] Manual watch\n{timestamp}"
            self.record_motion_video(None, message, camera)

            self.logger.info("Manual watch: restarting motion detector")
            time.sleep(0.5)
            self.restart_detector()
        except Exception as e:
            self.logger.error(f"Manual watch failed: {e}")
        finally:
            with self.manual_watch_lock:
                self.manual_watch_active = False

    def take_snapshot(self) -> tuple:
        """Tiny helper: capture one frame from the camera, return (True, jpeg_bytes) or (False, error_str)."""
        try:
            import cv2
        except ImportError:
            return False, "OpenCV not available"

        camera = self.monitor_camera_index
        if camera is None:
            pinned = self.safe_config.get('camera.index', -1)
            if isinstance(pinned, int) and pinned >= 0:
                camera = pinned
            else:
                camera = CameraDetector(self.logger).find_best_camera()

        if camera is None:
            return False, "No camera found"

        self.logger.info(f"[Snapshot] Taking snapshot on camera {camera}")
        try:
            if self.detector:
                self.detector.stop_monitoring()
            time.sleep(0.5)

            cap = cv2.VideoCapture(camera)
            if not cap.isOpened():
                self.logger.error(f"[Snapshot ERROR] Could not open camera {camera}")
                return False, "Could not open camera"

            # Warmup: let the sensor settle before grabbing the frame
            for _ in range(8):
                cap.read()
                time.sleep(0.05)

            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                self.logger.error("[Snapshot ERROR] Camera returned no frame")
                return False, "Failed to capture frame"

            quality = self.safe_config.get('motion.snapshot_quality', 75)
            encode_ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if not encode_ok:
                return False, "Failed to encode frame"

            self.logger.info(f"[Snapshot] ✓ Captured {len(buf)} bytes")
            return True, bytes(buf)

        except Exception as e:
            self.logger.error(f"[Snapshot ERROR] take_snapshot failed: {e}")
            return False, str(e)
        finally:
            time.sleep(0.3)
            self.restart_detector()

    def send_startup_notification(self) -> None:
        if not self.notifier:
            return

        custom_name = self.safe_config.get('machine.custom_name', socket.gethostname())
        hostname = socket.gethostname()
        timestamp = datetime.now().strftime("%a %b %d, %Y @ %I:%M %p")

        config_lines = [
            f"1. motion.video_duration: {self.safe_config.get('motion.video_duration', 15)}",
            f"2. motion.video_on_motion: {self.safe_config.get('motion.video_on_motion', True)}",
            f"3. motion.alert_hours.enabled: {self.safe_config.get('motion.alert_hours.enabled', False)}",
            f"4. motion.sensitivity: {self.safe_config.get('motion.sensitivity', 0.5)}",
            f"5. motion.snapshot_quality: {self.safe_config.get('motion.snapshot_quality', 75)}",
            f"6. motion.video_quality: {self.safe_config.get('motion.video_quality', 'low')}",
            f"7. motion.cooldown: {self.safe_config.get('motion.cooldown', 60)}",
            f"8. motion.alert_text: {self.safe_config.get('motion.alert_text', 'Motion detected')}",
            f"9. motion.snapshot: {self.safe_config.get('motion.snapshot', True)}",
            f"10. daemon.check_interval: {self.safe_config.get('daemon.check_interval', 5)}",
            f"11. security.passcode: {self.safe_config.get('security.passcode', None)}",
            f"12. machine.custom_name: {self.safe_config.get('machine.custom_name', hostname)}",
            f"13. security.edit_machine: {self.safe_config.get('security.edit_machine', None)}",
            f"14. nodes: /nodes",
            f"15. camera.index: {self.safe_config.get('camera.index', -1)} (-1=auto)",
            f"16. daemon.heartbeat_interval: {self.safe_config.get('daemon.heartbeat_interval', 15)}s",
        ]

        legal_notice = (
            "⚠️ RECORDING NOTICE: Video and audio surveillance laws vary by location. "
            "In some jurisdictions, recording individuals without consent — including video in private spaces or audio in any setting — is illegal. "
            "In one-party consent regions, only one participant must consent. In all-party consent regions, everyone being recorded must consent. "
            "You are responsible for ensuring your use of this system complies with all applicable local, state, and federal laws."
        )

        message = f"""DAEMON WATCHER LOADED

Machine: [{custom_name}]
Hostname: {hostname}
Loaded: {timestamp}

{legal_notice}

CURRENT CONFIGURATION
{chr(10).join(config_lines)}

AVAILABLE COMMANDS
/edit <n> <value>             Change setting
/edit <machine> <n> <value>  Change setting on specific machine
/status                       Show all daemon status
/status <machine>             Show single daemon status
/nodes                        Show nodes
/snap                         Take snapshot now
/snap <machine>               Take snapshot on specific machine
/watch                        Record video now
/watch <machine>              Queue watch on specific machine
/test                         Send test alert
/logs                         Show recent logs
/kill                         Self-destruct
/help                         Show help

Ready to monitor. Send /edit to customize."""

        self.notifier.send_message(message, include_logo=True)

        if self.logo_base64:
            try:
                logo_bytes = base64.b64decode(self.logo_base64)
                self.notifier.send_photo_with_caption(logo_bytes, "Daemon Watcher Active")
            except Exception as e:
                self.logger.debug(f"Could not send logo: {e}")

    def send_shutdown_notification(self) -> None:
        if not self.notifier:
            return

        custom_name = self.safe_config.get('machine.custom_name', socket.gethostname())
        timestamp = datetime.now().strftime("%a %b %d, %Y @ %I:%M %p")

        message = f"DAEMON WATCHER STOPPED\n\nMachine: [{custom_name}]\nTime: {timestamp}"
        self.notifier.send_message(message, include_logo=True)

        if self.logo_base64:
            try:
                logo_bytes = base64.b64decode(self.logo_base64)
                self.notifier.send_photo_with_caption(logo_bytes, "Daemon Watcher Offline")
            except Exception as e:
                self.logger.debug(f"Could not send logo: {e}")

    def run(self) -> None:
        self.check_updates()

        dep_manager = DependencyManager(self.logger)
        if not dep_manager.check_and_install_all():
            self.logger.warning("Some dependencies missing")

        if not self.load_config():
            return
        if not self.setup_telegram():
            return

        if not self.validate_passcode_with_user():
            return

        if not self.setup_detector():
            return

        def signal_handler(signum, frame):
            self.is_running = False

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        self.is_running = True
        self.update_registry()
        self.send_startup_notification()
        self.logger.info("Daemon Watcher running")

        pinned = self.safe_config.get('camera.index', -1)
        if isinstance(pinned, int) and pinned >= 0:
            camera = pinned
            self.logger.info(f"Using pinned camera index {camera} (camera.index config)")
        else:
            camera = CameraDetector(self.logger).find_best_camera()
        if camera is None:
            self.logger.error("No camera found")
            return

        self.start_detector_thread(camera)

        telegram_listener = TelegramCommandListener(
            self.safe_config.get('telegram.token'),
            self.safe_config.get('telegram.chat_id'),
            self,
            self.safe_config,
            self.logger
        )
        telegram_thread = threading.Thread(
            target=telegram_listener.poll_for_commands,
            daemon=True
        )
        telegram_thread.start()
        self.logger.info("✓ Telegram listener started")

        self.heartbeat_manager = HeartbeatManager(
            self.safe_config.get('telegram.token'),
            self.safe_config.get('telegram.chat_id'),
            self, self.safe_config, self.logger
        )
        heartbeat_thread = threading.Thread(target=self.heartbeat_manager.run, daemon=True)
        heartbeat_thread.start()
        self.logger.info("✓ Heartbeat started")

        self.node_sync_worker = NodeSyncWorker(self, self.safe_config, self.logger)
        sync_thread = threading.Thread(target=self.node_sync_worker.run, daemon=True)
        sync_thread.start()
        self.logger.info("✓ Node sync worker started")

        self.udp_receiver = UDPHeartbeatReceiver(self, self.safe_config, self.logger)
        udp_thread = threading.Thread(target=self.udp_receiver.run, daemon=True)
        udp_thread.start()
        self.logger.info(f"✓ UDP heartbeat receiver started (port={self.safe_config.get('daemon.heartbeat_port', UDP_HEARTBEAT_PORT)})")

        try:
            while self.is_running:
                if self.safe_config.reload_if_changed():
                    self.logger.info("Configuration reloaded")
                self.process_watch_requests()
                self.update_registry()
                self.save_state()
                time.sleep(5)
        except KeyboardInterrupt:
            pass
        finally:
            self.is_running = False
            if self.heartbeat_manager:
                self.heartbeat_manager.stop()
            if self.node_sync_worker:
                self.node_sync_worker.stop()
            if self.udp_receiver:
                self.udp_receiver.stop()
            if self.detector:
                self.detector.stop_monitoring()
            self.update_registry()
            self.send_shutdown_notification()
            self.save_state()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Daemon Watcher - USB Surveillance System")
    parser.add_argument("--usb-path", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    daemon = MotionDaemon(args.usb_path, args.config)
    daemon.load_config()
    if args.status:
        print(json.dumps(daemon.get_status(), indent=2))
    else:
        daemon.run()
