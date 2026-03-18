#!/usr/bin/env python3
"""
PyArmor Configuration - Obfuscate and build production executables
Requires: pip install pyarmor
"""

import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path.cwd()
BUILD_DIR = PROJECT_DIR / "build"
DIST_DIR = PROJECT_DIR / "dist"
ARMORED_DIR = PROJECT_DIR / "armored"

# Files to obfuscate
FILES_TO_PROTECT = [
    "motion_daemon_core_v2.py",
    "install_wizard.py",
    "motion_daemon_telegram.py",
    "motion_daemon_launcher.py",
]

def obfuscate_with_pyarmor():
    """Obfuscate Python files with PyArmor"""
    print("=" * 60)
    print("STEP 1: Obfuscating Python files with PyArmor...")
    print("=" * 60)
    
    try:
        import pyarmor
    except ImportError:
        print("ERROR: PyArmor not installed")
        print("Install with: pip install pyarmor")
        sys.exit(1)
    
    # Create armored directory
    ARMORED_DIR.mkdir(exist_ok=True)
    
    # Run PyArmor obfuscation
    for file in FILES_TO_PROTECT:
        filepath = PROJECT_DIR / file
        if not filepath.exists():
            print(f"WARNING: {file} not found, skipping...")
            continue
        
        print(f"\n🔐 Obfuscating {file}...")
        
        try:
            # PyArmor command: obfuscate and restrict features
            cmd = [
                sys.executable, "-m", "pyarmor",
                "obfuscate",
                "--restrict",
                "--no-console",
                "-O", str(ARMORED_DIR),
                str(filepath)
            ]
            
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"✓ {file} obfuscated")
        except subprocess.CalledProcessError as e:
            print(f"ERROR obfuscating {file}: {e}")
            return False
    
    print("\n✓ All files obfuscated successfully!")
    return True

def build_with_pyinstaller():
    """Build standalone executables with PyInstaller"""
    print("\n" + "=" * 60)
    print("STEP 2: Building executables with PyInstaller...")
    print("=" * 60)
    
    try:
        import PyInstaller
    except ImportError:
        print("ERROR: PyInstaller not installed")
        print("Install with: pip install pyinstaller")
        sys.exit(1)
    
    # Build install_wizard for current platform
    print("\n🔨 Building install_wizard executable...")
    
    wizard_spec = f"""
# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['{ARMORED_DIR / "install_wizard.py"}'],
    pathex=['{ARMORED_DIR}', '{PROJECT_DIR}'],
    binaries=[],
    datas=[
        ('{PROJECT_DIR / "daemon_watcher.jpg"}', '.'),
        ('{PROJECT_DIR / "full_watcher_logo.PNG"}', '.'),
        ('{PROJECT_DIR / "daemon_config.yaml"}', '.'),
        ('{PROJECT_DIR / "motion_requirements.txt"}', '.'),
        ('{ARMORED_DIR}', '.'),
    ],
    hiddenimports=['cryptography', 'PIL', 'yaml', 'requests'],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludedimports=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DaemonWatcherSetup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
"""
    
    try:
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--onefile",
            "--windowed",
            "--name", "DaemonWatcherSetup",
            "--icon", str(PROJECT_DIR / "full_watcher_logo.PNG") if (PROJECT_DIR / "full_watcher_logo.PNG").exists() else None,
            "--add-data", f"{PROJECT_DIR / 'daemon_watcher.jpg'}:.",
            "--add-data", f"{PROJECT_DIR / 'full_watcher_logo.PNG'}:.",
            "--hidden-import", "cryptography",
            "--hidden-import", "PIL",
            "--hidden-import", "yaml",
            "--hidden-import", "requests",
            str(ARMORED_DIR / "install_wizard.py")
        ]
        
        # Remove None values
        cmd = [c for c in cmd if c is not None]
        
        subprocess.run(cmd, check=True)
        print("✓ Executable built successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR building executable: {e}")
        return False

def package_for_distribution():
    """Package everything for USB distribution"""
    print("\n" + "=" * 60)
    print("STEP 3: Packaging for USB distribution...")
    print("=" * 60)
    
    import platform
    import shutil
    
    system = platform.system()
    
    # Find executable
    if system == "Darwin":  # macOS
        exe_path = DIST_DIR / "DaemonWatcherSetup.app"
        exe_name = "DaemonWatcherSetup.app"
    elif system == "Windows":
        exe_path = DIST_DIR / "DaemonWatcherSetup.exe"
        exe_name = "DaemonWatcherSetup.exe"
    else:  # Linux
        exe_path = DIST_DIR / "DaemonWatcherSetup"
        exe_name = "DaemonWatcherSetup"
    
    if not exe_path.exists():
        print(f"ERROR: Executable not found at {exe_path}")
        return False
    
    print(f"\n📦 Packaging for {system}...")
    print(f"✓ Executable: {exe_name}")
    
    # Copy supporting files
    supporting_files = [
        "motion_daemon_core_v2.py",
        "motion_daemon_launcher.py",
        "motion_daemon_telegram.py",
        "motion_daemon_deploy.py",
        "daemon_config.yaml",
        "motion_requirements.txt",
        "daemon_watcher.jpg",
        "full_watcher_logo.PNG",
    ]
    
    usb_package_dir = DIST_DIR / f"DaemonWatcher_USB_{system}"
    usb_package_dir.mkdir(exist_ok=True)
    
    # Copy executable
    if system == "Darwin":
        shutil.copytree(exe_path, usb_package_dir / exe_name, dirs_exist_ok=True)
    else:
        shutil.copy2(exe_path, usb_package_dir / exe_name)
    
    # Copy supporting files
    for file in supporting_files:
        src = PROJECT_DIR / file
        if src.exists():
            shutil.copy2(src, usb_package_dir / file)
    
    print(f"\n✓ Package created: {usb_package_dir}")
    return True

def main():
    """Build production package"""
    print("\n" + "=" * 60)
    print("DAEMON WATCHER - PRODUCTION BUILD")
    print("=" * 60)
    
    steps = [
        ("Obfuscate with PyArmor", obfuscate_with_pyarmor),
        ("Build with PyInstaller", build_with_pyinstaller),
        ("Package for USB", package_for_distribution),
    ]
    
    for step_name, step_func in steps:
        if not step_func():
            print(f"\n❌ Build failed at: {step_name}")
            sys.exit(1)
    
    print("\n" + "=" * 60)
    print("✅ PRODUCTION BUILD COMPLETE")
    print("=" * 60)
    print(f"\nYour executable is ready in: {DIST_DIR}")
    print("Copy to USB and test on other machines!")

if __name__ == "__main__":
    main()
