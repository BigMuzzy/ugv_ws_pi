import asyncio
import logging
import json
from .cloudflare_calls import CloudflareCallsClient

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration
    AIORTC_AVAILABLE = True
except ImportError:
    AIORTC_AVAILABLE = False

class SFUManager:
    def __init__(self, calls_client: CloudflareCallsClient, video_source=None, on_command=None, logger=None):
        self.calls_client = calls_client
        self.video_source = video_source
        self.on_command = on_command
        self.logger = logger or logging.getLogger(__name__)
        self.pc = None
        self.data_channel = None

    async def connect(self):
        if not AIORTC_AVAILABLE:
            self.logger.error("aiortc not available")
            return

        self.pc = RTCPeerConnection()

        # Add video track
        if self.video_source:
            self.pc.addTrack(self.video_source.create_track())

        # Create DataChannel for commands (we are the sink for commands from operator)
        # Actually, for Cloudflare Calls, if we want to receive data, we usually wait for the other side?
        # Or we create a channel and the SFU bridges it.
        # Let's create a local channel to be ready.
        # self.data_channel = self.pc.createDataChannel("cmd_vel")
        # self._setup_datachannel(self.data_channel)
        
        # Handle incoming data channels
        @self.pc.on("datachannel")
        def on_datachannel(channel):
            self.logger.info(f"Received DataChannel: {channel.label}")
            self._setup_datachannel(channel)

        # Create Offer
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        # Send to SFU
        # We need to send the offer to the SFU to create tracks.
        # The API for creating tracks with SDP:
        # POST /sessions/{sessionId}/tracks/new
        # Body: { "sessionDescription": { "sdp": offer.sdp, "type": "offer" }, "tracks": [...] }
        
        # Since we don't have the exact API, we'll assume a simplified flow where we send the offer 
        # and get an answer.
        
        # Note: This is a simplification. Real Calls API might require per-track negotiation or bundle.
        # We'll assume we are adding the video track.
        
        response = await self.calls_client.create_track(
            session_id=self.calls_client.session_id,
            track_name="video_main",
            sdp=offer.sdp
        )
        
        if response and 'sessionDescription' in response:
            answer_sdp = response['sessionDescription']['sdp']
            answer = RTCSessionDescription(sdp=answer_sdp, type='answer')
            await self.pc.setRemoteDescription(answer)
            self.logger.info("SFU Connection Established")

    def _setup_datachannel(self, channel):
        @channel.on("message")
        def on_message(message):
            try:
                if self.on_command:
                    # Parse command
                    # Assuming JSON: { "linear": { "x": ... }, "angular": { "z": ... } }
                    data = json.loads(message)
                    linear = data.get("linear", {})
                    angular = data.get("angular", {})
                    self.on_command(
                        linear.get("x", 0.0), 0.0, 0.0,
                        0.0, 0.0, angular.get("z", 0.0)
                    )
            except Exception as e:
                self.logger.error(f"Error processing command: {e}")

    async def close(self):
        if self.pc:
            await self.pc.close()
