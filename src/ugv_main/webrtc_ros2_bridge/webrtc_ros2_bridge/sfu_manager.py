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
        
        Based on: https://github.com/cloudflare/realtime-examples/blob/main/echo-datachannels/index.html
        
        DataChannels in Cloudflare SFU are unidirectional:
        - Operator creates a "local" datachannel and publishes to it
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
            
            # Step 1: Create a local datachannel to trigger SCTP transport in the offer
            # Use a high negotiated ID that won't conflict with SFU-assigned IDs
            dummy_dc = self.pc.createDataChannel("sctp-transport", negotiated=True, id=1000)
            self.logger.info("Created dummy datachannel to establish SCTP transport")
            
            # Step 2: Create offer with the datachannel
            offer = await self.pc.createOffer()
            await self.pc.setLocalDescription(offer)
            self.logger.info("Created offer for datachannel subscription")
            
            # Step 3: Use /datachannels/establish to set up SCTP transport with SFU
            establish_response = await self.calls_client.establish_datachannel(
                session_id=self.calls_client.session_id,
                channel_name="server-events",  # Dummy channel name for transport setup
                location="remote",
                remote_session_id=remote_session_id,
                sdp=offer.sdp
            )
            
            self.logger.info(f"DataChannel establish response: {establish_response}")
            
            if establish_response.get('errorCode'):
                self.logger.error(f"DataChannel establish error: {establish_response.get('errorDescription')}")
                return False
            
            # Step 4: Handle renegotiation
            if establish_response.get('requiresImmediateRenegotiation') and establish_response.get('sessionDescription'):
                remote_sdp = establish_response['sessionDescription']
                await self.pc.setRemoteDescription(
                    RTCSessionDescription(sdp=remote_sdp['sdp'], type=remote_sdp['type'])
                )
                self.logger.info(f"Set remote description (type={remote_sdp['type']})")
                
                if remote_sdp['type'] == 'offer':
                    answer = await self.pc.createAnswer()
                    await self.pc.setLocalDescription(answer)
                    await self.calls_client.renegotiate(
                        session_id=self.calls_client.session_id,
                        sdp=answer.sdp,
                        sdp_type='answer'
                    )
                    self.logger.info("Renegotiation complete")
            elif establish_response.get('sessionDescription'):
                remote_sdp = establish_response['sessionDescription']
                await self.pc.setRemoteDescription(
                    RTCSessionDescription(sdp=remote_sdp['sdp'], type=remote_sdp['type'])
                )
                self.logger.info("Set remote description (no renegotiation needed)")
            
            # Step 5: Now subscribe to the actual datachannel using /datachannels/new
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
            self.logger.info(f"DataChannel '{channel_label}' closed")
            if channel_label in self.data_channels:
                del self.data_channels[channel_label]
        
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

    async def close(self):
        """Close the WebRTC connection."""
        if self.pc:
            await self.pc.close()
            self.pc = None
        if self._video_track:
            self._video_track.stop()
            self._video_track = None
        self.data_channels.clear()
