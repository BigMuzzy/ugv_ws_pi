"""Cloudflare SFU client for WebRTC connection management.

DataChannel Implementation Notes (Cloudflare Calls SFU):
========================================================
Cloudflare Calls SFU DataChannels are UNIDIRECTIONAL (publisher → subscribers only).

For bidirectional teleop commands, we need TWO DataChannels:
1. Robot → Viewer (telemetry) - Robot publishes, viewers subscribe
2. Viewer → Robot (commands) - Each viewer publishes, robot subscribes

The DataChannel setup requires:
1. Call /datachannels/new with location="local" to publish a channel
2. Call /datachannels/new with location="remote" and sessionId to subscribe
3. Create a negotiated DataChannel with the returned ID

Reference: https://developers.cloudflare.com/realtime/sfu/datachannels/
Example: https://github.com/cloudflare/realtime-examples/tree/main/echo-datachannels
"""
import asyncio
import json
import aiohttp

try:
    from aiortc import (
        RTCPeerConnection,
        RTCSessionDescription,
        RTCConfiguration,
        RTCIceServer,
        VideoStreamTrack,
    )
    from aiortc.contrib.media import MediaRelay, MediaPlayer
    from av import VideoFrame
    import numpy as np
    AIORTC_AVAILABLE = True
except ImportError:
    AIORTC_AVAILABLE = False


class DummyVideoTrack(VideoStreamTrack):
    """
    A dummy video track that generates blank frames.
    Replace with actual camera feed.
    """
    def __init__(self):
        super().__init__()

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        
        # Create a blank frame (640x480, black)
        frame = VideoFrame(width=640, height=480)
        frame.pts = pts
        frame.time_base = time_base
        
        return frame


class CloudflareSFUClient:
    """
    Client for connecting to Cloudflare Calls SFU.
    
    This replaces the P2P WebRTC connection with an SFU model where:
    - Robot publishes video track to Cloudflare SFU
    - Multiple viewers can watch the same robot
    - Commands come through DataChannel from SFU
    """

    def __init__(
        self,
        robot_id: str,
        workers_endpoint: str,
        video_track=None,
        on_command=None,
        on_emergency_stop=None,
        logger=None,
        fallback_mode=False
    ):
        """
        Initialize Cloudflare SFU client.

        Args:
            robot_id: Unique identifier for this robot
            workers_endpoint: URL of Cloudflare Workers backend
            video_track: Video track to publish to SFU
            on_command: Callback for velocity commands (linear, angular)
            on_emergency_stop: Callback for emergency stop
            logger: Logger instance
            fallback_mode: If True, skip SFU and use P2P fallback
        """
        self._robot_id = robot_id
        self._workers_endpoint = workers_endpoint.rstrip('/')
        self._video_track = video_track
        self._on_command = on_command
        self._on_emergency_stop = on_emergency_stop
        self._logger = logger
        self._fallback_mode = fallback_mode

        self._pc = None  # RTCPeerConnection
        self._telemetry_channel = None  # Robot → Viewers (telemetry)
        self._command_channel = None    # For receiving commands (subscribed from viewers)
        self._session_id = None
        self._ice_servers = []
        self._relay = MediaRelay() if AIORTC_AVAILABLE else None

        self._connected = False
        self._reconnect_task = None
        
        # DataChannel IDs from Cloudflare SFU
        self._telemetry_channel_id = None
        self._command_channel_id = None

    async def connect(self):
        """Connect to Cloudflare SFU and create session with DataChannels."""
        if not AIORTC_AVAILABLE:
            if self._logger:
                self._logger.error("aiortc not available - cannot connect to SFU")
            return False

        if self._fallback_mode:
            if self._logger:
                self._logger.info("SFU client in fallback mode - skipping connection")
            return False

        try:
            # Step 1: Create SFU session via Workers API
            session_info = await self._create_sfu_session()
            if not session_info:
                if self._logger:
                    self._logger.error("Failed to create SFU session")
                return False

            self._session_id = session_info['sessionId']
            self._ice_servers = session_info.get('iceServers', [])

            if self._logger:
                self._logger.info(
                    f"Created SFU session: {self._session_id}"
                )

            # Create a dummy video track if none provided (BEFORE creating peer connection)
            if not self._video_track:
                if self._logger:
                    self._logger.info("No video track provided, creating dummy track")
                self._video_track = DummyVideoTrack()

            # Step 2: Create RTCPeerConnection with ICE servers
            await self._create_peer_connection()

            # Step 3: Establish DataChannel transport first (required by Cloudflare Calls)
            # This creates a "server-events" datachannel which enables the SCTP transport
            await self._establish_datachannel_transport()

            # Step 4: Register telemetry DataChannel with SFU (Robot → Viewers)
            # This allows viewers to subscribe to our telemetry
            await self._register_telemetry_datachannel()

            # Step 5: Create offer with video track and DataChannels, send to SFU
            await self._create_and_send_offer()

            self._connected = True
            if self._logger:
                self._logger.info("Successfully connected to Cloudflare SFU")

            return True

        except Exception as e:
            if self._logger:
                self._logger.error(f"Error connecting to SFU: {e}")
            return False

    async def _establish_datachannel_transport(self):
        """
        Establish the DataChannel transport with the SFU.
        
        This is required before we can register/use DataChannels.
        We create a local 'server-events' datachannel and call the establish endpoint.
        """
        if self._logger:
            self._logger.info("Establishing DataChannel transport with SFU")
        
        # Create a local datachannel to initiate SCTP transport
        server_events_dc = self._pc.createDataChannel("server-events", negotiated=False)
        
        @server_events_dc.on("open")
        def on_open():
            if self._logger:
                self._logger.info("server-events DataChannel opened")
        
        @server_events_dc.on("message")
        def on_message(message):
            if self._logger:
                self._logger.debug(f"server-events message: {message}")
        
        # Create offer for establish
        offer = await self._pc.createOffer()
        await self._pc.setLocalDescription(offer)
        
        # Call the establish endpoint
        try:
            url = f"{self._workers_endpoint}/api/sessions/{self._robot_id}/datachannels/establish"
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json={
                        'sessionDescription': {
                            'type': self._pc.localDescription.type,
                            'sdp': self._pc.localDescription.sdp
                        },
                        'dataChannel': {
                            'location': 'remote',
                            'dataChannelName': 'server-events'
                        }
                    },
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        if self._logger:
                            self._logger.warning(
                                f"DataChannel establish returned {response.status}: {error_text}"
                            )
                        return
                    
                    data = await response.json()
                    
                    # If we got an answer, set it
                    if data.get('requiresImmediateRenegotiation') and data.get('sessionDescription'):
                        from aiortc import RTCSessionDescription
                        remote_desc = RTCSessionDescription(
                            sdp=data['sessionDescription']['sdp'],
                            type=data['sessionDescription']['type']
                        )
                        await self._pc.setRemoteDescription(remote_desc)
                        if self._logger:
                            self._logger.info("DataChannel transport established with SFU")
        except Exception as e:
            if self._logger:
                self._logger.warning(f"Error establishing DataChannel transport: {e}")

    async def _register_telemetry_datachannel(self):
        """
        Register a DataChannel for telemetry (Robot → Viewers).
        
        Cloudflare Calls DataChannels are unidirectional.
        We publish 'telemetry' channel that viewers can subscribe to.
        """
        if self._logger:
            self._logger.info("Registering telemetry DataChannel with SFU")
        
        try:
            url = f"{self._workers_endpoint}/api/sessions/{self._robot_id}/datachannels/new"
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json={
                        'dataChannels': [{
                            'location': 'local',
                            'dataChannelName': 'telemetry'
                        }]
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        if self._logger:
                            self._logger.warning(
                                f"Failed to register telemetry DataChannel: {response.status} - {error_text}"
                            )
                        return
                    
                    data = await response.json()
                    if data.get('dataChannels') and len(data['dataChannels']) > 0:
                        self._telemetry_channel_id = data['dataChannels'][0].get('id')
                        if self._logger:
                            self._logger.info(
                                f"Registered telemetry DataChannel with ID: {self._telemetry_channel_id}"
                            )
                        
                        # Create the negotiated datachannel with the returned ID
                        if self._telemetry_channel_id is not None:
                            self._telemetry_channel = self._pc.createDataChannel(
                                "telemetry",
                                negotiated=True,
                                id=self._telemetry_channel_id
                            )
                            
                            @self._telemetry_channel.on("open")
                            def on_open():
                                if self._logger:
                                    self._logger.info("Telemetry DataChannel opened")
                            
                            @self._telemetry_channel.on("error")
                            def on_error(error):
                                if self._logger:
                                    self._logger.error(f"Telemetry DataChannel error: {error}")
        except Exception as e:
            if self._logger:
                self._logger.warning(f"Error registering telemetry DataChannel: {e}")
            if self._logger:
                self._logger.error(f"Error connecting to SFU: {e}")
            return False

    async def _create_sfu_session(self):
        """Create SFU session via Workers API."""
        try:
            url = f"{self._workers_endpoint}/api/sessions/create"
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json={'robotId': self._robot_id},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        if self._logger:
                            self._logger.error(
                                f"Failed to create session: {response.status} - {error_text}"
                            )
                        return None

                    data = await response.json()
                    return data.get('session')

        except asyncio.TimeoutError:
            if self._logger:
                self._logger.error("Timeout creating SFU session")
            return None
        except Exception as e:
            if self._logger:
                self._logger.error(f"Error creating SFU session: {e}")
            return None

    async def _create_peer_connection(self):
        """Create RTCPeerConnection with ICE servers from Workers."""
        # Convert ICE servers to RTCIceServer format
        ice_servers = []
        for server in self._ice_servers:
            urls = server.get('urls', [])
            if isinstance(urls, str):
                urls = [urls]
            
            ice_server = RTCIceServer(urls=urls)
            if 'username' in server:
                ice_server.username = server['username']
            if 'credential' in server:
                ice_server.credential = server['credential']
            
            ice_servers.append(ice_server)

        # Create RTCConfiguration
        config = RTCConfiguration(iceServers=ice_servers)
        
        # Create peer connection
        self._pc = RTCPeerConnection(configuration=config)

        # Set up event handlers
        @self._pc.on("connectionstatechange")
        async def on_connectionstatechange():
            if self._logger:
                self._logger.info(
                    f"SFU connection state: {self._pc.connectionState}"
                )
            
            if self._pc.connectionState == "failed":
                if self._logger:
                    self._logger.warning("SFU connection failed, attempting reconnect")
                await self._reconnect()
            elif self._pc.connectionState == "closed":
                self._connected = False

        @self._pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            if self._logger:
                self._logger.info(
                    f"ICE connection state: {self._pc.iceConnectionState}"
                )

        @self._pc.on("datachannel")
        def on_datachannel(channel):
            """
            Handle incoming data channel from SFU.
            
            In Cloudflare Calls SFU model:
            - We may receive channels from viewers who publish commands
            - Channel names might be 'commands-{viewerId}' or similar
            """
            if self._logger:
                self._logger.info(f"Received data channel: {channel.label}, id: {channel.id}")
            
            # Accept any channel that looks like a command channel
            if 'command' in channel.label.lower():
                if self._logger:
                    self._logger.info(f"Setting up command channel: {channel.label}")
                self._command_channel = channel
                
                @channel.on("open")
                def on_open():
                    if self._logger:
                        self._logger.info(f"Command channel '{channel.label}' opened")
                
                @channel.on("message")
                def on_message(message):
                    self._handle_command_message(message)
                
                @channel.on("close")
                def on_close():
                    if self._logger:
                        self._logger.info(f"Command channel '{channel.label}' closed")
            else:
                # Log other channels for debugging
                if self._logger:
                    self._logger.debug(f"Received non-command channel: {channel.label}")
                
                @channel.on("message")
                def on_message(message):
                    if self._logger:
                        self._logger.debug(f"Message on '{channel.label}': {message}")

        # Add video track if available
        if self._video_track:
            if self._relay:
                # Use relay for existing tracks
                relayed_track = self._relay.subscribe(self._video_track)
                self._pc.addTrack(relayed_track)
            else:
                # Add track directly if no relay
                self._pc.addTrack(self._video_track)
            
            if self._logger:
                self._logger.info("Added video track to SFU connection")
        else:
            if self._logger:
                self._logger.warning("No video track available - SDP will have no media sections")

    def _handle_command_message(self, message):
        """Handle incoming command messages."""
        try:
            if self._logger:
                self._logger.info(f"Received DataChannel message: {message}")

            data = json.loads(message)
            msg_type = data.get('type')
            
            if msg_type == 'command':
                linear = data.get('linear', 0.0)
                angular = data.get('angular', 0.0)
                if self._logger:
                    self._logger.info(f"Processing command - Linear: {linear}, Angular: {angular}")
                
                if self._on_command:
                    self._on_command(linear, angular)
            
            elif msg_type == 'emergency_stop':
                if self._logger:
                    self._logger.warning("Received EMERGENCY STOP command")
                if self._on_emergency_stop:
                    self._on_emergency_stop()
            
        except json.JSONDecodeError:
            if self._logger:
                self._logger.warning(f"Invalid JSON message: {message}")
        except Exception as e:
            if self._logger:
                self._logger.error(f"Error handling message: {e}")

    async def _create_and_send_offer(self):
        """Create offer and send to SFU via Workers API."""
        # Create offer
        offer = await self._pc.createOffer()
        await self._pc.setLocalDescription(offer)

        if self._logger:
            self._logger.info("Created offer for SFU")

        # Send offer to Workers API and get answer
        try:
            url = f"{self._workers_endpoint}/api/sessions/{self._robot_id}/offer"
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json={
                        'offer': {
                            'type': self._pc.localDescription.type,
                            'sdp': self._pc.localDescription.sdp
                        }
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        if self._logger:
                            self._logger.error(
                                f"Failed to send offer: {response.status} - {error_text}"
                            )
                        return

                    data = await response.json()
                    answer = data.get('answer')
                    
                    if not answer:
                        if self._logger:
                            self._logger.error("No answer received from SFU")
                        return

                    # Set remote description with answer
                    from aiortc import RTCSessionDescription
                    remote_desc = RTCSessionDescription(
                        sdp=answer['sdp'],
                        type=answer['type']
                    )
                    await self._pc.setRemoteDescription(remote_desc)

                    if self._logger:
                        self._logger.info("Set remote description from SFU answer")

        except asyncio.TimeoutError:
            if self._logger:
                self._logger.error("Timeout sending offer to SFU")
        except Exception as e:
            if self._logger:
                self._logger.error(f"Error sending offer: {e}")

    async def disconnect(self):
        """Disconnect from SFU and clean up resources."""
        self._connected = False

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        if self._pc:
            await self._pc.close()
            self._pc = None

        # Clean up DataChannels
        self._telemetry_channel = None
        self._command_channel = None

        # Delete session via Workers API
        if self._session_id:
            try:
                url = f"{self._workers_endpoint}/api/sessions/{self._robot_id}"
                async with aiohttp.ClientSession() as session:
                    async with session.delete(
                        url,
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as response:
                        if self._logger:
                            if response.status == 200:
                                self._logger.info("Deleted SFU session")
                            else:
                                self._logger.warning(
                                    f"Failed to delete session: {response.status}"
                                )
            except Exception as e:
                if self._logger:
                    self._logger.error(f"Error deleting session: {e}")

        if self._logger:
            self._logger.info("Disconnected from SFU")

    async def _reconnect(self):
        """Attempt to reconnect to SFU with exponential backoff."""
        if self._reconnect_task and not self._reconnect_task.done():
            return  # Already reconnecting

        async def reconnect_loop():
            retry_count = 0
            max_retries = 5
            base_delay = 1.0

            while retry_count < max_retries and not self._connected:
                delay = min(base_delay * (2 ** retry_count), 30.0)
                if self._logger:
                    self._logger.info(
                        f"Reconnecting to SFU in {delay}s (attempt {retry_count + 1}/{max_retries})"
                    )
                
                await asyncio.sleep(delay)
                
                success = await self.connect()
                if success:
                    if self._logger:
                        self._logger.info("Successfully reconnected to SFU")
                    return
                
                retry_count += 1

            if self._logger:
                self._logger.error(
                    "Failed to reconnect to SFU after max retries, "
                    "consider enabling fallback mode"
                )

        self._reconnect_task = asyncio.create_task(reconnect_loop())

    def set_video_track(self, video_track):
        """Update the video track being published to SFU."""
        self._video_track = video_track
        
        # If already connected, add the new track
        if self._pc and self._relay and video_track:
            relayed_track = self._relay.subscribe(video_track)
            self._pc.addTrack(relayed_track)
            if self._logger:
                self._logger.info("Updated video track on SFU connection")

    def is_connected(self):
        """Check if connected to SFU."""
        return self._connected and self._pc and self._pc.connectionState == "connected"

    async def send_telemetry(self, data):
        """
        Send telemetry data through telemetry DataChannel.
        
        This channel is published by the robot and viewers can subscribe to it.
        
        Args:
            data: Dictionary with telemetry data
        """
        if self._telemetry_channel and self._telemetry_channel.readyState == "open":
            try:
                message = json.dumps({
                    'type': 'telemetry',
                    'data': data
                })
                self._telemetry_channel.send(message)
            except Exception as e:
                if self._logger:
                    self._logger.error(f"Error sending telemetry: {e}")
