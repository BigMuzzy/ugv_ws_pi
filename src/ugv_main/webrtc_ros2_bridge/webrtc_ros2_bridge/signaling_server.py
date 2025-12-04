"""WebRTC signaling server with WebSocket support."""
import asyncio
import json
import os
import signal
import sys

try:
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

# Import WebRTC manager and video source
from .webrtc_manager import WebRTCManager, AIORTC_AVAILABLE
from .video_source import VideoSource, VideoStreamTrack
from .cloudflare_turn import CloudflareTURNProvider


class SignalingServer:
    """WebRTC signaling server handling SDP/ICE exchange."""

    def __init__(
        self,
        host="0.0.0.0",
        port=8080,
        static_dir=None,
        on_command=None,
        on_emergency_stop=None,
        video_config=None,
        webrtc_config=None,
        logger=None
    ):
        """
        Initialize signaling server.

        Args:
            host: Server host address
            port: Server port
            static_dir: Directory for static files
            on_command: Callback for velocity commands
            on_emergency_stop: Callback for emergency stop
            video_config: Video configuration dict
            webrtc_config: WebRTC configuration dict
            logger: Logger instance
        """
        if not AIOHTTP_AVAILABLE:
            raise RuntimeError("aiohttp not available. Install with: pip install aiohttp")

        self._host = host
        self._port = port
        self._static_dir = static_dir
        self._logger = logger

        # Video configuration
        video_config = video_config or {}
        self._video_source = VideoSource(
            device=video_config.get("device", "/dev/video0"),
            width=video_config.get("width", 640),
            height=video_config.get("height", 480),
            fps=video_config.get("fps", 30),
            logger=logger
        )

        # WebRTC configuration
        webrtc_config = webrtc_config or {}
        self._webrtc_manager = WebRTCManager(
            stun_servers=webrtc_config.get("stun_servers"),
            turn_servers=webrtc_config.get("turn_servers"),
            on_command=on_command,
            on_emergency_stop=on_emergency_stop,
            on_ice_candidate=self._on_ice_candidate,
            logger=logger
        )

        self._app = None
        self._runner = None
        self._site = None
        self._websockets = {}
        
        # Initialize Cloudflare TURN provider
        self._turn_provider = CloudflareTURNProvider(logger=logger)

    async def start(self):
        """Start the signaling server."""
        # Start video source
        if not self._video_source.start():
            if self._logger:
                self._logger.warning("Video source not available")

        # Create video track if available
        if AIORTC_AVAILABLE:
            video_track = VideoStreamTrack(
                self._video_source,
                logger=self._logger
            )
            self._webrtc_manager.set_video_track(video_track)

        # Create aiohttp application
        self._app = web.Application()
        self._app.router.add_get("/ws", self._websocket_handler)
        self._app.router.add_post("/offer", self._offer_handler)
        self._app.router.add_get("/health", self._health_handler)
        self._app.router.add_get("/ice-servers", self._ice_servers_handler)

        # Serve static files if directory is specified
        if self._static_dir and os.path.isdir(self._static_dir):
            self._app.router.add_static("/", self._static_dir, follow_symlinks=True)
            self._app.router.add_get("/", self._index_handler)

        # Start server
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()

        if self._logger:
            self._logger.info(f"Signaling server started on http://{self._host}:{self._port}")

    async def stop(self):
        """Stop the signaling server."""
        # Close all WebSocket connections
        for ws in list(self._websockets.values()):
            await ws.close()

        # Close WebRTC connections
        await self._webrtc_manager.close_all()

        # Stop video source
        self._video_source.stop()

        # Stop server
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

        if self._logger:
            self._logger.info("Signaling server stopped")

    async def _index_handler(self, request):
        """Serve index.html."""
        if self._static_dir:
            index_path = os.path.join(self._static_dir, "index.html")
            if os.path.exists(index_path):
                return web.FileResponse(index_path)
        return web.Response(text="WebRTC Bridge", content_type="text/html")

    async def _health_handler(self, request):
        """Health check endpoint."""
        return web.json_response({
            "status": "ok",
            "peers": self._webrtc_manager.peer_count,
            "video": self._video_source.is_running
        })

    async def _ice_servers_handler(self, request):
        """
        ICE servers endpoint - provides STUN/TURN configuration.
        
        Returns dynamically generated credentials from Cloudflare.
        """
        try:
            ice_servers = self._turn_provider.get_ice_servers()
            return web.json_response({
                "iceServers": ice_servers
            })
        except Exception as e:
            if self._logger:
                self._logger.error(f"Error getting ICE servers: {e}")
            # Return fallback config on error
            return web.json_response({
                "iceServers": [
                    {'urls': 'stun:stun.l.google.com:19302'},
                    {'urls': 'stun:stun1.l.google.com:19302'}
                ]
            })

    def _on_ice_candidate(self, peer_id, candidate):
        """
        Handle ICE candidate from WebRTC manager and send to client.

        Args:
            peer_id: Peer identifier
            candidate: ICE candidate data
        """
        if peer_id in self._websockets:
            ws = self._websockets[peer_id]
            asyncio.create_task(ws.send_json({
                "type": "ice_candidate",
                "candidate": candidate
            }))

    async def _offer_handler(self, request):
        """Handle HTTP POST for SDP offer."""
        try:
            data = await request.json()
            peer_id = data.get("peer_id")
            sdp = data.get("sdp")

            if not sdp:
                return web.json_response({"error": "Missing SDP"}, status=400)

            answer_sdp = await self._webrtc_manager.handle_offer(peer_id, sdp)

            if answer_sdp:
                return web.json_response({
                    "type": "answer",
                    "sdp": answer_sdp,
                    "peer_id": peer_id
                })
            else:
                return web.json_response(
                    {"error": "Failed to create answer"},
                    status=500
                )

        except Exception as e:
            if self._logger:
                self._logger.error(f"Error handling offer: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def _websocket_handler(self, request):
        """Handle WebSocket connections for signaling."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        peer_id = str(id(ws))
        self._websockets[peer_id] = ws

        if self._logger:
            self._logger.info(f"WebSocket connected: {peer_id}")

        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    await self._handle_ws_message(peer_id, ws, msg.data)
                elif msg.type == web.WSMsgType.ERROR:
                    if self._logger:
                        self._logger.error(f"WebSocket error: {ws.exception()}")

        finally:
            # Clean up on disconnect
            self._websockets.pop(peer_id, None)
            await self._webrtc_manager.close_peer_connection(peer_id)
            if self._logger:
                self._logger.info(f"WebSocket disconnected: {peer_id}")

        return ws

    async def _handle_ws_message(self, peer_id, ws, message):
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")

            if msg_type == "offer":
                # Handle SDP offer
                sdp = data.get("sdp")
                answer_sdp = await self._webrtc_manager.handle_offer(peer_id, sdp)
                if answer_sdp:
                    await ws.send_json({
                        "type": "answer",
                        "sdp": answer_sdp
                    })

            elif msg_type == "ice_candidate":
                # Handle ICE candidate
                candidate = data.get("candidate")
                await self._webrtc_manager.handle_ice_candidate(peer_id, candidate)

            elif msg_type == "ping":
                # Respond with pong
                await ws.send_json({
                    "type": "pong",
                    "timestamp": data.get("timestamp", 0)
                })

        except json.JSONDecodeError:
            if self._logger:
                self._logger.warning(f"Invalid JSON from {peer_id}")
        except Exception as e:
            if self._logger:
                self._logger.error(f"Error handling WS message: {e}")

    def send_to_all_websockets(self, data):
        """Send message to all connected WebSocket clients."""
        for ws in self._websockets.values():
            asyncio.create_task(ws.send_json(data))


async def run_standalone_server(
    host="0.0.0.0",
    port=8080,
    static_dir=None,
    video_config=None,
    webrtc_config=None
):
    """
    Run signaling server standalone (without ROS2).

    Args:
        host: Server host
        port: Server port
        static_dir: Static files directory
        video_config: Video configuration
        webrtc_config: WebRTC configuration
    """
    server = SignalingServer(
        host=host,
        port=port,
        static_dir=static_dir,
        video_config=video_config,
        webrtc_config=webrtc_config
    )

    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(server.stop()))

    await server.start()

    # Keep running
    while True:
        await asyncio.sleep(1)


def main():
    """Main entry point for standalone signaling server."""
    import argparse

    parser = argparse.ArgumentParser(description="WebRTC Signaling Server")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--port", type=int, default=8080, help="Server port")
    parser.add_argument("--static", help="Static files directory")
    parser.add_argument("--video-device", default="/dev/video0", help="Video device")
    parser.add_argument("--video-width", type=int, default=640, help="Video width")
    parser.add_argument("--video-height", type=int, default=480, help="Video height")
    parser.add_argument("--video-fps", type=int, default=30, help="Video FPS")

    args = parser.parse_args()

    video_config = {
        "device": args.video_device,
        "width": args.video_width,
        "height": args.video_height,
        "fps": args.video_fps
    }

    try:
        asyncio.run(run_standalone_server(
            host=args.host,
            port=args.port,
            static_dir=args.static,
            video_config=video_config
        ))
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()
