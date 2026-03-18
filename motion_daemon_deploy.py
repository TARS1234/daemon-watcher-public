#!/usr/bin/env python3
"""
Motion Daemon Deployment Bootstrap
Copies scripts to USB and initializes configuration
"""

import sys
import shutil
import stat
from pathlib import Path
from typing import List, Tuple, Optional


class MotionDaemonDeployer:
    """Deploy motion daemon to USB"""

    def __init__(self, usb_mount: Path, source_dir: Path):
        self.usb_mount = Path(usb_mount)
        self.source_dir = Path(source_dir)

        self.required_script_groups: List[Tuple[List[str], str]] = [
            (["motion_daemon_core_v2.py", "motion_daemon_core.py"], "main daemon"),
            (["motion_daemon_launcher.py"], "launcher"),
        ]

        self.optional_files: List[str] = [
            "motion_daemon_telegram.py",
            "motion_requirements.txt",
            "MOTION_QUICKSTART.md",
            "FINAL_PRODUCTION_BUILD.md",
        ]

        self.deployed_core_script: Optional[str] = None
        self.deployed_files: List[str] = []

    def validate_paths(self) -> bool:
        """Validate USB mount and source directory"""
        if not self.usb_mount.exists():
            print(f"❌ USB mount not found: {self.usb_mount}")
            return False

        if not self.usb_mount.is_dir():
            print(f"❌ USB path is not a directory: {self.usb_mount}")
            return False

        if not self.source_dir.exists():
            print(f"❌ Source directory not found: {self.source_dir}")
            return False

        if not self.source_dir.is_dir():
            print(f"❌ Source path is not a directory: {self.source_dir}")
            return False

        test_file = self.usb_mount / ".test_write"
        try:
            test_file.touch()
            test_file.unlink()
        except PermissionError:
            print(f"❌ No write permission on USB: {self.usb_mount}")
            return False
        except Exception as e:
            print(f"❌ Unable to verify USB write access: {e}")
            return False

        return True

    def _copy_file(self, src: Path, dst: Path, executable: bool = False) -> bool:
        """Copy a single file"""
        try:
            shutil.copy2(src, dst)
            if executable:
                st = dst.stat()
                dst.chmod(st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            print(f"  ✓ {dst.name}")
            self.deployed_files.append(dst.name)
            return True
        except Exception as e:
            print(f"  ❌ {src.name}: {e}")
            return False

    def copy_scripts(self) -> bool:
        """Copy required and optional files to USB"""
        print("📋 Copying scripts...")

        for candidates, label in self.required_script_groups:
            selected = None
            for name in candidates:
                candidate_path = self.source_dir / name
                if candidate_path.exists():
                    selected = candidate_path
                    break

            if selected is None:
                print(f"❌ Missing required {label}. Checked: {', '.join(candidates)}")
                return False

            if label == "main daemon":
                self.deployed_core_script = selected.name

            dst = self.usb_mount / selected.name
            if not self._copy_file(selected, dst, executable=True):
                return False

        for name in self.optional_files:
            src = self.source_dir / name
            if src.exists():
                dst = self.usb_mount / name
                if not self._copy_file(src, dst, executable=name.endswith(".py")):
                    return False

        return True

    def create_directories(self) -> None:
        """Create necessary directories"""
        print("📁 Creating directories...")

        for dir_name in ["logs", ".cache"]:
            dir_path = self.usb_mount / dir_name
            dir_path.mkdir(parents=True, exist_ok=True)
            print(f"  ✓ {dir_name}")

    def create_default_config(self) -> None:
        """Create default configuration file if one does not already exist"""
        print("⚙️  Creating default configuration...")

        config_file = self.usb_mount / "daemon_config.yaml"
        if config_file.exists():
            print("  ✓ daemon_config.yaml already exists")
            return

        config = """# Motion Detection Daemon Configuration
# Configure Telegram bot and motion settings here

telegram:
  token: "YOUR_BOT_TOKEN"
  chat_id: "YOUR_CHAT_ID"

motion:
  enabled: true
  sensitivity: 0.5
  snapshot: true
  video_on_motion: true
  video_duration: 15
  video_quality: "low"
  snapshot_quality: 75
  cooldown: 60
  alert_text: "Motion detected"
  include_timestamp: true
  include_hostname: true
  alert_hours:
    enabled: false
    start: 9
    end: 17

daemon:
  auto_start: true
  check_interval: 5
"""

        try:
            config_file.write_text(config)
            print("  ✓ daemon_config.yaml")
        except Exception as e:
            print(f"  ❌ Config creation failed: {e}")

    def create_readme(self) -> None:
        """Create README with setup instructions"""
        print("📄 Creating README...")

        core_script = self.deployed_core_script or "motion_daemon_core_v2.py"

        readme = f"""# Motion Detection Daemon

## Quick Start

1. Configure Telegram
Edit daemon_config.yaml:
- Get bot token from @BotFather on Telegram
- Get your chat_id from @userinfobot
- Add both to the config file

2. Run Daemon
python3 {core_script}

3. Auto-Launch Mode (Optional)
python3 motion_daemon_launcher.py --mode daemon

## How It Works

1. Plug USB into a machine
2. Run the daemon
3. Monitor camera continuously for motion
4. Send Telegram alerts with snapshots/videos when motion is detected

## Configuration

Example:

telegram:
  token: "YOUR_BOT_TOKEN"
  chat_id: "YOUR_CHAT_ID"

motion:
  sensitivity: 0.5
  snapshot: true
  video_on_motion: true
  video_duration: 15
  cooldown: 60

## Troubleshooting

No camera found:
- Check if webcam/camera is connected

Telegram not working:
- Verify token and chat_id in config
- Test token:
  curl https://api.telegram.org/botYOUR_TOKEN/getMe

Permission issues:
- Verify the USB is writable

## File Structure

{self.usb_mount}/
├── {core_script}
├── motion_daemon_launcher.py
├── daemon_config.yaml
├── logs/
└── .daemon_state.json

## Logs

tail -f logs/daemon_*.log
"""

        readme_file = self.usb_mount / "README.md"
        try:
            readme_file.write_text(readme)
            print("  ✓ README.md")
        except Exception as e:
            print(f"  ❌ README creation failed: {e}")

    def check_dependencies(self) -> None:
        """Check for Python dependencies"""
        print("📦 Checking dependencies...")

        required = {
            "yaml": ("PyYAML", "pip install PyYAML"),
            "requests": ("requests", "pip install requests"),
        }

        optional = {
            "cv2": "opencv-python (motion detection)",
            "PIL": "pillow (image processing)",
        }

        missing_required = []

        for module, (display_name, install_cmd) in required.items():
            try:
                __import__(module)
                print(f"  ✓ {display_name}")
            except ImportError:
                print(f"  ❌ {display_name} (REQUIRED)")
                missing_required.append(install_cmd)

        for module, name in optional.items():
            try:
                __import__(module)
                print(f"  ✓ {name}")
            except ImportError:
                print(f"  ⚠️  {name}")

        if missing_required:
            print("\n⚠️  Install required packages:")
            for cmd in missing_required:
                print(f"   {cmd}")

    def deploy(self) -> bool:
        """Run full deployment"""
        print("\n" + "=" * 60)
        print("  MOTION DAEMON DEPLOYMENT")
        print("=" * 60 + "\n")

        if not self.validate_paths():
            return False

        self.create_directories()

        if not self.copy_scripts():
            return False

        self.create_default_config()
        self.create_readme()
        self.check_dependencies()

        print("\n" + "=" * 60)
        print("✅ Deployment complete!")
        print("=" * 60)
        print(f"\n📍 USB mounted at: {self.usb_mount}")

        if self.deployed_core_script:
            print("\n⏭️  Next steps:")
            print("   1. Edit daemon_config.yaml with Telegram credentials")
            print(f"   2. Run: python3 {self.deployed_core_script}")
            print("   3. Or: python3 motion_daemon_launcher.py --mode daemon")
            print()

        return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Deploy Motion Daemon")
    parser.add_argument("usb_path", type=Path, help="USB mount path")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path.cwd(),
        help="Source directory for scripts (default: current dir)",
    )

    args = parser.parse_args()

    deployer = MotionDaemonDeployer(args.usb_path, args.source)

    if deployer.deploy():
        sys.exit(0)
    else:
        sys.exit(1)
