"""ROSBridge Proxy - Bridges Fleet DO WebSocket to local rosbridge_server.

This module provides bidirectional proxying of rosbridge JSON messages between
the Cloudflare Fleet DO and a local rosbridge_server instance.

Architecture:
    Operator (roslibjs) <-> Fleet DO <-> ROSBridge Proxy <-> rosbridge_server <-> ROS2

The proxy:
1. Receives rosbridge messages from Fleet DO (type: 'rosbridge')
2. Forwards them to local rosbridge_server
3. Receives responses from rosbridge_server
4. Wraps and sends them back to Fleet DO
"""

import asyncio
import json
import logging
from typing import Optional, Callable, Any

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
except ImportError:
    websockets = None
    ConnectionClosed = Exception


class ROSBridgeProxy:
    """Proxies rosbridge messages between Fleet DO and local rosbridge_server.
    
    This class maintains two WebSocket connections:
    1. Fleet DO connection (shared with SignalingClient or separate)
    2. Local rosbridge_server connection (ws://localhost:9090)
    
    Message Flow:
        Fleet DO -> [type: rosbridge, payload: {...}] -> Proxy -> rosbridge_server
        rosbridge_server -> {...} -> Proxy -> [type: rosbridge, payload: {...}] -> Fleet DO
    """
    
    def __init__(
        self,
        rosbridge_url: str = "ws://localhost:9090",
        send_to_fleet: Optional[Callable[[dict], Any]] = None,
        logger: Optional[logging.Logger] = None
    ):
        """Initialize the ROSBridge Proxy.
        
        Args:
            rosbridge_url: WebSocket URL for local rosbridge_server
            send_to_fleet: Async callback to send messages to Fleet DO
            logger: Logger instance
        """
        self.rosbridge_url = rosbridge_url
        self.send_to_fleet = send_to_fleet
        self.logger = logger or logging.getLogger(__name__)
        
        self._rosbridge_ws: Optional[Any] = None
        self._running = False
        self._reconnect_delay = 5
        self._connection_task: Optional[asyncio.Task] = None
        
    @property
    def is_connected(self) -> bool:
        """Check if connected to rosbridge_server."""
        return self._rosbridge_ws is not None and self._rosbridge_ws.open
    
    async def start(self):
        """Start the proxy - connects to rosbridge_server."""
        if websockets is None:
            self.logger.error("websockets library not available, proxy disabled")
            return
            
        self._running = True
        self._connection_task = asyncio.create_task(self._connection_loop())
        self.logger.info(f"ROSBridge Proxy starting, will connect to {self.rosbridge_url}")
        
    async def stop(self):
        """Stop the proxy and close connections."""
        self._running = False
        
        if self._rosbridge_ws:
            try:
                await self._rosbridge_ws.close()
            except Exception as e:
                self.logger.debug(f"Error closing rosbridge connection: {e}")
            self._rosbridge_ws = None
            
        if self._connection_task:
            self._connection_task.cancel()
            try:
                await self._connection_task
            except asyncio.CancelledError:
                pass
            self._connection_task = None
            
        self.logger.info("ROSBridge Proxy stopped")
        
    async def _connection_loop(self):
        """Main connection loop - maintains connection to rosbridge_server."""
        while self._running:
            try:
                self.logger.info(f"Connecting to rosbridge_server: {self.rosbridge_url}")
                
                async with websockets.connect(
                    self.rosbridge_url,
                    ping_interval=20,
                    ping_timeout=10
                ) as ws:
                    self._rosbridge_ws = ws
                    self.logger.info("Connected to rosbridge_server")
                    
                    # Listen for messages from rosbridge_server
                    async for message in ws:
                        await self._handle_rosbridge_message(message)
                        
            except ConnectionClosed as e:
                self.logger.warning(f"rosbridge_server connection closed: {e}")
            except ConnectionRefusedError:
                self.logger.warning(
                    f"rosbridge_server not available at {self.rosbridge_url}. "
                    "Make sure rosbridge_server is running."
                )
            except Exception as e:
                self.logger.error(f"rosbridge_server connection error: {e}")
            finally:
                self._rosbridge_ws = None
                
            if self._running:
                self.logger.info(f"Reconnecting in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                
    async def _handle_rosbridge_message(self, message: str):
        """Handle a message received from rosbridge_server.
        
        Wraps the message and forwards it to Fleet DO.
        """
        try:
            # Parse to validate JSON and for logging
            data = json.loads(message)
            
            # Forward to Fleet DO wrapped in rosbridge type
            if self.send_to_fleet:
                wrapped = {
                    "type": "rosbridge",
                    "payload": data
                }
                await self.send_to_fleet(wrapped)
                
                # Log topic subscriptions (but not every message to avoid spam)
                op = data.get("op", "")
                if op in ("subscribe", "unsubscribe", "advertise", "unadvertise",
                          "call_service", "service_response"):
                    self.logger.debug(f"Forwarded to Fleet DO: {op} - {data.get('topic', data.get('service', ''))}")
                    
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON from rosbridge_server: {e}")
        except Exception as e:
            self.logger.error(f"Error forwarding rosbridge message: {e}")
            
    async def handle_fleet_message(self, data: dict):
        """Handle a rosbridge message received from Fleet DO.
        
        Extracts the payload and forwards to rosbridge_server.
        
        Args:
            data: Message dict with type='rosbridge' and payload containing
                  the actual rosbridge JSON message
        """
        if data.get("type") != "rosbridge":
            return
            
        payload = data.get("payload")
        if not payload:
            self.logger.warning("Received rosbridge message with empty payload")
            return
            
        if not self.is_connected:
            self.logger.warning("Cannot forward to rosbridge_server - not connected")
            return
            
        try:
            message = json.dumps(payload)
            await self._rosbridge_ws.send(message)
            
            # Log for debugging
            op = payload.get("op", "")
            topic_or_service = payload.get("topic", payload.get("service", ""))
            self.logger.debug(f"Forwarded to rosbridge_server: {op} {topic_or_service}")
            
        except Exception as e:
            self.logger.error(f"Error forwarding to rosbridge_server: {e}")


class IntegratedSignalingClient:
    """Extended SignalingClient with integrated ROSBridge proxy support.
    
    This class combines the existing SignalingClient functionality with
    ROSBridge proxy capabilities, handling both:
    - SFU signaling (subscribe_cmd for DataChannels)
    - ROSBridge message proxying
    
    The same WebSocket connection to Fleet DO is used for both purposes.
    """
    
    def __init__(
        self,
        worker_url: str,
        robot_id: str,
        calls_client: Any,  # CloudflareCallsClient
        rosbridge_url: str = "ws://localhost:9090",
        on_subscribe_cmd: Optional[Callable] = None,
        get_video_track_name: Optional[Callable] = None,
        enable_rosbridge_proxy: bool = True,
        logger: Optional[logging.Logger] = None
    ):
        """Initialize the integrated signaling client.
        
        Args:
            worker_url: Fleet Worker WebSocket URL
            robot_id: Unique robot identifier
            calls_client: CloudflareCallsClient instance
            rosbridge_url: Local rosbridge_server URL
            on_subscribe_cmd: Callback for DataChannel subscription commands
            get_video_track_name: Callback to get current video track name
            enable_rosbridge_proxy: Whether to enable rosbridge proxying
            logger: Logger instance
        """
        self.worker_url = worker_url
        self.robot_id = robot_id
        self.calls_client = calls_client
        self.on_subscribe_cmd = on_subscribe_cmd
        self.get_video_track_name = get_video_track_name
        self.logger = logger or logging.getLogger(__name__)
        
        self.ws = None
        self.running = False
        self._reconnect_delay = 5
        
        # ROSBridge proxy
        self._enable_rosbridge_proxy = enable_rosbridge_proxy
        self._rosbridge_proxy: Optional[ROSBridgeProxy] = None
        
        if enable_rosbridge_proxy:
            self._rosbridge_proxy = ROSBridgeProxy(
                rosbridge_url=rosbridge_url,
                send_to_fleet=self._send_to_fleet,
                logger=self.logger
            )
            
    async def _send_to_fleet(self, data: dict):
        """Send a message to Fleet DO."""
        if self.ws:
            try:
                await self.ws.send(json.dumps(data))
            except Exception as e:
                self.logger.error(f"Error sending to Fleet DO: {e}")
                
    async def start(self):
        """Start the signaling client and rosbridge proxy."""
        self.running = True
        
        # Start rosbridge proxy if enabled
        if self._rosbridge_proxy:
            await self._rosbridge_proxy.start()
        
        # Main Fleet DO connection loop
        while self.running:
            try:
                self.logger.info(f"Connecting to Fleet Worker: {self.worker_url}")
                
                async with websockets.connect(self.worker_url) as ws:
                    self.ws = ws
                    self.logger.info("Connected to Fleet Worker")
                    
                    # Send initial status
                    await self.send_status()
                    
                    # Start heartbeat task
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                    
                    try:
                        # Listen for messages
                        async for message in ws:
                            await self._handle_message(message)
                    finally:
                        heartbeat_task.cancel()
                        try:
                            await heartbeat_task
                        except asyncio.CancelledError:
                            pass
                            
            except ConnectionClosed as e:
                self.logger.warning(f"Fleet Worker connection closed: {e}")
            except Exception as e:
                self.logger.error(f"Fleet Worker connection error: {e}")
            finally:
                self.ws = None
                
            if self.running:
                self.logger.info(f"Reconnecting to Fleet Worker in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                
    async def stop(self):
        """Stop the signaling client and rosbridge proxy."""
        self.running = False
        
        if self._rosbridge_proxy:
            await self._rosbridge_proxy.stop()
            
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None
            
        self.logger.info("Signaling client stopped")
        
    async def send_status(self):
        """Send status update to Fleet Worker."""
        if self.ws and self.calls_client.session_id:
            msg = {
                "type": "status",
                "robotId": self.robot_id,
                "sfuSessionId": self.calls_client.session_id
            }
            
            if self.get_video_track_name:
                track_name = self.get_video_track_name()
                if track_name:
                    msg["videoTrackName"] = track_name
                    
            await self.ws.send(json.dumps(msg))
            self.logger.debug(f"Sent status: {msg}")
            
    async def _heartbeat_loop(self):
        """Send periodic status updates."""
        while self.running:
            await asyncio.sleep(30)
            try:
                await self.send_status()
            except Exception as e:
                self.logger.error(f"Heartbeat error: {e}")
                
    async def _handle_message(self, message: str):
        """Handle a message from Fleet Worker."""
        try:
            data = json.loads(message)
            
            # Handle DataChannel subscription command (existing functionality)
            if data.get("action") == "subscribe_cmd":
                session_id = data.get("sessionId")
                channel = data.get("channel")
                self.logger.info(f"Received subscribe_cmd: session={session_id}, channel={channel}")
                
                if self.on_subscribe_cmd:
                    await self.on_subscribe_cmd(session_id, channel)
                    
            # Handle rosbridge proxy messages (new functionality)
            elif data.get("type") == "rosbridge":
                if self._rosbridge_proxy:
                    await self._rosbridge_proxy.handle_fleet_message(data)
                else:
                    self.logger.warning("Received rosbridge message but proxy not enabled")
                    
            else:
                self.logger.debug(f"Unhandled message type: {data}")
                
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON from Fleet Worker: {e}")
        except Exception as e:
            self.logger.error(f"Error handling Fleet Worker message: {e}")
