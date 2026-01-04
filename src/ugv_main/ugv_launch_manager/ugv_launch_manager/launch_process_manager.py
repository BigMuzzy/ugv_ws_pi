#!/usr/bin/env python3
"""
Launch Process Manager
Manages subprocess lifecycle for ROS2 launch files
"""

import os
import signal
import subprocess
import tempfile
import time
import threading
from typing import Optional, Dict


class LaunchProcessManager:
    """Manages launch file processes"""

    def __init__(self, logger=None, debug: bool = False):
        self.logger = logger
        self.debug = debug
        self.active_process: Optional[subprocess.Popen] = None
        self.current_mode: str = 'idle'
        self.process_start_time: Optional[float] = None
        self.last_log_path: Optional[str] = None
        self._output_thread: Optional[threading.Thread] = None

    def _get_popen_kwargs(self) -> Dict:
        """Return platform-appropriate kwargs for Popen process group handling."""
        if os.name == 'nt':
            # Allows sending CTRL_BREAK_EVENT to the process group.
            return {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
        return {'start_new_session': True}

    def _make_log_path(self, package: str, launch_file: str) -> str:
        safe_name = f"{package}__{launch_file}".replace(os.sep, '_').replace(':', '_')
        log_dir = os.path.join(tempfile.gettempdir(), 'ugv_launch_manager')
        os.makedirs(log_dir, exist_ok=True)
        return os.path.join(log_dir, f"{safe_name}.log")

    def _tee_subprocess_output(self, log_path: str):
        """Continuously drain child stdout to avoid deadlocks and persist output."""
        proc = self.active_process
        if not proc or not proc.stdout:
            return

        try:
            with open(log_path, 'a', encoding='utf-8', errors='replace') as log_file:
                for line in proc.stdout:
                    # Keep console output for debug mode.
                    print(line, end='')
                    log_file.write(line)
                    log_file.flush()
        except Exception:
            # Best-effort output capture; avoid crashing the manager.
            return

    def start_launch(self, package: str, launch_file: str,
                    arguments: Optional[Dict[str, str]] = None) -> bool:
        """
        Start a ROS2 launch file as subprocess

        Args:
            package: ROS2 package name
            launch_file: Launch file name
            arguments: Optional launch arguments dict

        Returns:
            True if launch started successfully
        """
        try:
            # Build command
            cmd = ['ros2', 'launch', package, launch_file]

            # Add arguments
            if arguments:
                for key, value in arguments.items():
                    cmd.append(f'{key}:={value}')

            # Log command
            if self.logger:
                self.logger.info(f"Starting launch: {' '.join(cmd)}")
            else:
                print(f"Starting launch: {' '.join(cmd)}")

            # Source ROS2 environment
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'  # Ensure real-time output

            popen_kwargs = self._get_popen_kwargs()

            # Always keep a log file path so failures are diagnosable.
            self.last_log_path = self._make_log_path(package, launch_file)

            # Start process
            # In debug mode, tee output to console and file (avoid PIPE buffer deadlocks).
            if self.debug:
                self.active_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=env,
                    **popen_kwargs,
                )

                self._output_thread = threading.Thread(
                    target=self._tee_subprocess_output,
                    args=(self.last_log_path,),
                    daemon=True,
                )
                self._output_thread.start()
            else:
                with open(self.last_log_path, 'ab', buffering=0) as log_file:
                    self.active_process = subprocess.Popen(
                        cmd,
                        stdout=log_file,
                        stderr=log_file,
                        env=env,
                        **popen_kwargs,
                    )

            self.process_start_time = time.time()

            # Wait a bit to check if process started successfully
            time.sleep(1.0)

            if self.active_process.poll() is not None:
                # Process already died
                if self.logger:
                    self.logger.error(f"Launch process died immediately with code {self.active_process.returncode}")
                    self.logger.error(f"See log: {self.last_log_path}")
                return False

            if self.logger:
                self.logger.info(f"Launch process started successfully (PID: {self.active_process.pid})")
                self.logger.info(f"Logging to: {self.last_log_path}")

            return True

        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to start launch: {e}")
            else:
                print(f"Failed to start launch: {e}")
            return False

    def stop_launch(self, timeout: float = 10.0) -> bool:
        """
        Stop currently running launch process

        Args:
            timeout: Seconds to wait for graceful shutdown

        Returns:
            True if stopped successfully
        """
        if not self.active_process:
            if self.logger:
                self.logger.warn("No active process to stop")
            return True

        try:
            pid = self.active_process.pid

            if self.logger:
                self.logger.info(f"Stopping launch process (PID: {pid})...")

            # Politely request shutdown
            try:
                if os.name == 'nt':
                    # Best-effort Ctrl+Break to the new process group.
                    self.active_process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(os.getpgid(pid), signal.SIGINT)
            except (ProcessLookupError, AttributeError):
                # Process already dead or signal not supported
                self.active_process = None
                return True

            # Wait for graceful shutdown
            start_time = time.time()
            while time.time() - start_time < timeout:
                if self.active_process.poll() is not None:
                    if self.logger:
                        self.logger.info("Launch process stopped gracefully")
                    self.active_process = None
                    self._output_thread = None
                    return True
                time.sleep(0.5)

            # Force kill if still running
            if self.logger:
                self.logger.warn(f"Force killing process (PID: {pid})...")

            try:
                if os.name == 'nt':
                    self.active_process.kill()
                else:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass

            self.active_process = None
            self._output_thread = None
            return True

        except Exception as e:
            if self.logger:
                self.logger.error(f"Error stopping launch: {e}")
            return False

    def get_status(self) -> Dict:
        """
        Get current process status

        Returns:
            Status dict with mode, active, pid, uptime
        """
        status = {
            'mode': self.current_mode,
            'is_active': self.is_active(),
            'pid': self.active_process.pid if self.active_process else None,
            'uptime': self.get_uptime()
        }
        return status

    def is_active(self) -> bool:
        """Check if process is currently active"""
        if not self.active_process:
            return False
        return self.active_process.poll() is None

    def get_uptime(self) -> Optional[float]:
        """Get process uptime in seconds"""
        if not self.process_start_time or not self.is_active():
            return None
        return time.time() - self.process_start_time

    def set_mode(self, mode: str):
        """Set current mode name"""
        self.current_mode = mode
