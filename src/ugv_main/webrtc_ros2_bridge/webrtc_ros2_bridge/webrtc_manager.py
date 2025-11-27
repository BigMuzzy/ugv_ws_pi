"""WebRTC connection manager for peer connections and data channels."""
import asyncio
import json
import uuid

try:
    from aiortc import (
        RTCPeerConnection,
        RTCSessionDescription,
        RTCConfiguration,
        RTCIceServer,
    )
    from aiortc.contrib.media import MediaRelay
    AIORTC_AVAILABLE = True
except ImportError:
    AIORTC_AVAILABLE = False


class WebRTCManager:
    """Manage WebRTC peer connections and data channels."""

    def __init__(
        self,
        stun_servers=None,
        turn_servers=None,
        on_command=None,
        on_emergency_stop=None,
        logger=None
    ):
        """
        Initialize WebRTC manager.

        Args:
            stun_servers: List of STUN server URLs
            turn_servers: List of TURN server configurations
            on_command: Callback for velocity commands
            on_emergency_stop: Callback for emergency stop
            logger: Logger instance
        """
        self._stun_servers = stun_servers or ["stun:stun.l.google.com:19302"]
        self._turn_servers = turn_servers or []
        self._on_command = on_command
        self._on_emergency_stop = on_emergency_stop
        self._logger = logger

        self._peer_connections = {}
        self._data_channels = {}
        self._video_track = None

        if AIORTC_AVAILABLE:
            self._relay = MediaRelay()
        else:
            self._relay = None

    def _get_rtc_config(self):
        """Get RTCConfiguration with ICE servers."""
        if not AIORTC_AVAILABLE:
            return None

        ice_servers = []

        # Add STUN servers
        for url in self._stun_servers:
            ice_servers.append(RTCIceServer(urls=[url]))

        # Add TURN servers
        for turn in self._turn_servers:
            ice_servers.append(RTCIceServer(
                urls=[turn.get("url", "")],
                username=turn.get("username"),
                credential=turn.get("credential")
            ))

        return RTCConfiguration(iceServers=ice_servers)

    def set_video_track(self, track):
        """
        Set the video track to add to peer connections.

        Args:
            track: Video track instance
        """
        self._video_track = track

    async def create_peer_connection(self, peer_id=None):
        """
        Create a new peer connection.

        Args:
            peer_id: Optional peer identifier

        Returns:
            Tuple of (peer_id, RTCPeerConnection)
        """
        if not AIORTC_AVAILABLE:
            if self._logger:
                self._logger.error("aiortc not available")
            return None, None

        if peer_id is None:
            peer_id = str(uuid.uuid4())

        config = self._get_rtc_config()
        pc = RTCPeerConnection(configuration=config)

        # Store the connection
        self._peer_connections[peer_id] = pc

        # Set up event handlers
        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            if self._logger:
                self._logger.info(
                    f"Connection state ({peer_id}): {pc.connectionState}"
                )
            if pc.connectionState == "failed":
                await self.close_peer_connection(peer_id)
            elif pc.connectionState == "closed":
                self._cleanup_peer(peer_id)

        @pc.on("datachannel")
        def on_datachannel(channel):
            if self._logger:
                self._logger.info(f"Data channel received: {channel.label}")
            self._setup_data_channel(peer_id, channel)

        @pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            if self._logger:
                self._logger.info(
                    f"ICE connection state ({peer_id}): {pc.iceConnectionState}"
                )

        # Add video track if available
        if self._video_track and self._relay:
            pc.addTrack(self._relay.subscribe(self._video_track))

        return peer_id, pc

    def _setup_data_channel(self, peer_id, channel):
        """Set up data channel event handlers."""
        self._data_channels[peer_id] = channel

        @channel.on("message")
        def on_message(message):
            self._handle_data_message(peer_id, message)

        @channel.on("close")
        def on_close():
            if self._logger:
                self._logger.info(f"Data channel closed for peer {peer_id}")
            # Trigger emergency stop on disconnect
            if self._on_emergency_stop:
                self._on_emergency_stop(True)

    def _handle_data_message(self, peer_id, message):
        """Handle incoming data channel message."""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")

            if msg_type == "cmd_vel":
                if self._on_command:
                    linear = data.get("linear", {})
                    angular = data.get("angular", {})
                    self._on_command(
                        linear.get("x", 0),
                        linear.get("y", 0),
                        linear.get("z", 0),
                        angular.get("x", 0),
                        angular.get("y", 0),
                        angular.get("z", 0)
                    )
            elif msg_type == "emergency_stop":
                if self._on_emergency_stop:
                    active = data.get("active", True)
                    self._on_emergency_stop(active)
            elif msg_type == "ping":
                # Respond with pong for latency measurement
                self.send_to_peer(peer_id, {
                    "type": "pong",
                    "timestamp": data.get("timestamp", 0)
                })

        except json.JSONDecodeError:
            if self._logger:
                self._logger.warn(f"Invalid JSON message from {peer_id}")
        except Exception as e:
            if self._logger:
                self._logger.error(f"Error handling message: {e}")

    async def handle_offer(self, peer_id, sdp):
        """
        Handle SDP offer from client.

        Args:
            peer_id: Peer identifier
            sdp: SDP offer string

        Returns:
            SDP answer string or None
        """
        if not AIORTC_AVAILABLE:
            return None

        # Create peer connection if not exists
        if peer_id not in self._peer_connections:
            peer_id, pc = await self.create_peer_connection(peer_id)
            if pc is None:
                return None
        else:
            pc = self._peer_connections[peer_id]

        # Set remote description
        offer = RTCSessionDescription(sdp=sdp, type="offer")
        await pc.setRemoteDescription(offer)

        # Create and set local description
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return pc.localDescription.sdp

    async def handle_ice_candidate(self, peer_id, candidate):
        """
        Handle ICE candidate from client.

        Args:
            peer_id: Peer identifier
            candidate: ICE candidate data
        """
        if not AIORTC_AVAILABLE:
            return

        if peer_id not in self._peer_connections:
            if self._logger:
                self._logger.warn(f"Unknown peer for ICE candidate: {peer_id}")
            return

        # aiortc handles ICE candidates automatically through the offer/answer
        # exchange, so this is mainly for completeness
        pass

    def send_to_peer(self, peer_id, data):
        """
        Send data to a specific peer via data channel.

        Args:
            peer_id: Peer identifier
            data: Data to send (will be JSON encoded)
        """
        if peer_id in self._data_channels:
            channel = self._data_channels[peer_id]
            if channel.readyState == "open":
                channel.send(json.dumps(data))

    def send_to_all(self, data):
        """
        Send data to all connected peers.

        Args:
            data: Data to send (will be JSON encoded)
        """
        for peer_id in self._data_channels:
            self.send_to_peer(peer_id, data)

    async def close_peer_connection(self, peer_id):
        """
        Close a peer connection.

        Args:
            peer_id: Peer identifier
        """
        if peer_id in self._peer_connections:
            pc = self._peer_connections[peer_id]
            await pc.close()
            self._cleanup_peer(peer_id)

    def _cleanup_peer(self, peer_id):
        """Clean up peer connection resources."""
        self._peer_connections.pop(peer_id, None)
        self._data_channels.pop(peer_id, None)

    async def close_all(self):
        """Close all peer connections."""
        for peer_id in list(self._peer_connections.keys()):
            await self.close_peer_connection(peer_id)

    @property
    def connected_peers(self):
        """Return list of connected peer IDs."""
        return list(self._peer_connections.keys())

    @property
    def peer_count(self):
        """Return number of connected peers."""
        return len(self._peer_connections)
