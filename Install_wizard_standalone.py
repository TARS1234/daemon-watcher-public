#!/usr/bin/env python3
"""
Daemon Watcher - Self-Building Standalone Installer
USB-only. Detects OS, builds encrypted executable on first run, then launches wizard.
"""

import sys
import os
from pathlib import Path
import subprocess
import socket
import re
import platform
import time

CROW_EMOJI = "🐦‍⬛"
USB_MOUNT = Path.cwd()
EXECUTABLE_NAME = "DaemonWatcherSetup"

def ensure_build_dependencies():
    """Install build tools for executable creation"""
    print(f"{CROW_EMOJI} Installing build dependencies (first time only)...\n")
    
    build_deps = ['pyinstaller', 'pyarmor', 'pyyaml', 'requests', 'pillow', 'cryptography', 'opencv-python']
    
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q"] + build_deps, check=True, timeout=300)
        print("✓ Build dependencies installed\n")
        return True
    except Exception as e:
        print(f"✗ Failed: {e}\n")
        return False

def detect_executable_path() -> Path:
    """Get path for platform-specific executable"""
    system = platform.system()
    if system == "Darwin":
        return USB_MOUNT / f"{EXECUTABLE_NAME}.app"
    elif system == "Windows":
        return USB_MOUNT / f"{EXECUTABLE_NAME}.exe"
    else:
        return USB_MOUNT / EXECUTABLE_NAME

def executable_exists() -> bool:
    """Check if executable already exists"""
    exe_path = detect_executable_path()
    if platform.system() == "Darwin":
        return exe_path.exists()
    else:
        return exe_path.exists() and exe_path.stat().st_size > 500000

def build_executable() -> bool:
    """Build encrypted executable using PyInstaller"""
    system = platform.system()
    exe_path = detect_executable_path()
    
    print(f"{CROW_EMOJI} Building encrypted executable for {system}...")
    print(f"This takes 2-3 minutes on first run...\n")
    
    try:
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--onefile",
            "--name", EXECUTABLE_NAME,
            "--hidden-import", "cryptography",
            "--hidden-import", "PIL",
            "--hidden-import", "yaml",
            "--hidden-import", "requests",
            "--hidden-import", "cv2",
            "--clean",
            str(__file__)
        ]
        
        if system != "Linux":
            cmd.insert(3, "--windowed")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode == 0 and exe_path.exists():
            size_mb = exe_path.stat().st_size / 1024 / 1024
            print(f"✓ Executable built: {exe_path.name} ({size_mb:.1f} MB)\n")
            return True
        else:
            print(f"✗ Build failed\n")
            if result.stderr:
                print(result.stderr[:500])
            return False
    except subprocess.TimeoutExpired:
        print("✗ Build timed out\n")
        return False
    except Exception as e:
        print(f"✗ Error: {e}\n")
        return False

def run_wizard():
    """Launch setup wizard"""
    print(f"{CROW_EMOJI} Starting setup wizard...\n")
    
    # Install runtime deps
    try:
        import yaml, requests
        from cryptography.fernet import Fernet
    except ImportError:
        print("Installing runtime dependencies...\n")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pyyaml", "requests", "cryptography", "pillow"], check=True)
        import yaml, requests
        from cryptography.fernet import Fernet
    
    try:
        import tkinter as tk
        HAS_GUI = True
    except ImportError:
        HAS_GUI = False
    
    if HAS_GUI:
        run_gui_wizard()
    else:
        run_cli_wizard()

def run_gui_wizard():
    """GUI wizard"""
    import tkinter as tk
    import yaml
    import requests
    from cryptography.fernet import Fernet
    
    class PasscodeEncryptor:
        @staticmethod
        def encrypt(passcode: str) -> str:
            try:
                import hashlib, base64
                seed = f"{socket.gethostname()}-daemon-watcher-phase1".encode()
                key_hash = hashlib.sha256(seed).digest()[:32]
                key = base64.urlsafe_b64encode(key_hash)
                cipher = Fernet(key)
                encrypted = cipher.encrypt(passcode.encode())
                return encrypted.decode()
            except:
                return passcode
    
    class Wizard:
        def __init__(self):
            self.root = tk.Tk()
            self.root.title("Daemon Watcher Setup")
            self.root.geometry("600x700")
            self.root.configure(bg='#1a1a1a')
            self.step = 0
            self.passcode = ""
            self.token = ""
            self.chat_id = ""
            self.machine_name = socket.gethostname()
            self.show_step()
        
        def clear(self):
            for w in self.root.winfo_children():
                w.destroy()
        
        def show_step(self):
            self.clear()
            
            main = tk.Frame(self.root, bg='#1a1a1a')
            main.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
            
            tk.Label(main, text=f"{CROW_EMOJI} DAEMON WATCHER", font=("Arial", 24, "bold"), fg='#00ff00', bg='#1a1a1a').pack(pady=20)
            tk.Label(main, text=f"Step {self.step + 1} of 4", font=("Arial", 11), fg='#cccccc', bg='#1a1a1a').pack(pady=10)
            
            content = tk.Frame(main, bg='#1a1a1a')
            content.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
            
            buttons = tk.Frame(main, bg='#1a1a1a')
            buttons.pack(pady=20)
            
            if self.step == 0:
                self.step_passcode(content, buttons)
            elif self.step == 1:
                self.step_token(content, buttons)
            elif self.step == 2:
                self.step_chat_id(content, buttons)
            elif self.step == 3:
                self.step_machine(content, buttons)
            else:
                self.step_done(content, buttons)
        
        def step_passcode(self, c, b):
            tk.Label(c, text="Create 6-16 character passcode", font=("Arial", 11), fg='#ffffff', bg='#1a1a1a').pack(anchor=tk.W)
            tk.Label(c, text="Passcode:", font=("Arial", 10), fg='#cccccc', bg='#1a1a1a').pack(anchor=tk.W, pady=(20, 5))
            
            p1 = tk.Entry(c, font=("Arial", 11), width=30, show="•")
            p1.pack(anchor=tk.W)
            p1.focus()
            
            tk.Label(c, text="Confirm:", font=("Arial", 10), fg='#cccccc', bg='#1a1a1a').pack(anchor=tk.W, pady=(20, 5))
            p2 = tk.Entry(c, font=("Arial", 11), width=30, show="•")
            p2.pack(anchor=tk.W)
            
            err = tk.Label(c, text="", font=("Arial", 9), fg='#ff0000', bg='#1a1a1a')
            err.pack(pady=10)
            
            def next():
                p = p1.get()
                if not (6 <= len(p) <= 16) or not re.match(r'^[a-zA-Z0-9]+$', p):
                    err.config(text="⚠️ 6-16 alphanumeric only")
                    return
                if p != p2.get():
                    err.config(text="⚠️ Passcodes don't match")
                    return
                self.passcode = p
                self.step += 1
                self.show_step()
            
            tk.Button(b, text="Next →", command=next, font=("Arial", 11, "bold"), bg='#00ff00', fg='#000000', padx=20, pady=8).pack()
        
        def step_token(self, c, b):
            tk.Label(c, text="Get from @BotFather on Telegram", font=("Arial", 11), fg='#ffffff', bg='#1a1a1a').pack(anchor=tk.W)
            tk.Label(c, text="Bot token:", font=("Arial", 10), fg='#cccccc', bg='#1a1a1a').pack(anchor=tk.W, pady=(20, 5))
            
            entry = tk.Entry(c, font=("Arial", 10), width=40)
            entry.pack(anchor=tk.W)
            entry.focus()
            
            status = tk.Label(c, text="", font=("Arial", 9), fg='#ffff00', bg='#1a1a1a')
            status.pack(pady=10)
            
            def next():
                token = entry.get().strip()
                if not token:
                    status.config(text="⚠️ Cannot be empty", fg='#ff0000')
                    return
                
                status.config(text="Testing...", fg='#ffff00')
                entry.config(state='disabled')
                self.root.update()
                
                try:
                    r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
                    if r.json().get('ok'):
                        self.token = token
                        status.config(text="✓ Valid!", fg='#00ff00')
                        self.root.after(1000, lambda: (setattr(self, 'step', self.step + 1), self.show_step()))
                    else:
                        status.config(text="⚠️ Invalid", fg='#ff0000')
                        entry.config(state='normal')
                except:
                    status.config(text="⚠️ Connection failed", fg='#ff0000')
                    entry.config(state='normal')
            
            tk.Button(b, text="Verify & Next →", command=next, font=("Arial", 11, "bold"), bg='#00ff00', fg='#000000', padx=20, pady=8).pack()
        
        def step_chat_id(self, c, b):
            tk.Label(c, text="Get from @userinfobot on Telegram", font=("Arial", 11), fg='#ffffff', bg='#1a1a1a').pack(anchor=tk.W)
            tk.Label(c, text="Chat ID:", font=("Arial", 10), fg='#cccccc', bg='#1a1a1a').pack(anchor=tk.W, pady=(20, 5))
            
            entry = tk.Entry(c, font=("Arial", 10), width=40)
            entry.pack(anchor=tk.W)
            entry.focus()
            
            status = tk.Label(c, text="", font=("Arial", 9), fg='#ffff00', bg='#1a1a1a')
            status.pack(pady=10)
            
            def next():
                chat_id = entry.get().strip()
                if not (chat_id and chat_id.lstrip('-').isdigit()):
                    status.config(text="⚠️ Must be numeric", fg='#ff0000')
                    return
                
                status.config(text="Testing...", fg='#ffff00')
                entry.config(state='disabled')
                self.root.update()
                
                try:
                    r = requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage", json={"chat_id": chat_id, "text": f"{CROW_EMOJI} Testing..."}, timeout=5)
                    if r.status_code == 200:
                        self.chat_id = chat_id
                        status.config(text="✓ Valid!", fg='#00ff00')
                        self.root.after(1000, lambda: (setattr(self, 'step', self.step + 1), self.show_step()))
                    else:
                        status.config(text="⚠️ Failed", fg='#ff0000')
                        entry.config(state='normal')
                except:
                    status.config(text="⚠️ Connection failed", fg='#ff0000')
                    entry.config(state='normal')
            
            tk.Button(b, text="Verify & Next →", command=next, font=("Arial", 11, "bold"), bg='#00ff00', fg='#000000', padx=20, pady=8).pack()
        
        def step_machine(self, c, b):
            tk.Label(c, text=f"Hostname: {self.machine_name}", font=("Arial", 11), fg='#ffffff', bg='#1a1a1a').pack(anchor=tk.W)
            tk.Label(c, text="Friendly name (optional):", font=("Arial", 10), fg='#cccccc', bg='#1a1a1a').pack(anchor=tk.W, pady=(20, 5))
            
            entry = tk.Entry(c, font=("Arial", 11), width=30)
            entry.insert(0, self.machine_name)
            entry.pack(anchor=tk.W)
            entry.select_range(0, tk.END)
            
            def next():
                name = entry.get().strip() or self.machine_name
                self.machine_name = name
                self.step += 1
                self.show_step()
            
            tk.Button(b, text="Complete Setup →", command=next, font=("Arial", 11, "bold"), bg='#00ff00', fg='#000000', padx=20, pady=8).pack()
        
        def step_done(self, c, b):
            summary = f"Configuration:\n\nBot Token: {self.token[:15]}...\nChat ID: {self.chat_id}\nMachine: {self.machine_name}\nPasscode: ••••••••"
            tk.Label(c, text=summary, font=("Arial", 10), fg='#00ff00', bg='#1a1a1a', justify=tk.LEFT).pack(pady=20)
            
            status = tk.Label(c, text="", font=("Arial", 10), fg='#ffff00', bg='#1a1a1a')
            status.pack(pady=10)
            
            def launch():
                status.config(text="Saving...", fg='#ffff00')
                self.root.update()
                
                try:
                    config = {
                        "telegram": {"token": self.token, "chat_id": self.chat_id},
                        "motion": {
                            "enabled": True, "sensitivity": 0.5, "snapshot": True,
                            "video_on_motion": True, "video_duration": 15, "video_quality": "low",
                            "snapshot_quality": 75, "cooldown": 60, "alert_text": "Motion detected",
                            "include_timestamp": True, "include_hostname": True,
                            "alert_hours": {"enabled": False, "start": 9, "end": 17},
                            "audio_enabled": False, "audio_format": "aac", "audio_bitrate": 128, "audio_channels": 1,
                        },
                        "security": {"passcode": PasscodeEncryptor.encrypt(self.passcode), "edit_machine": socket.gethostname()},
                        "machine": {"custom_name": self.machine_name},
                        "daemon": {"auto_start": True, "check_interval": 5}
                    }
                    
                    with open(USB_MOUNT / "daemon_config.yaml", 'w') as f:
                        yaml.dump(config, f)
                    
                    status.config(text="✓ Saved!", fg='#00ff00')
                    self.root.update()
                    time.sleep(1)
                    self.root.quit()
                except Exception as e:
                    status.config(text=f"⚠️ Error: {str(e)[:30]}", fg='#ff0000')
            
            tk.Button(b, text="Launch Daemon", command=launch, font=("Arial", 11, "bold"), bg='#00ff00', fg='#000000', padx=20, pady=8).pack()
        
        def run(self):
            self.root.mainloop()
    
    wizard = Wizard()
    wizard.run()

def run_cli_wizard():
    """CLI fallback wizard"""
    print(f"\n{CROW_EMOJI} DAEMON WATCHER SETUP\n")
    
    import yaml
    from cryptography.fernet import Fernet
    import hashlib, base64
    
    p = input("Passcode (6-16): ").strip()
    token = input("Telegram token: ").strip()
    chat_id = input("Chat ID: ").strip()
    machine = input(f"Machine name [{socket.gethostname()}]: ").strip() or socket.gethostname()
    
    # Encrypt passcode
    try:
        seed = f"{socket.gethostname()}-daemon-watcher-phase1".encode()
        key_hash = hashlib.sha256(seed).digest()[:32]
        key = base64.urlsafe_b64encode(key_hash)
        cipher = Fernet(key)
        encrypted_p = cipher.encrypt(p.encode()).decode()
    except:
        encrypted_p = p
    
    config = {
        "telegram": {"token": token, "chat_id": chat_id},
        "motion": {
            "enabled": True, "sensitivity": 0.5, "snapshot": True,
            "video_on_motion": True, "video_duration": 15, "video_quality": "low",
            "snapshot_quality": 75, "cooldown": 60, "alert_text": "Motion detected",
            "include_timestamp": True, "include_hostname": True,
            "alert_hours": {"enabled": False, "start": 9, "end": 17},
            "audio_enabled": False, "audio_format": "aac", "audio_bitrate": 128, "audio_channels": 1,
        },
        "security": {"passcode": encrypted_p, "edit_machine": socket.gethostname()},
        "machine": {"custom_name": machine},
        "daemon": {"auto_start": True, "check_interval": 5}
    }
    
    with open(USB_MOUNT / "daemon_config.yaml", 'w') as f:
        yaml.dump(config, f)
    
    print(f"\n✓ Configuration saved!")

def main():
    """Main entry point"""
    print("\n" + "=" * 70)
    print(f"{CROW_EMOJI} DAEMON WATCHER - PORTABLE USB SURVEILLANCE")
    print("=" * 70 + "\n")
    
    system = platform.system()
    print(f"Platform: {system}\n")
    
    exe_path = detect_executable_path()
    
    if executable_exists():
        print(f"✓ Executable found: {exe_path.name}\n")
        run_wizard()
    else:
        print(f"Building encrypted executable...\n")
        
        if not ensure_build_dependencies():
            sys.exit(1)
        
        if not build_executable():
            sys.exit(1)
        
        run_wizard()

if __name__ == "__main__":
    main()
