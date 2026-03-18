#!/usr/bin/env python3
"""
Motion Daemon Auto-Launcher — Cross-platform USB detection and daemon startup
Detects USB insertion and automatically starts motion daemon
"""

import sys
import platform
import subprocess
import time
import logging
import json
import tempfile
from pathlib import Path
from typing import Optional


def setup_launcher_logging(usb_mount: Path) -> logging.Logger:
    """Setup logging for launcher"""
    log_dir = usb_mount / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("motion_launcher")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if logger.handlers:
        logger.handlers.clear()

    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

    handler = logging.FileHandler(log_dir / "launcher.log")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger


class USBDetector:
    """Detect USB insertion and start daemon"""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.daemon_process: Optional[subprocess.Popen] = None

    def _find_core_script(self, mount_path: Path) -> Optional[Path]:
        """Find the best available core script on the USB"""
        candidates = [
            mount_path / "motion_daemon_core_v2.py",
            mount_path / "motion_daemon_core.py",
        ]

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate

        return None

    def _state_indicates_running(self, state_file: Path) -> bool:
        """Check if saved state claims the daemon is already running"""
        if not state_file.exists():
            return False

        try:
            with open(state_file, 'r') as f:
                state = json.load(f)
            return bool(state.get("is_running"))
        except Exception as e:
            self.logger.warning(f"Could not read state file {state_file}: {e}")
            return False

    def start_daemon(self, usb_path: Path, core_script: Path) -> bool:
        """Start motion daemon"""
        try:
            state_file = usb_path / ".daemon_state.json"
            if self._state_indicates_running(state_file):
                self.logger.info("Daemon already marked as running in state file")
                return True

            self.daemon_process = subprocess.Popen(
                [sys.executable, str(core_script), "--usb-path", str(usb_path)],
                cwd=str(usb_path),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=(platform.system() != "Windows"),
            )

            self.logger.info(
                f"✓ Motion daemon started using {core_script.name} (PID: {self.daemon_process.pid})"
            )
            return True

        except Exception as e:
            self.logger.error(f"Failed to start daemon: {e}")
            return False

    def on_usb_mounted(self, mount_path: Path) -> None:
        """Called when USB is detected"""
        self.logger.info(f"✓ USB detected at {mount_path}")

        core_script = self._find_core_script(mount_path)
        if core_script is None:
            self.logger.error(
                f"Core script not found on USB. Checked: "
                f"{mount_path / 'motion_daemon_core_v2.py'}, {mount_path / 'motion_daemon_core.py'}"
            )
            return

        self.start_daemon(mount_path, core_script)


class LinuxUSBDetector(USBDetector):
    """Linux USB detection via mount polling"""

    def start_monitoring(self) -> None:
        """Monitor USB insertion"""
        self.logger.info("Linux USB monitor started (mtab polling)")
        seen_mounts = set()

        while True:
            try:
                with open('/etc/mtab', 'r') as f:
                    mounts = f.readlines()

                current_mounts = set()

                for line in mounts:
                    if '/media/' in line or '/mnt/' in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            mount_point = parts[1]
                            current_mounts.add(mount_point)

                            if mount_point not in seen_mounts:
                                seen_mounts.add(mount_point)

                                if (Path(mount_point) / "daemon_config.yaml").exists():
                                    self.on_usb_mounted(Path(mount_point))

                seen_mounts.intersection_update(current_mounts)
                time.sleep(2)

            except Exception as e:
                self.logger.error(f"mtab polling error: {e}")
                time.sleep(5)


class MacOSUSBDetector(USBDetector):
    """macOS USB detection via /Volumes polling"""

    def start_monitoring(self) -> None:
        """Monitor /Volumes directory"""
        self.logger.info("macOS USB monitor started (/Volumes polling)")
        seen_volumes = set()

        while True:
            try:
                current_volumes = set()

                for vol in Path('/Volumes').iterdir():
                    if not vol.is_dir():
                        continue

                    vol_name = vol.name
                    current_volumes.add(vol_name)

                    if vol_name in ('Macintosh HD', '.', '..'):
                        continue

                    if vol_name not in seen_volumes:
                        seen_volumes.add(vol_name)

                        if (vol / "daemon_config.yaml").exists():
                            self.on_usb_mounted(vol)

                seen_volumes.intersection_update(current_volumes)
                time.sleep(2)

            except Exception as e:
                self.logger.error(f"Volumes polling error: {e}")
                time.sleep(5)


class WindowsUSBDetector(USBDetector):
    """Windows USB detection via drive polling"""

    def start_monitoring(self) -> None:
        """Monitor available drives"""
        self.logger.info("Windows USB monitor started (drive polling)")
        import string

        seen_drives = set()

        while True:
            try:
                current_drives = set()

                for drive in string.ascii_uppercase:
                    drive_path = Path(f"{drive}:/")
                    if drive_path.exists():
                        current_drives.add(drive)

                        if drive not in seen_drives:
                            seen_drives.add(drive)
                            if (drive_path / "daemon_config.yaml").exists():
                                self.on_usb_mounted(drive_path)

                seen_drives.intersection_update(current_drives)
                time.sleep(2)

            except Exception as e:
                self.logger.error(f"Drive polling error: {e}")
                time.sleep(5)


class Launcher:
    """Launcher orchestrator"""

    def __init__(self):
        self.logger: Optional[logging.Logger] = None
        self.detector: Optional[USBDetector] = None
        self.system = platform.system()

    def _build_detector(self, logger: logging.Logger) -> Optional[USBDetector]:
        """Create the correct detector for the current OS"""
        if self.system == "Linux":
            return LinuxUSBDetector(logger)
        if self.system == "Darwin":
            return MacOSUSBDetector(logger)
        if self.system == "Windows":
            return WindowsUSBDetector(logger)

        logger.error(f"Unsupported platform: {self.system}")
        return None

    def initialize(self, usb_mount: Optional[Path] = None) -> bool:
        """Initialize launcher"""
        log_root = usb_mount if usb_mount else Path(tempfile.gettempdir())
        self.logger = setup_launcher_logging(log_root)
        self.logger.info(f"Launcher initializing on {self.system}")

        self.detector = self._build_detector(self.logger)
        return self.detector is not None

    def run_single_mount(self, usb_mount: Path) -> None:
        """Run daemon on specific mount (one-time)"""
        self.logger = setup_launcher_logging(usb_mount)
        detector = self._build_detector(self.logger)

        if detector is None:
            return

        detector.on_usb_mounted(usb_mount)

    def run_daemon_mode(self) -> None:
        """Run as persistent monitor"""
        if not self.initialize():
            print("Failed to initialize launcher")
            sys.exit(1)

        self.logger.info("Launcher starting in daemon mode")

        try:
            self.detector.start_monitoring()
        except KeyboardInterrupt:
            self.logger.info("Launcher shutdown")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Motion Daemon Auto-Launcher")
    parser.add_argument(
        "--mode",
        choices=["daemon", "once"],
        default="daemon",
        help="daemon: continuous monitoring, once: single USB path"
    )
    parser.add_argument("--usb-path", type=Path, help="USB mount path (for 'once' mode)")

    args = parser.parse_args()

    launcher = Launcher()

    if args.mode == "once":
        if not args.usb_path:
            print("Error: --usb-path required for 'once' mode")
            sys.exit(1)
        launcher.run_single_mount(args.usb_path)
    else:
        launcher.run_daemon_mode()
