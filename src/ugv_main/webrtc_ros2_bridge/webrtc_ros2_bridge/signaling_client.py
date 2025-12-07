import asyncio
import json
import logging
import websockets
from .cloudflare_calls import CloudflareCallsClient

class SignalingClient:
    """WebSocket client for connecting to the Fleet Worker signaling server.
    
    Responsibilities:
    - Connect to Fleet Worker via WebSocket
    - Register robot with SFU session info
    - Send periodic heartbeats
    - Handle commands from Worker (e.g., subscribe to operator's DataChannel)
    """
    
    def __init__(self, worker_url, robot_id, calls_client: CloudflareCallsClient, 
                 on_subscribe_cmd=None, get_video_track_name=None, logger=None):
        self.worker_url = worker_url
        self.robot_id = robot_id
        self.calls_client = calls_client
        self.on_subscribe_cmd = on_subscribe_cmd
        self.get_video_track_name = get_video_track_name  # Callback to get current video track name
        self.logger = logger or logging.getLogger(__name__)
        self.ws = None
        self.running = False
        self._reconnect_delay = 5  # seconds

    async def start(self):
        self.running = True
        while self.running:
            try:
                self.logger.info(f"Connecting to Signaling Worker: {self.worker_url}")
                async with websockets.connect(self.worker_url) as ws:
                    self.ws = ws
                    self.logger.info("Connected to Signaling Worker")
                    
                    # Send initial status
                    await self.send_status()

                    # Start heartbeat task
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                    
                    # Listen for messages
                    async for message in ws:
                        await self._handle_message(message)
                    
                    heartbeat_task.cancel()
            except Exception as e:
                self.logger.error(f"Signaling connection error: {e}")
                await asyncio.sleep(5) # Retry delay

    async def stop(self):
        self.running = False
        if self.ws:
            await self.ws.close()

    async def send_status(self):
        """Send status update to Fleet Worker with SFU session info."""
        if self.ws and self.calls_client.session_id:
            msg = {
                "type": "status",
                "robotId": self.robot_id,
                "sfuSessionId": self.calls_client.session_id
            }
            # Include video track name if available
            if self.get_video_track_name:
                track_name = self.get_video_track_name()
                if track_name:
                    msg["videoTrackName"] = track_name
            
            await self.ws.send(json.dumps(msg))
            self.logger.debug(f"Sent status: {msg}")

    async def _heartbeat_loop(self):
        while self.running:
            await asyncio.sleep(30)
            await self.send_status()

    async def _handle_message(self, message):
        try:
            data = json.loads(message)
            self.logger.info(f"Received message: {data}")
            
            if data.get("action") == "subscribe_cmd":
                # { "action": "subscribe_cmd", "sessionId": "SessionO", "channel": "cmd_vel" }
                session_id = data.get("sessionId")
                channel = data.get("channel")
                
                if self.on_subscribe_cmd:
                    await self.on_subscribe_cmd(session_id, channel)
                    
        except Exception as e:
            self.logger.error(f"Error handling message: {e}")
