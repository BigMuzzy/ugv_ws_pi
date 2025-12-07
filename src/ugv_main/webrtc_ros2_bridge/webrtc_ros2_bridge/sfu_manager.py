import asyncio
import logging
import json
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
    """
    
    def __init__(self, calls_client: CloudflareCallsClient, video_source=None, on_command=None, logger=None):
        self.calls_client = calls_client
        self.video_source = video_source
        self.on_command = on_command
        self.logger = logger or logging.getLogger(__name__)
        self.pc = None
        self.data_channels = {}  # channel_name -> RTCDataChannel
        self._video_track = None
        self._video_track_name = None

    async def connect(self):
        """Establish WebRTC connection to SFU and publish video track."""
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
                self.logger.info(f"Connection state: {self.pc.connectionState}")
                
            @self.pc.on("iceconnectionstatechange") 
            async def on_iceconnectionstatechange():
                self.logger.info(f"ICE connection state: {self.pc.iceConnectionState}")

            # Add video track if available
            transceivers = []
            if self.video_source:
                self._video_track = VideoStreamTrack(self.video_source, logger=self.logger)
                transceiver = self.pc.addTransceiver(self._video_track, direction="sendonly")
                transceivers.append(transceiver)
                self.logger.info("Added video track to peer connection")

            # Create and set local offer
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
                self.logger.info("SFU Connection Established")
                return True
            else:
                self.logger.error("No session description in SFU response")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to connect to SFU: {e}")
            return False

    async def subscribe_to_datachannel(self, remote_session_id, channel_name):
        """Subscribe to a remote DataChannel (e.g., cmd_vel from operator).
        
        This triggers SDP renegotiation to establish the DataChannel.
        
        Args:
            remote_session_id: The operator's SFU session ID
            channel_name: Name of the DataChannel to subscribe to
        """
        if not self.pc:
            self.logger.error("No peer connection available")
            return False
            
        try:
            self.logger.info(f"Subscribing to DataChannel '{channel_name}' from session {remote_session_id}")
            
            # Use /datachannels/new to subscribe to remote datachannel
            response = await self.calls_client.create_datachannel(
                session_id=self.calls_client.session_id,
                channel_name=channel_name,
                location="remote",
                remote_session_id=remote_session_id
            )
            
            self.logger.info(f"DataChannel subscription response: {response}")
            
            # If we got a datachannel ID, create a negotiated datachannel locally
            if response and 'dataChannels' in response and len(response['dataChannels']) > 0:
                dc_info = response['dataChannels'][0]
                dc_id = dc_info.get('id')
                
                if dc_id is not None:
                    # Create a negotiated datachannel with the same ID
                    channel = self.pc.createDataChannel(
                        channel_name,
                        negotiated=True,
                        id=dc_id
                    )
                    self.data_channels[channel_name] = channel
                    self._setup_datachannel(channel)
                    self.logger.info(f"Created negotiated DataChannel '{channel_name}' with id={dc_id}")
                    return True
            
            self.logger.warning(f"No datachannel ID in response: {response}")
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to subscribe to DataChannel: {e}")
            return False

    def _setup_datachannel(self, channel):
        """Set up event handlers for a DataChannel."""
        channel_label = channel.label
        
        @channel.on("open")
        def on_open():
            self.logger.info(f"DataChannel '{channel_label}' opened")
        
        @channel.on("close")
        def on_close():
            self.logger.info(f"DataChannel '{channel_label}' closed")
            if channel_label in self.data_channels:
                del self.data_channels[channel_label]
        
        @channel.on("message")
        def on_message(message):
            try:
                if self.on_command:
                    # Parse command
                    # Expected format: { "linear": { "x": ... }, "angular": { "z": ... } }
                    if isinstance(message, bytes):
                        message = message.decode('utf-8')
                    data = json.loads(message)
                    linear = data.get("linear", {})
                    angular = data.get("angular", {})
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

    async def close(self):
        """Close the WebRTC connection."""
        if self.pc:
            await self.pc.close()
            self.pc = None
        if self._video_track:
            self._video_track.stop()
            self._video_track = None
        self.data_channels.clear()
