#!/usr/bin/env python3
"""
Lifecycle Client Helper

Wraps ROS2 lifecycle service calls (ChangeState, GetState) for a single
managed node with timeout handling and convenience methods.
"""

import time

from rclpy.node import Node
from rclpy.callback_groups import CallbackGroup

from lifecycle_msgs.srv import ChangeState, GetState
from lifecycle_msgs.msg import State, Transition


class LifecycleClient:
    """Manages lifecycle transitions for a single ROS2 lifecycle node."""

    def __init__(
        self,
        node: Node,
        managed_node_name: str,
        callback_group: CallbackGroup,
        timeout: float = 10.0,
    ):
        self._node = node
        self._name = managed_node_name
        self._timeout = timeout
        self._logger = node.get_logger()

        self._change_state_client = node.create_client(
            ChangeState,
            f'/{managed_node_name}/change_state',
            callback_group=callback_group,
        )
        self._get_state_client = node.create_client(
            GetState,
            f'/{managed_node_name}/get_state',
            callback_group=callback_group,
        )

    @property
    def name(self) -> str:
        return self._name

    def _spin_until_future(self, future, timeout: float = None) -> bool:
        """Wait for the future to complete or timeout.

        Uses polling instead of rclpy.spin_once() because the
        MultiThreadedExecutor is already spinning the node.  Calling
        spin_once() from a background thread causes 'generator already
        executing' errors and corrupts the executor wait-set.
        """
        timeout = timeout if timeout is not None else self._timeout
        start = time.monotonic()
        while not future.done():
            time.sleep(0.05)
            if time.monotonic() - start > timeout:
                self._logger.warn(
                    f"[{self._name}] Service call timed out after {timeout}s"
                )
                return False
        return True

    def get_state(self, timeout: float = None) -> int:
        """Query the current lifecycle state. Returns state ID or -1 on failure."""
        timeout = timeout if timeout is not None else self._timeout
        if not self._get_state_client.wait_for_service(timeout_sec=min(timeout, 5.0)):
            self._logger.info(f"[{self._name}] get_state service not available")
            return -1

        request = GetState.Request()
        future = self._get_state_client.call_async(request)

        if not self._spin_until_future(future, timeout):
            return -1

        result = future.result()
        if result is None:
            return -1
        return result.current_state.id

    def change_state(self, transition_id: int, timeout: float = None) -> bool:
        """Request a lifecycle transition. Returns True on success."""
        timeout = timeout if timeout is not None else self._timeout
        if not self._change_state_client.wait_for_service(
            timeout_sec=min(timeout, 5.0)
        ):
            self._logger.warn(f"[{self._name}] change_state service not available")
            return False

        request = ChangeState.Request()
        request.transition = Transition()
        request.transition.id = transition_id

        transition_name = self._transition_name(transition_id)
        self._logger.info(f"[{self._name}] Requesting transition: {transition_name}")

        future = self._change_state_client.call_async(request)

        if not self._spin_until_future(future, timeout):
            self._logger.error(
                f"[{self._name}] Transition {transition_name} timed out"
            )
            return False

        result = future.result()
        if result is None or not result.success:
            self._logger.error(f"[{self._name}] Transition {transition_name} failed")
            return False

        self._logger.info(f"[{self._name}] Transition {transition_name} succeeded")
        return True

    def wait_for_state(
        self, expected_state_id: int, timeout: float = None, poll_interval: float = 0.2
    ) -> bool:
        """Poll get_state until the expected state is reached or timeout."""
        timeout = timeout if timeout is not None else self._timeout
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            state = self.get_state(timeout=2.0)
            if state == expected_state_id:
                return True
            time.sleep(poll_interval)
        self._logger.warn(
            f"[{self._name}] Timed out waiting for state "
            f"{self._state_name(expected_state_id)}, current: {self._state_name(state)}"
        )
        return False

    def configure_and_activate(self, timeout: float = None) -> bool:
        """Configure then activate. Returns True if node reaches ACTIVE state."""
        timeout = timeout if timeout is not None else self._timeout

        current = self.get_state(timeout=5.0)
        if current == -1:
            self._logger.error(f"[{self._name}] Cannot get state, node may not exist")
            return False

        # If already active, nothing to do
        if current == State.PRIMARY_STATE_ACTIVE:
            self._logger.info(f"[{self._name}] Already active")
            return True

        # If inactive (already configured), just activate
        if current == State.PRIMARY_STATE_INACTIVE:
            return self.change_state(Transition.TRANSITION_ACTIVATE, timeout)

        # If unconfigured, configure first
        if current == State.PRIMARY_STATE_UNCONFIGURED:
            if not self.change_state(Transition.TRANSITION_CONFIGURE, timeout):
                return False
            # Wait for INACTIVE state after configure
            if not self.wait_for_state(State.PRIMARY_STATE_INACTIVE, timeout=5.0):
                return False
            return self.change_state(Transition.TRANSITION_ACTIVATE, timeout)

        self._logger.error(
            f"[{self._name}] Cannot configure_and_activate from state "
            f"{self._state_name(current)}"
        )
        return False

    def deactivate_and_cleanup(self, timeout: float = None) -> bool:
        """Deactivate then cleanup to unconfigured. Returns True on success.

        If the node's lifecycle services are not available (e.g., node not
        yet launched or already gone), this returns True — there is nothing
        to deactivate.
        """
        timeout = timeout if timeout is not None else self._timeout

        current = self.get_state(timeout=5.0)
        if current == -1:
            self._logger.info(
                f"[{self._name}] Lifecycle services not available, "
                f"assuming already clean"
            )
            return True

        # Already unconfigured, nothing to do
        if current == State.PRIMARY_STATE_UNCONFIGURED:
            self._logger.info(f"[{self._name}] Already unconfigured")
            return True

        # If active, deactivate first
        if current == State.PRIMARY_STATE_ACTIVE:
            if not self.change_state(Transition.TRANSITION_DEACTIVATE, timeout):
                return False
            if not self.wait_for_state(State.PRIMARY_STATE_INACTIVE, timeout=5.0):
                return False

        # If inactive, cleanup to unconfigured
        current = self.get_state(timeout=2.0)
        if current == State.PRIMARY_STATE_INACTIVE:
            if not self.change_state(Transition.TRANSITION_CLEANUP, timeout):
                return False
            return self.wait_for_state(
                State.PRIMARY_STATE_UNCONFIGURED, timeout=5.0
            )

        self._logger.warn(
            f"[{self._name}] Unexpected state {self._state_name(current)} "
            f"during deactivate_and_cleanup"
        )
        return False

    @staticmethod
    def _transition_name(transition_id: int) -> str:
        names = {
            Transition.TRANSITION_CONFIGURE: 'CONFIGURE',
            Transition.TRANSITION_CLEANUP: 'CLEANUP',
            Transition.TRANSITION_ACTIVATE: 'ACTIVATE',
            Transition.TRANSITION_DEACTIVATE: 'DEACTIVATE',
            Transition.TRANSITION_UNCONFIGURED_SHUTDOWN: 'UNCONFIGURED_SHUTDOWN',
            Transition.TRANSITION_INACTIVE_SHUTDOWN: 'INACTIVE_SHUTDOWN',
            Transition.TRANSITION_ACTIVE_SHUTDOWN: 'ACTIVE_SHUTDOWN',
        }
        return names.get(transition_id, f'UNKNOWN({transition_id})')

    @staticmethod
    def _state_name(state_id: int) -> str:
        names = {
            State.PRIMARY_STATE_UNKNOWN: 'UNKNOWN',
            State.PRIMARY_STATE_UNCONFIGURED: 'UNCONFIGURED',
            State.PRIMARY_STATE_INACTIVE: 'INACTIVE',
            State.PRIMARY_STATE_ACTIVE: 'ACTIVE',
            State.PRIMARY_STATE_FINALIZED: 'FINALIZED',
            -1: 'UNREACHABLE',
        }
        return names.get(state_id, f'UNKNOWN({state_id})')
