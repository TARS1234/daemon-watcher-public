#!/usr/bin/env python3
"""Daemon Watcher Install Wizard - First-time configuration wizard with GUI"""

import sys
import os
from pathlib import Path
from typing import Optional, Tuple
import subprocess
import time
import socket
import re

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None

try:
    import tkinter as tk
    from tkinter import messagebox, simpledialog
    from PIL import Image, ImageTk
except ImportError:
    print("ERROR: tkinter or PIL not available")
    print("Install with: pip install pillow")
    sys.exit(1)

import yaml
import requests

CROW_EMOJI = "🐦‍⬛"
USB_MOUNT = Path.cwd()
CONFIG_FILE = USB_MOUNT / "daemon_config.yaml"
LOGO_PATH = USB_MOUNT / "full_watcher_logo.PNG"

class PasscodeEncryptor:
    """Encrypt passcodes for storage"""
    
    @staticmethod
    def get_key() -> bytes:
        """Get encryption key"""
        key_str = os.environ.get('DAEMON_WATCHER_KEY')
        if key_str:
            return key_str.encode()
        import hashlib
        seed = f"{socket.gethostname()}-daemon-watcher-phase1".encode()
        key_hash = hashlib.sha256(seed).digest()[:32]
        import base64
        return base64.urlsafe_b64encode(key_hash)
    
    @staticmethod
    def encrypt(passcode: str) -> str:
        """Encrypt passcode"""
        if not Fernet:
            return passcode
        try:
            cipher = Fernet(PasscodeEncryptor.get_key())
            encrypted = cipher.encrypt(passcode.encode())
            return encrypted.decode()
        except:
            return passcode

class InstallWizard:
    """Main install wizard application"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("Daemon Watcher - Setup Wizard")
        self.root.geometry("600x700")
        self.root.configure(bg='#1a1a1a')
        
        self.passcode = ""
        self.telegram_token = ""
        self.telegram_chat_id = ""
        self.machine_name = socket.gethostname()
        
        self.show_logo_screen()
    
    def show_logo_screen(self):
        """Show logo splash screen"""
        self.clear_window()
        
        frame = tk.Frame(self.root, bg='#1a1a1a')
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Load and display logo
        try:
            if LOGO_PATH.exists():
                img = Image.open(LOGO_PATH)
                img.thumbnail((500, 400), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                logo_label = tk.Label(frame, image=photo, bg='#1a1a1a')
                logo_label.image = photo
                logo_label.pack(pady=20)
        except Exception as e:
            title_label = tk.Label(frame, text="DAEMON WATCHER", font=("Arial", 32, "bold"), 
                                 fg='#00ff00', bg='#1a1a1a')
            title_label.pack(pady=20)
        
        subtitle = tk.Label(frame, text="PLUG. INSTALL. WATCH.", font=("Arial", 14), 
                          fg='#ff0000', bg='#1a1a1a')
        subtitle.pack(pady=10)
        
        desc = tk.Label(frame, text="First-time Setup Wizard", font=("Arial", 12), 
                       fg='#ffffff', bg='#1a1a1a')
        desc.pack(pady=20)
        
        # Start button
        start_btn = tk.Button(frame, text="Begin Setup →", command=self.show_passcode_screen,
                            font=("Arial", 12, "bold"), bg='#00ff00', fg='#000000',
                            padx=20, pady=10)
        start_btn.pack(pady=30)
    
    def show_passcode_screen(self):
        """Step 1: Create passcode"""
        self.clear_window()
        
        frame = tk.Frame(self.root, bg='#1a1a1a')
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        title = tk.Label(frame, text=f"{CROW_EMOJI} Create Passcode", font=("Arial", 18, "bold"),
                        fg='#00ff00', bg='#1a1a1a')
        title.pack(pady=20)
        
        desc = tk.Label(frame, text="6-16 alphanumeric characters (no emoji/symbols)",
                       font=("Arial", 11), fg='#cccccc', bg='#1a1a1a', wraplength=500)
        desc.pack(pady=10)
        
        tk.Label(frame, text="Passcode:", font=("Arial", 11), fg='#ffffff', bg='#1a1a1a').pack(anchor=tk.W, padx=20)
        passcode_entry = tk.Entry(frame, font=("Arial", 12), width=30, show="•")
        passcode_entry.pack(pady=10, padx=20)
        passcode_entry.focus()
        
        tk.Label(frame, text="Confirm:", font=("Arial", 11), fg='#ffffff', bg='#1a1a1a').pack(anchor=tk.W, padx=20)
        confirm_entry = tk.Entry(frame, font=("Arial", 12), width=30, show="•")
        confirm_entry.pack(pady=10, padx=20)
        
        error_label = tk.Label(frame, text="", font=("Arial", 10), fg='#ff0000', bg='#1a1a1a')
        error_label.pack(pady=5)
        
        def validate_and_next():
            passcode = passcode_entry.get()
            confirm = confirm_entry.get()
            
            if not passcode:
                error_label.config(text="⚠️ Passcode cannot be empty")
                return
            
            if len(passcode) < 6 or len(passcode) > 16:
                error_label.config(text="⚠️ Passcode must be 6-16 characters")
                return
            
            if not re.match(r'^[a-zA-Z0-9]+$', passcode):
                error_label.config(text="⚠️ Only alphanumeric characters allowed")
                return
            
            if passcode != confirm:
                error_label.config(text="⚠️ Passcodes don't match")
                return
            
            self.passcode = passcode
            self.show_telegram_token_screen()
        
        next_btn = tk.Button(frame, text="Next →", command=validate_and_next,
                           font=("Arial", 12, "bold"), bg='#00ff00', fg='#000000',
                           padx=20, pady=10)
        next_btn.pack(pady=30)
    
    def show_telegram_token_screen(self):
        """Step 2: Get Telegram bot token"""
        self.clear_window()
        
        frame = tk.Frame(self.root, bg='#1a1a1a')
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        title = tk.Label(frame, text=f"{CROW_EMOJI} Telegram Bot Token", font=("Arial", 18, "bold"),
                        fg='#00ff00', bg='#1a1a1a')
        title.pack(pady=20)
        
        desc = tk.Label(frame, text="Get token from @BotFather on Telegram\nPaste it below:",
                       font=("Arial", 11), fg='#cccccc', bg='#1a1a1a', wraplength=500)
        desc.pack(pady=10)
        
        tk.Label(frame, text="Bot Token:", font=("Arial", 11), fg='#ffffff', bg='#1a1a1a').pack(anchor=tk.W, padx=20)
        token_entry = tk.Entry(frame, font=("Arial", 10), width=40)
        token_entry.pack(pady=10, padx=20)
        token_entry.focus()
        
        error_label = tk.Label(frame, text="", font=("Arial", 10), fg='#ff0000', bg='#1a1a1a')
        error_label.pack(pady=5)
        
        status_label = tk.Label(frame, text="", font=("Arial", 10), fg='#ffff00', bg='#1a1a1a')
        status_label.pack(pady=5)
        
        def validate_and_next():
            token = token_entry.get().strip()
            
            if not token:
                error_label.config(text="⚠️ Token cannot be empty")
                return
            
            error_label.config(text="")
            status_label.config(text="Testing connection...", fg='#ffff00')
            self.root.update()
            
            if self.test_telegram_token(token):
                self.telegram_token = token
                status_label.config(text="✓ Token valid!", fg='#00ff00')
                self.root.after(1000, self.show_telegram_chat_id_screen)
            else:
                error_label.config(text="⚠️ Invalid token. Check and try again.")
                status_label.config(text="")
        
        next_btn = tk.Button(frame, text="Verify & Next →", command=validate_and_next,
                           font=("Arial", 12, "bold"), bg='#00ff00', fg='#000000',
                           padx=20, pady=10)
        next_btn.pack(pady=30)
    
    def test_telegram_token(self, token: str) -> bool:
        """Test if Telegram token is valid"""
        try:
            url = f"https://api.telegram.org/bot{token}/getMe"
            response = requests.get(url, timeout=5)
            data = response.json()
            return data.get('ok', False)
        except:
            return False
    
    def show_telegram_chat_id_screen(self):
        """Step 3: Get Telegram chat ID"""
        self.clear_window()
        
        frame = tk.Frame(self.root, bg='#1a1a1a')
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        title = tk.Label(frame, text=f"{CROW_EMOJI} Telegram Chat ID", font=("Arial", 18, "bold"),
                        fg='#00ff00', bg='#1a1a1a')
        title.pack(pady=20)
        
        desc = tk.Label(frame, text="Send any message to your bot, then paste your Chat ID below.\n"
                       "Get it from @userinfobot on Telegram:",
                       font=("Arial", 11), fg='#cccccc', bg='#1a1a1a', wraplength=500)
        desc.pack(pady=10)
        
        tk.Label(frame, text="Chat ID:", font=("Arial", 11), fg='#ffffff', bg='#1a1a1a').pack(anchor=tk.W, padx=20)
        chat_id_entry = tk.Entry(frame, font=("Arial", 10), width=40)
        chat_id_entry.pack(pady=10, padx=20)
        chat_id_entry.focus()
        
        error_label = tk.Label(frame, text="", font=("Arial", 10), fg='#ff0000', bg='#1a1a1a')
        error_label.pack(pady=5)
        
        status_label = tk.Label(frame, text="", font=("Arial", 10), fg='#ffff00', bg='#1a1a1a')
        status_label.pack(pady=5)
        
        def validate_and_next():
            chat_id = chat_id_entry.get().strip()
            
            if not chat_id:
                error_label.config(text="⚠️ Chat ID cannot be empty")
                return
            
            if not chat_id.lstrip('-').isdigit():
                error_label.config(text="⚠️ Chat ID must be numeric")
                return
            
            error_label.config(text="")
            status_label.config(text="Testing connection...", fg='#ffff00')
            self.root.update()
            
            if self.test_telegram_connection(self.telegram_token, chat_id):
                self.telegram_chat_id = chat_id
                status_label.config(text="✓ Connection valid!", fg='#00ff00')
                self.root.after(1000, self.show_machine_name_screen)
            else:
                error_label.config(text="⚠️ Connection failed. Check token and chat ID.")
                status_label.config(text="")
        
        next_btn = tk.Button(frame, text="Verify & Next →", command=validate_and_next,
                           font=("Arial", 12, "bold"), bg='#00ff00', fg='#000000',
                           padx=20, pady=10)
        next_btn.pack(pady=30)
    
    def test_telegram_connection(self, token: str, chat_id: str) -> bool:
        """Test if we can send a message to Telegram"""
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": f"{CROW_EMOJI} Testing Daemon Watcher connection..."
            }
            response = requests.post(url, json=payload, timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def show_machine_name_screen(self):
        """Step 4: Set machine name (optional)"""
        self.clear_window()
        
        frame = tk.Frame(self.root, bg='#1a1a1a')
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        title = tk.Label(frame, text=f"{CROW_EMOJI} Machine Name", font=("Arial", 18, "bold"),
                        fg='#00ff00', bg='#1a1a1a')
        title.pack(pady=20)
        
        desc = tk.Label(frame, text="Give this machine a friendly name for easy identification\n"
                       f"(Leave blank to use hostname: {self.machine_name}):",
                       font=("Arial", 11), fg='#cccccc', bg='#1a1a1a', wraplength=500)
        desc.pack(pady=10)
        
        tk.Label(frame, text="Machine Name:", font=("Arial", 11), fg='#ffffff', bg='#1a1a1a').pack(anchor=tk.W, padx=20)
        name_entry = tk.Entry(frame, font=("Arial", 12), width=30)
        name_entry.insert(0, self.machine_name)
        name_entry.pack(pady=10, padx=20)
        name_entry.focus()
        name_entry.select_range(0, tk.END)
        
        error_label = tk.Label(frame, text="", font=("Arial", 10), fg='#ff0000', bg='#1a1a1a')
        error_label.pack(pady=5)
        
        def validate_and_next():
            name = name_entry.get().strip()
            
            if not name:
                name = self.machine_name
            
            if len(name) < 1 or len(name) > 32:
                error_label.config(text="⚠️ Name must be 1-32 characters")
                return
            
            self.machine_name = name
            self.show_summary_screen()
        
        next_btn = tk.Button(frame, text="Complete Setup →", command=validate_and_next,
                           font=("Arial", 12, "bold"), bg='#00ff00', fg='#000000',
                           padx=20, pady=10)
        next_btn.pack(pady=30)
    
    def show_summary_screen(self):
        """Step 5: Review and save configuration"""
        self.clear_window()
        
        frame = tk.Frame(self.root, bg='#1a1a1a')
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        title = tk.Label(frame, text=f"{CROW_EMOJI} Setup Complete", font=("Arial", 18, "bold"),
                        fg='#00ff00', bg='#1a1a1a')
        title.pack(pady=20)
        
        summary = f"""Configuration Summary:
        
Passcode: ••••••••••
Bot Token: {self.telegram_token[:10]}...
Chat ID: {self.telegram_chat_id}
Machine Name: {self.machine_name}

Ready to launch Daemon Watcher!"""
        
        summary_label = tk.Label(frame, text=summary, font=("Arial", 10), fg='#ffffff', 
                                bg='#1a1a1a', justify=tk.LEFT)
        summary_label.pack(pady=20)
        
        status_label = tk.Label(frame, text="", font=("Arial", 10), fg='#ffff00', bg='#1a1a1a')
        status_label.pack(pady=5)
        
        def save_and_launch():
            status_label.config(text="Saving configuration...", fg='#ffff00')
            self.root.update()
            
            if self.save_configuration():
                status_label.config(text="✓ Configuration saved!", fg='#00ff00')
                self.root.after(1000, self.launch_daemon)
            else:
                status_label.config(text="⚠️ Failed to save configuration", fg='#ff0000')
        
        launch_btn = tk.Button(frame, text="Launch Daemon →", command=save_and_launch,
                             font=("Arial", 12, "bold"), bg='#00ff00', fg='#000000',
                             padx=20, pady=10)
        launch_btn.pack(pady=30)
    
    def save_configuration(self) -> bool:
        """Save configuration to YAML"""
        try:
            config = {
                "telegram": {
                    "token": self.telegram_token,
                    "chat_id": self.telegram_chat_id,
                },
                "motion": {
                    "enabled": True,
                    "sensitivity": 0.5,
                    "snapshot": True,
                    "video_on_motion": True,
                    "video_duration": 15,
                    "video_quality": "low",
                    "snapshot_quality": 75,
                    "cooldown": 60,
                    "alert_text": "Motion detected",
                    "include_timestamp": True,
                    "include_hostname": True,
                    "alert_hours": {"enabled": False, "start": 9, "end": 17},
                    "audio_enabled": False,
                    "audio_format": "aac",
                    "audio_bitrate": 128,
                    "audio_channels": 1,
                },
                "security": {
                    "passcode": PasscodeEncryptor.encrypt(self.passcode),
                    "edit_machine": socket.gethostname(),
                },
                "machine": {
                    "custom_name": self.machine_name,
                },
                "daemon": {
                    "auto_start": True,
                    "check_interval": 5,
                }
            }
            
            with open(CONFIG_FILE, 'w') as f:
                yaml.dump(config, f)
            
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False
    
    def launch_daemon(self):
        """Launch the daemon process"""
        try:
            daemon_script = USB_MOUNT / "motion_daemon_core.py"
            if daemon_script.exists():
                subprocess.Popen([sys.executable, str(daemon_script)])
                self.root.after(2000, self.root.quit)
            else:
                messagebox.showerror("Error", "motion_daemon_core.py not found")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to launch daemon: {e}")
    
    def clear_window(self):
        """Clear all widgets from window"""
        for widget in self.root.winfo_children():
            widget.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    wizard = InstallWizard(root)
    root.mainloop()
