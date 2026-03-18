#!/usr/bin/env python3
"""
Motion Daemon Telegram Handler — Command parsing, live config updates, remote control
Handles /edit, /status, /restart, /test, /kill, and all user interactions
"""

import json
import logging
import time
import threading
import subprocess
import sys
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime


# ============================================================================
# CONFIG MAP — Maps user input to YAML keys
# ============================================================================

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
}

CONFIG_LABELS = {
    "1": "Video Duration",
    "2": "Send Video",
    "3": "Alert Hours Enabled",
    "4": "Sensitivity",
    "5": "Snapshot Quality",
    "6": "Video Quality",
    "7": "Cooldown",
    "8": "Alert Text",
    "9": "Snapshot Only",
    "10": "Check Interval",
}


# ============================================================================
# COMMAND VALIDATOR & PARSER
# ============================================================================

class CommandValidator:
    """Validate and parse user input"""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
    
    def validate_value(self, config_key: str, value_type: str, value_str: str) -> tuple[bool, Any, str]:
        """Validate and convert user input to correct type"""
        
        try:
            if value_type == "int":
                value = int(value_str)
                return True, value, str(value)
            
            elif value_type == "float":
                value = float(value_str)
                return True, value, f"{value:.2f}"
            
            elif value_type == "bool":
                if value_str.lower() in ['true', 'yes', 'on', '1']:
                    return True, True, "true"
                elif value_str.lower() in ['false', 'no', 'off', '0']:
                    return True, False, "false"
                else:
                    return False, None, "Expected: true/false"
            
            elif value_type == "string":
                return True, value_str, value_str
        
        except ValueError:
            return False, None, f"Invalid {value_type} value"
        
        return False, None, "Unknown type"
    
    def get_config_range_hint(self, idx: str) -> str:
        """Get valid range hint for setting"""
        if idx in CONFIG_MAP:
            return CONFIG_MAP[idx][2]
        return ""


# ============================================================================
# TELEGRAM COMMAND LISTENER & HANDLER
# ============================================================================

class TelegramCommandHandler:
    """Handle incoming Telegram commands"""
    
    def __init__(self, token: str, chat_id: str, daemon, safe_config, logger: logging.Logger):
        self.token = token
        self.chat_id = chat_id
        self.daemon = daemon
        self.safe_config = safe_config
        self.logger = logger
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.last_update_id = 0
        self.validator = CommandValidator(logger)
        self.is_running = False
        self.pending_kill_confirmation = False
    
    def poll_for_commands(self) -> None:
        """Continuously poll Telegram for new messages"""
        self.is_running = True
        self.logger.info("Telegram command listener started (polling mode)")
        
        while self.is_running:
            try:
                updates = self.get_updates()
                
                for update in updates:
                    message = update.get('message', {})
                    text = message.get('text', '').strip()
                    
                    if text:
                        self.handle_message(text)
                
                time.sleep(2)  # Poll every 2 seconds
            
            except Exception as e:
                self.logger.error(f"Telegram polling error: {e}")
                time.sleep(5)
    
    def get_updates(self) -> list:
        """Get updates from Telegram API"""
        try:
            import requests
            
            response = requests.get(
                f"{self.api_url}/getUpdates",
                json={"offset": self.last_update_id + 1, "timeout": 10},
                timeout=15
            )
            response.raise_for_status()
            
            data = response.json()
            updates = data.get('result', [])
            
            # Update offset
            if updates:
                self.last_update_id = updates[-1]['update_id']
            
            return updates
        
        except Exception as e:
            self.logger.debug(f"Get updates error: {e}")
            return []
    
    def send_message(self, text: str) -> bool:
        """Send message to user"""
        try:
            import requests
            
            response = requests.post(
                f"{self.api_url}/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10
            )
            response.raise_for_status()
            return True
        
        except Exception as e:
            self.logger.error(f"Send message error: {e}")
            return False
    
    def handle_message(self, text: str) -> None:
        """Route message to appropriate handler"""
        text = text.strip()
        
        if text.startswith("/edit"):
            self.handle_edit_command(text)
        elif text.startswith("/status"):
            self.handle_status_command()
        elif text.startswith("/restart"):
            self.handle_restart_command()
        elif text.startswith("/test"):
            self.handle_test_command()
        elif text.startswith("/kill"):
            self.handle_kill_command(text)
        elif text.startswith("/confirm"):
            self.handle_kill_confirmation(text)
        elif text.startswith("/logs"):
            self.handle_logs_command()
        elif text.startswith("/help"):
            self.handle_help_command()
        else:
            self.send_message("❓ Unknown command. Type /help for available commands.")
    
    def handle_edit_command(self, text: str) -> None:
        """Handle /edit command"""
        # Format: "/edit 1 20" or "/edit" (show current config)
        parts = text.split(maxsplit=2)
        
        if len(parts) == 1:
            # "/edit" without args — show current config
            self.show_current_config()
        
        elif len(parts) >= 2:
            idx = parts[1]
            
            if idx not in CONFIG_MAP:
                self.send_message(f"❌ Invalid setting number: {idx}\nValid: 1-10")
                return
            
            if len(parts) < 3:
                self.send_message(f"❌ Please provide a value.\nFormat: /edit {idx} <value>")
                return
            
            value_str = parts[2]
            config_key, value_type, hint = CONFIG_MAP[idx]
            label = CONFIG_LABELS.get(idx, config_key)
            
            # Validate input
            is_valid, value, display = self.validator.validate_value(config_key, value_type, value_str)
            
            if not is_valid:
                self.send_message(
                    f"❌ Invalid value for {label}\n"
                    f"Type: {value_type}\n"
                    f"Range: {hint}\n"
                    f"Error: {display}"
                )
                return
            
            # Update config
            old_value = self.safe_config.get(config_key)
            self.safe_config.set(config_key, value)
            
            # Confirm
            self.send_message(
                f"✅ <b>{label}</b>\n"
                f"{old_value} → {display}\n"
                f"(Changes take effect immediately)"
            )
    
    def show_current_config(self) -> None:
        """Display current configuration"""
        message = "⚙️  <b>CURRENT CONFIGURATION</b>\n\n"
        
        for idx in sorted(CONFIG_MAP.keys(), key=lambda x: int(x)):
            config_key = CONFIG_MAP[idx][0]
            label = CONFIG_LABELS[idx]
            value = self.safe_config.get(config_key)
            
            message += f"{idx}️⃣  <b>{label}</b>: {value}\n"
        
        message += "\n<i>Send: /edit &lt;number&gt; &lt;value&gt;</i>\n"
        message += "<i>Example: /edit 1 20</i>"
        
        self.send_message(message)
    
    def handle_status_command(self) -> None:
        """Handle /status command"""
        status = self.daemon.get_status()
        
        uptime_seconds = status['uptime_seconds']
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        message = (
            f"🟢 <b>DAEMON STATUS</b>\n\n"
            f"<b>Hostname:</b> {status['hostname']}\n"
            f"<b>Platform:</b> {status['platform']}\n"
            f"<b>Uptime:</b> {hours}h {minutes}m {seconds}s\n"
            f"<b>Running:</b> {'Yes ✓' if status['is_running'] else 'No ✗'}\n"
            f"<b>Motion Enabled:</b> {'Yes ✓' if status['motion_enabled'] else 'No ✗'}\n"
        )
        
        if status['last_motion'] > 0:
            last_motion = datetime.fromtimestamp(status['last_motion']).strftime("%H:%M:%S")
            message += f"<b>Last Motion:</b> {last_motion}\n"
        else:
            message += f"<b>Last Motion:</b> Never\n"
        
        self.send_message(message)
    
    def handle_restart_command(self) -> None:
        """Handle /restart command"""
        self.send_message("🔄 Restarting daemon...")
        self.daemon.is_running = False
        time.sleep(1)
        # User must manually restart (could implement auto-restart here)
    
    def handle_test_command(self) -> None:
        """Handle /test command"""
        self.send_message("📸 Sending test alert...")
        
        # Try to send test image
        try:
            import cv2
            camera_index = 0
            cap = cv2.VideoCapture(camera_index)
            
            if cap.isOpened():
                ret, frame = cap.read()
                cap.release()
                
                if ret:
                    test_file = "/tmp/test_motion.jpg"
                    cv2.imwrite(test_file, frame)
                    
                    if self.daemon.notifier:
                        self.daemon.notifier.send_photo(
                            test_file,
                            "🧪 TEST ALERT - Telegram connection working ✓"
                        )
                    
                    import os
                    os.remove(test_file)
                    return
        
        except:
            pass
        
        # Fallback: just send message
        self.send_message("✅ <b>Test successful</b>\nTelegram connection is working ✓")
    
    def handle_kill_command(self, text: str) -> None:
        """Handle /kill command (requires confirmation)"""
        if self.pending_kill_confirmation:
            self.send_message("⚠️  Confirmation already pending.\nSend /confirm yes or /confirm no")
            return
        
        self.pending_kill_confirmation = True
        self.send_message(
            "🚨 <b>SELF-DESTRUCT REQUESTED</b>\n\n"
            "This will:\n"
            "• Stop the daemon\n"
            "• Wipe all logs\n"
            "• Delete machine fingerprints\n"
            "• Clear all state files\n\n"
            "Send: <code>/confirm yes</code> to proceed\n"
            "Send: <code>/confirm no</code> to cancel"
        )
    
    def handle_kill_confirmation(self, text: str) -> None:
        """Handle /confirm command"""
        if not self.pending_kill_confirmation:
            self.send_message("❌ No pending confirmation.")
            return
        
        self.pending_kill_confirmation = False
        
        if "yes" in text.lower():
            self.send_message("💀 <b>INITIATING SELF-DESTRUCT</b>\n\nWiping all traces...")
            self.daemon.self_destruct.kill_daemon(self.daemon.notifier)
        else:
            self.send_message("✓ Self-destruct cancelled.")
    
    def handle_logs_command(self) -> None:
        """Handle /logs command"""
        try:
            log_dir = self.daemon.logs_dir
            log_files = list(log_dir.glob("daemon_*.log"))
            
            if not log_files:
                self.send_message("❌ No logs found")
                return
            
            latest_log = sorted(log_files)[-1]
            
            with open(latest_log, 'r') as f:
                lines = f.readlines()
            
            # Show last 15 lines
            last_lines = lines[-15:]
            log_text = "".join(last_lines)
            
            # Escape for Telegram
            log_text = log_text.replace("<", "&lt;").replace(">", "&gt;")
            
            message = f"📋 <b>Recent Logs</b> ({latest_log.name})\n\n<pre>{log_text}</pre>"
            
            self.send_message(message)
        
        except Exception as e:
            self.send_message(f"❌ Error reading logs: {e}")
    
    def handle_help_command(self) -> None:
        """Handle /help command"""
        message = (
            "⚡ <b>AVAILABLE COMMANDS</b>\n\n"
            "<code>/edit</code> - Show current config\n"
            "<code>/edit &lt;n&gt; &lt;value&gt;</code> - Change setting\n"
            "  Example: <code>/edit 1 20</code>\n\n"
            "<code>/status</code> - Show daemon status\n"
            "<code>/restart</code> - Restart daemon\n"
            "<code>/test</code> - Send test alert\n"
            "<code>/logs</code> - Show recent logs\n"
            "<code>/kill</code> - Self-destruct (requires confirmation)\n"
            "<code>/help</code> - Show this message\n\n"
            "<b>SETTINGS (1-10):</b>\n"
        )
        
        for idx in sorted(CONFIG_MAP.keys(), key=lambda x: int(x)):
            label = CONFIG_LABELS[idx]
            hint = CONFIG_MAP[idx][2]
            message += f"{idx}. {label} ({hint})\n"
        
        self.send_message(message)
    
    def stop_listening(self) -> None:
        """Stop command listener"""
        self.is_running = False


# ============================================================================
# INTEGRATION WITH DAEMON
# ============================================================================

def start_telegram_listener(daemon, safe_config, logger: logging.Logger) -> Optional[TelegramCommandHandler]:
    """Start Telegram command listener in background thread"""
    
    tg_cfg = safe_config.get('telegram', {})
    token = tg_cfg.get('token')
    chat_id = tg_cfg.get('chat_id')
    
    if not token or token == "YOUR_BOT_TOKEN":
        logger.error("Telegram not configured for command listener")
        return None
    
    try:
        handler = TelegramCommandHandler(token, chat_id, daemon, safe_config, logger)
        
        listener_thread = threading.Thread(
            target=handler.poll_for_commands,
            daemon=True
        )
        listener_thread.start()
        
        logger.info("✓ Telegram command listener started")
        return handler
    
    except Exception as e:
        logger.error(f"Failed to start Telegram listener: {e}")
        return None
