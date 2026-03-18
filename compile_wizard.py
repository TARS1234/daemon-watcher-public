#!/usr/bin/env python3
"""
Compile Wizard to .app - Takes install_wizard_standalone.py and compiles to DaemonWatcherSetup.app
Run this AFTER build_package.py to create the final USB-ready executable
"""

import sys
import subprocess
from pathlib import Path

PROJECT_DIR = Path.cwd()
DIST_DIR = PROJECT_DIR / "dist"
WIZARD_FILE = DIST_DIR / "install_wizard_standalone.py"

def ensure_pyinstaller():
    """Install PyInstaller if needed"""
    try:
        import PyInstaller
    except ImportError:
        print("Installing PyInstaller...\n")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pyinstaller"], check=True)

def compile_to_app():
    """Compile wizard to .app using PyInstaller"""
    print("=" * 70)
    print("COMPILING WIZARD TO STANDALONE .APP")
    print("=" * 70 + "\n")
    
    if not WIZARD_FILE.exists():
        print(f"✗ {WIZARD_FILE} not found")
        print(f"Run build_package.py first!\n")
        return False
    
    print(f"✓ Found wizard: {WIZARD_FILE.name}\n")
    
    print("Compiling to DaemonWatcherSetup.app...\n")
    print("(This takes 2-3 minutes)\n")
    
    try:
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--onefile",
            "--windowed",
            "--name", "DaemonWatcherSetup",
            "--hidden-import", "cryptography",
            "--hidden-import", "PIL",
            "--hidden-import", "yaml",
            "--hidden-import", "requests",
            "--hidden-import", "cv2",
            "--clean",
            str(WIZARD_FILE)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode == 0:
            app_path = DIST_DIR / "DaemonWatcherSetup.app"
            if app_path.exists():
                size_mb = sum(f.stat().st_size for f in app_path.rglob('*')) / 1024 / 1024
                print(f"✓ Compiled successfully!\n")
                print(f"✓ Output: {app_path}")
                print(f"✓ Size: {size_mb:.1f} MB\n")
                return True
            else:
                print(f"✗ App not found at {app_path}\n")
                return False
        else:
            print(f"✗ Compilation failed\n")
            if result.stderr:
                print(result.stderr[:500])
            return False
    
    except subprocess.TimeoutExpired:
        print("✗ Build timed out\n")
        return False
    except Exception as e:
        print(f"✗ Error: {e}\n")
        return False

def copy_to_usb(app_path: Path):
    """Copy compiled app to USB"""
    print("=" * 70)
    print("READY FOR USB")
    print("=" * 70 + "\n")
    
    print(f"The app is ready at: {app_path}\n")
    print("To copy to USB, run:\n")
    print(f'  cp -r "{app_path}" "/Volumes/NO NAME/"')
    print(f'  cp README.md "/Volumes/NO NAME/"\n')
    print("Then eject USB and double-click DaemonWatcherSetup.app on the USB!\n")

def main():
    """Main entry point"""
    ensure_pyinstaller()
    
    if not compile_to_app():
        sys.exit(1)
    
    app_path = DIST_DIR / "DaemonWatcherSetup.app"
    copy_to_usb(app_path)
    
    print("=" * 70)
    print("✅ WIZARD COMPILED AND READY FOR DISTRIBUTION")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    main()
