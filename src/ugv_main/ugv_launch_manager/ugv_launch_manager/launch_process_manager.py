#!/usr/bin/env python3
"""
Launch Process Manager
Manages subprocess lifecycle for ROS2 launch files
"""

import subprocess
import signal
import time
import os
from typing import Optional, Dict, List


class LaunchProcessManager:
    """Manages launch file processes"""

    def __init__(self, logger=None):
        self.logger = logger
        self.active_process: Optional[subprocess.Popen] = None
        self.current_mode: str = 'idle'
        self.process_start_time: Optional[float] = None

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

            # Start process
            self.active_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                preexec_fn=os.setsid  # Create new process group
            )

            self.process_start_time = time.time()

            # Wait a bit to check if process started successfully
            time.sleep(1.0)

            if self.active_process.poll() is not None:
                # Process already died
                if self.logger:
                    self.logger.error(f"Launch process died immediately with code {self.active_process.returncode}")
                return False

            if self.logger:
                self.logger.info(f"Launch process started successfully (PID: {self.active_process.pid})")

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

            # Send SIGINT to process group (like Ctrl+C)
            try:
                os.killpg(os.getpgid(pid), signal.SIGINT)
            except ProcessLookupError:
                # Process already dead
                self.active_process = None
                return True

            # Wait for graceful shutdown
            start_time = time.time()
            while time.time() - start_time < timeout:
                if self.active_process.poll() is not None:
                    if self.logger:
                        self.logger.info("Launch process stopped gracefully")
                    self.active_process = None
                    return True
                time.sleep(0.5)

            # Force kill if still running
            if self.logger:
                self.logger.warn(f"Force killing process (PID: {pid})...")

            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass

            self.active_process = None
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
