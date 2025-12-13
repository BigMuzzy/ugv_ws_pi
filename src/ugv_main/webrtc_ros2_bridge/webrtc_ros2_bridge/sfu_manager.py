import asyncio
import logging
import json
import time
from .cloudflare_calls import CloudflareCallsClient
from .video_source import VideoStreamTrack

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
    AIORTC_AVAILABLE = True
except ImportError:
    AIORTC_AVAILABLE = False

class SFUManager:
    """Manages WebRTC connection to Cloudflare Realtime SFU.

    Handles:
    - Video track publishing to SFU
    - DataChannel subscription for receiving commands
    - SDP negotiation and renegotiation
    - Session recovery on connection failures
    """

    def __init__(self, calls_client: CloudflareCallsClient, video_source=None, on_command=None, on_session_recovered=None, logger=None):
        self.calls_client = calls_client
        self.video_source = video_source
        self.on_command = on_command
        self.on_session_recovered = on_session_recovered  # Callback when session is recreated
        self.logger = logger or logging.getLogger(__name__)
        self.pc = None
        self.data_channels = {}  # channel_name -> RTCDataChannel
        self._video_track = None
        self._video_track_name = None
        self._is_recovering = False  # Prevent multiple concurrent recoveries
        self._health_check_task = None  # Background health monitoring task
        self._recovery_attempts = 0  # Track consecutive recovery attempts for backoff
        self._last_recovery_time = 0  # Timestamp of last recovery attempt

    async def connect(self):
        """Establish WebRTC connection to SFU and publish video track.
        
        Also sets up SCTP transport for DataChannels by creating a dummy channel.
        """
        if not AIORTC_AVAILABLE:
            self.logger.error("aiortc not available")
            return False

        try:
            # Create peer connection with Cloudflare STUN server
            config = RTCConfiguration(iceServers=[
                RTCIceServer(urls=["stun:stun.cloudflare.com:3478"])
            ])
            self.pc = RTCPeerConnection(configuration=config)
            
            # Set up event handlers
            @self.pc.on("datachannel")
            def on_datachannel(channel):
                self.logger.info(f"Received DataChannel: {channel.label}")
                self.data_channels[channel.label] = channel
                self._setup_datachannel(channel)
            
            @self.pc.on("connectionstatechange")
            async def on_connectionstatechange():
                state = self.pc.connectionState
                self.logger.info(f"Connection state: {state}")

                # CRITICAL: Stop robot on connection failure to prevent runaway
                if state in ('failed', 'disconnected', 'closed'):
                    self.logger.error(f"PeerConnection {state} - sending STOP command and triggering session recovery")
                    if self.on_command:
                        self.on_command(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

                    # Trigger session recovery
                    asyncio.create_task(self._recover_session())

            @self.pc.on("iceconnectionstatechange")
            async def on_iceconnectionstatechange():
                state = self.pc.iceConnectionState
                self.logger.info(f"ICE connection state: {state}")

                # CRITICAL: Stop robot on ICE failure to prevent runaway
                if state in ('failed', 'disconnected', 'closed'):
                    self.logger.error(f"ICE connection {state} - sending STOP command and triggering session recovery")
                    if self.on_command:
                        self.on_command(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

                    # Trigger session recovery
                    asyncio.create_task(self._recover_session())

            # Add video track if available
            transceivers = []
            if self.video_source:
                self._video_track = VideoStreamTrack(self.video_source, logger=self.logger)
                transceiver = self.pc.addTransceiver(self._video_track, direction="sendonly")
                transceivers.append(transceiver)
                self.logger.info("Added video track to peer connection")

            # Create a DataChannel to establish SCTP transport in the SDP
            # This ensures we can subscribe to remote DataChannels later
            # Use negotiated=True with a high ID to avoid conflicts with SFU-assigned IDs
            self._sctp_channel = self.pc.createDataChannel(
                "robot-events", 
                negotiated=True, 
                id=999  # High ID to avoid conflicts with SFU-assigned IDs (0, 1, 2, etc.)
            )
            self.logger.info("Added robot-events DataChannel for SCTP transport (id=999)")

            # Create and set local offer (now includes video + datachannel)
            offer = await self.pc.createOffer()
            await self.pc.setLocalDescription(offer)
            self.logger.info("Created local SDP offer")

            # Build tracks array for Calls API
            tracks = []
            for t in transceivers:
                track_name = f"robot_video_{self.calls_client.session_id[:8]}"
                tracks.append({
                    "location": "local",
                    "mid": t.mid,
                    "trackName": track_name
                })
                self._video_track_name = track_name

            # Send offer to SFU and get answer
            response = await self.calls_client.add_tracks(
                session_id=self.calls_client.session_id,
                sdp=offer.sdp,
                tracks=tracks
            )
            
            if response and 'sessionDescription' in response:
                answer_sdp = response['sessionDescription']['sdp']
                answer = RTCSessionDescription(sdp=answer_sdp, type='answer')
                await self.pc.setRemoteDescription(answer)
                self.logger.info("SFU Connection Established (with SCTP transport)")

                # Start proactive health monitoring
                if self._health_check_task:
                    self._health_check_task.cancel()
                self._health_check_task = asyncio.create_task(self._health_monitor_loop())

                return True
            else:
                self.logger.error("No session description in SFU response")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to connect to SFU: {e}")
            return False

    async def subscribe_to_datachannel(self, remote_session_id, channel_name):
        """Subscribe to a remote DataChannel (e.g., cmd_vel from operator).
        
        IMPORTANT: This assumes SCTP transport was already established during connect().
        We only call /datachannels/new to subscribe - NO renegotiation needed.
        
        DataChannels in Cloudflare SFU are unidirectional:
        - Operator creates a "local" datachannel and sends to it
        - Robot subscribes to it as "remote" and receives data
        
        Args:
            remote_session_id: The operator's SFU session ID
            channel_name: Name of the DataChannel to subscribe to
        """
        if not self.pc:
            self.logger.error("No peer connection available")
            return False
            
        try:
            self.logger.info(f"Subscribing to DataChannel '{channel_name}' from session {remote_session_id}")
            
            # Subscribe to the remote datachannel using /datachannels/new
            # SCTP transport is already established from connect()
            dc_response = await self.calls_client.create_datachannel(
                session_id=self.calls_client.session_id,
                channel_name=channel_name,
                location="remote",
                remote_session_id=remote_session_id
            )
            
            self.logger.info(f"DataChannel subscription response: {dc_response}")
            
            if dc_response and 'dataChannels' in dc_response and len(dc_response['dataChannels']) > 0:
                dc_info = dc_response['dataChannels'][0]
                
                if 'errorCode' in dc_info:
                    self.logger.error(f"DataChannel error: {dc_info.get('errorDescription')}")
                    return False
                    
                dc_id = dc_info.get('id')
                
                if dc_id is not None:
                    # Create a negotiated datachannel with the returned ID
                    channel = self.pc.createDataChannel(
                        f"{channel_name}_subscribed",
                        negotiated=True,
                        id=dc_id
                    )
                    self.data_channels[channel_name] = channel
                    self._setup_datachannel(channel)
                    
                    # Debug: Check SCTP transport state
                    if hasattr(self.pc, '_RTCPeerConnection__sctp') and self.pc._RTCPeerConnection__sctp:
                        sctp = self.pc._RTCPeerConnection__sctp
                        self.logger.info(f"SCTP state: {sctp.state if hasattr(sctp, 'state') else 'unknown'}")
                    
                    self.logger.info(f"Created negotiated DataChannel '{channel_name}' with id={dc_id}, readyState={channel.readyState}")
                    
                    # Wait for channel to open
                    for _ in range(50):  # 5 seconds total
                        if channel.readyState == "open":
                            self.logger.info(f"DataChannel '{channel_name}' is now open!")
                            return True
                        await asyncio.sleep(0.1)
                    
                    self.logger.warning(f"DataChannel '{channel_name}' still in state: {channel.readyState} after 5s")
                    return True  # Might open later
            
            self.logger.warning(f"No datachannel ID in response: {dc_response}")
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to subscribe to DataChannel: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def _setup_datachannel(self, channel):
        """Set up event handlers for a DataChannel."""
        channel_label = channel.label

        @channel.on("open")
        def on_open():
            self.logger.info(f"DataChannel '{channel_label}' opened")

        @channel.on("close")
        def on_close():
            self.logger.warning(f"DataChannel '{channel_label}' closed - stopping robot commands")
            if channel_label in self.data_channels:
                del self.data_channels[channel_label]

            # CRITICAL: Stop the robot when DataChannel closes to prevent runaway
            # This happens when operator disconnects or connection fails
            if self.on_command and 'cmd_vel' in channel_label.lower():
                self.logger.warning("Sending STOP command due to DataChannel closure")
                # Send zero velocity to stop the robot
                self.on_command(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        @channel.on("message")
        def on_message(message):
            try:
                self.logger.info(f"DataChannel '{channel_label}' received message: {message[:100] if len(str(message)) > 100 else message}")
                if self.on_command:
                    # Parse command
                    # Expected format: { "linear": { "x": ... }, "angular": { "z": ... } }
                    if isinstance(message, bytes):
                        message = message.decode('utf-8')
                    data = json.loads(message)
                    linear = data.get("linear", {})
                    angular = data.get("angular", {})
                    self.logger.info(f"Parsed command: linear.x={linear.get('x', 0)}, angular.z={angular.get('z', 0)}")
                    self.on_command(
                        linear.get("x", 0.0), 
                        linear.get("y", 0.0), 
                        linear.get("z", 0.0),
                        angular.get("x", 0.0), 
                        angular.get("y", 0.0), 
                        angular.get("z", 0.0)
                    )
            except json.JSONDecodeError as e:
                self.logger.warning(f"Invalid JSON in command: {e}")
            except Exception as e:
                self.logger.error(f"Error processing command: {e}")

    @property
    def video_track_name(self):
        """Get the published video track name for sharing with operators."""
        return self._video_track_name

    def get_connection_state(self):
        """Get the current peer connection state.

        Returns:
            str: Connection state ('new', 'connecting', 'connected', 'disconnected', 'failed', 'closed', or None)
        """
        if self.pc:
            return self.pc.connectionState
        return None

    async def _health_monitor_loop(self):
        """Proactively monitor session health and trigger recovery if needed.

        Checks every 10 seconds:
        - Peer connection state
        - ICE connection state
        - Time since last state change (detect stale connections)

        Triggers recovery if connection is degraded but not yet fully failed.
        """
        try:
            last_check_time = time.time()
            disconnected_since = None

            while True:
                await asyncio.sleep(10)  # Check every 10 seconds

                if not self.pc or self._is_recovering:
                    continue

                conn_state = self.pc.connectionState
                ice_state = self.pc.iceConnectionState

                # Log current health status
                self.logger.debug(f"Health check: connection={conn_state}, ice={ice_state}")

                # Check for problematic states
                if conn_state in ('disconnected', 'failed', 'closed'):
                    if disconnected_since is None:
                        disconnected_since = time.time()
                        self.logger.warning(f"Connection degraded: {conn_state}, monitoring...")

                    # If disconnected for more than 15 seconds, trigger recovery
                    time_disconnected = time.time() - disconnected_since
                    if time_disconnected > 15:
                        self.logger.error(f"Connection {conn_state} for {time_disconnected:.1f}s - triggering recovery")
                        asyncio.create_task(self._recover_session())
                        break
                elif ice_state in ('disconnected', 'failed', 'closed'):
                    if disconnected_since is None:
                        disconnected_since = time.time()
                        self.logger.warning(f"ICE connection degraded: {ice_state}, monitoring...")

                    # If ICE disconnected for more than 15 seconds, trigger recovery
                    time_disconnected = time.time() - disconnected_since
                    if time_disconnected > 15:
                        self.logger.error(f"ICE connection {ice_state} for {time_disconnected:.1f}s - triggering recovery")
                        asyncio.create_task(self._recover_session())
                        break
                else:
                    # Connection is healthy, reset disconnect timer
                    if disconnected_since is not None:
                        self.logger.info(f"Connection recovered to healthy state: {conn_state}/{ice_state}")
                    disconnected_since = None

        except asyncio.CancelledError:
            self.logger.info("Health monitor stopped")
        except Exception as e:
            self.logger.error(f"Health monitor error: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    async def _recover_session(self):
        """Recover from a failed SFU session by creating a new one.

        This method:
        1. Closes the old peer connection
        2. Creates a new SFU session via Cloudflare Calls API
        3. Reconnects to the SFU with the new session
        4. Notifies the signaling client to advertise the new session

        Uses exponential backoff for repeated failures:
        - 1st attempt: 2 seconds delay
        - 2nd attempt: 4 seconds delay
        - 3rd attempt: 8 seconds delay
        - Max delay: 30 seconds
        - Resets after 5 minutes of stable connection
        """
        if self._is_recovering:
            self.logger.info("Session recovery already in progress, skipping")
            return

        self._is_recovering = True
        try:
            # Stop health monitoring during recovery
            if self._health_check_task:
                self._health_check_task.cancel()
                self._health_check_task = None

            # Calculate backoff delay based on recent recovery attempts
            current_time = time.time()
            time_since_last_recovery = current_time - self._last_recovery_time

            # Reset attempt counter if we've been stable for 5 minutes
            if time_since_last_recovery > 300:
                self._recovery_attempts = 0

            # Exponential backoff: 2^attempts seconds, max 30 seconds
            backoff_delay = min(2 ** self._recovery_attempts, 30)
            self._recovery_attempts += 1
            self._last_recovery_time = current_time

            self.logger.warning(f"Starting session recovery (attempt #{self._recovery_attempts}, backoff={backoff_delay}s)...")

            # Close old peer connection
            if self.pc:
                try:
                    await self.pc.close()
                except Exception as e:
                    self.logger.warning(f"Error closing old peer connection: {e}")
                self.pc = None

            # Stop old video track
            if self._video_track:
                try:
                    self._video_track.stop()
                except Exception as e:
                    self.logger.warning(f"Error stopping old video track: {e}")
                self._video_track = None

            # Clear data channels
            self.data_channels.clear()
            self._video_track_name = None

            # Wait with exponential backoff before recreating session
            self.logger.info(f"Waiting {backoff_delay}s before recovery...")
            await asyncio.sleep(backoff_delay)

            # Create new SFU session
            self.logger.info("Creating new SFU session...")
            await self.calls_client.create_session()
            self.logger.info(f"New SFU session created: {self.calls_client.session_id}")

            # Reconnect to SFU
            self.logger.info("Reconnecting to SFU...")
            success = await self.connect()

            if success:
                self.logger.info(f"Session recovery successful! New session: {self.calls_client.session_id}")

                # Reset recovery counter on success
                self._recovery_attempts = 0

                # Notify bridge node to update signaling client with new session
                if self.on_session_recovered:
                    self.on_session_recovered()

                # Validate connection after brief delay
                await asyncio.sleep(5)
                if self.pc and self.pc.connectionState == 'connected':
                    self.logger.info("Recovery validation: Connection is stable")
                else:
                    state = self.pc.connectionState if self.pc else "None"
                    self.logger.warning(f"Recovery validation: Connection state is {state}, may need another recovery")
            else:
                self.logger.error("Session recovery failed - could not reconnect to SFU")
                # Will retry with longer backoff on next failure

        except Exception as e:
            self.logger.error(f"Session recovery failed: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
        finally:
            self._is_recovering = False

    async def close(self):
        """Close the WebRTC connection and clean up resources."""
        # Stop health monitoring
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None

        # Close peer connection
        if self.pc:
            await self.pc.close()
            self.pc = None

        # Stop video track
        if self._video_track:
            self._video_track.stop()
            self._video_track = None

        # Clear data channels
        self.data_channels.clear()
