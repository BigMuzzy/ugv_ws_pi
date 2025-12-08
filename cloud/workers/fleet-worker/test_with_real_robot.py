#!/usr/bin/env python3
"""
Test Fleet DO Extension with a REAL robot.

Prerequisites:
- A real robot must be connected to the Fleet Worker
- Run this script to test operator connection and message routing

Usage:
    python test_with_real_robot.py [--url URL] [--robot-id ROBOT_ID]
    
    If --robot-id is not specified, will list available robots and prompt.
"""

import asyncio
import json
import argparse
import sys
from datetime import datetime

try:
    import websockets
    import aiohttp
except ImportError:
    print("ERROR: Required libraries not installed.")
    print("Run: pip install websockets aiohttp")
    sys.exit(1)


# Default Fleet Worker URL
DEFAULT_WORKER_URL = "wss://fleet-worker.mssemyonov.workers.dev"


def log(role: str, message: str):
    """Print a timestamped log message."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] [{role}] {message}")


async def get_robots(base_url: str) -> list:
    """Fetch list of connected robots from API."""
    http_url = base_url.replace("wss://", "https://").replace("ws://", "http://")
    
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{http_url}/robots") as response:
            return await response.json()


async def test_operator_connection(base_url: str, robot_id: str):
    """
    Test operator WebSocket connection and message routing with a real robot.
    """
    url = f"{base_url}/ws/operator?robotId={robot_id}"
    log("OPERATOR", f"Connecting to {url}")
    
    try:
        ws = await websockets.connect(url)
        log("OPERATOR", "✓ Connected")
    except Exception as e:
        log("OPERATOR", f"✗ Connection failed: {e}")
        return False
    
    try:
        # Wait for connection confirmation
        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
        data = json.loads(msg)
        log("OPERATOR", f"✓ Received connection message:")
        print(json.dumps(data, indent=2))
        
        if data.get("type") == "connected":
            log("OPERATOR", f"✓ Session ID: {data.get('operatorSessionId')}")
            log("OPERATOR", f"✓ Robot connected: {data.get('robotConnected')}")
            
            if not data.get("robotConnected"):
                log("OPERATOR", "⚠ Robot not currently connected to Fleet DO")
                await ws.close()
                return False
        
        # Test: Send a rosbridge subscribe message
        log("TEST", "\n=== Sending rosbridge subscribe message ===")
        
        # Try /rosout which should always exist
        rosbridge_msg = {
            "op": "subscribe",
            "topic": "/rosout",
            "type": "rcl_interfaces/msg/Log",
            "id": "test-sub-1"
        }
        await ws.send(json.dumps(rosbridge_msg))
        log("OPERATOR", f"✓ Sent: {json.dumps(rosbridge_msg)}")
        
        # Wait for any response from robot (may get rosbridge data or nothing)
        log("TEST", "\n=== Waiting for robot responses (10 seconds) ===")
        log("TEST", "If robot has rosbridge_proxy running, you should see /odom data...")
        
        received_count = 0
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
                data = json.loads(msg)
                received_count += 1
                
                if data.get("type") == "robot_disconnected":
                    log("OPERATOR", f"⚠ Robot disconnected!")
                    break
                else:
                    # Rosbridge message from robot
                    topic = data.get("topic", "unknown")
                    op = data.get("op", "unknown")
                    log("OPERATOR", f"✓ Received [{op}] on {topic}")
                    if received_count <= 3:
                        print(json.dumps(data, indent=2)[:500])  # Truncate large messages
                    
                if received_count >= 10:
                    log("TEST", "Received 10 messages, stopping...")
                    break
                    
        except asyncio.TimeoutError:
            if received_count == 0:
                log("TEST", "⚠ No messages received from robot (timeout)")
                log("TEST", "   This is expected if rosbridge_proxy is not running on robot")
            else:
                log("TEST", f"✓ Received {received_count} message(s) before timeout")
        
        # Test: Send unsubscribe
        log("TEST", "\n=== Sending rosbridge unsubscribe ===")
        unsub_msg = {
            "op": "unsubscribe",
            "topic": "/rosout",
            "id": "test-sub-1"
        }
        await ws.send(json.dumps(unsub_msg))
        log("OPERATOR", f"✓ Sent: {json.dumps(unsub_msg)}")
        
        await ws.close()
        log("OPERATOR", "✓ Connection closed")
        
        return True
        
    except Exception as e:
        log("ERROR", f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        await ws.close()
        return False


async def interactive_test(base_url: str, robot_id: str):
    """
    Interactive test mode - keeps connection open for manual testing.
    """
    url = f"{base_url}/ws/operator?robotId={robot_id}"
    log("OPERATOR", f"Connecting to {url}")
    
    ws = await websockets.connect(url)
    log("OPERATOR", "✓ Connected")
    
    # Wait for connection confirmation
    msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
    data = json.loads(msg)
    print(json.dumps(data, indent=2))
    
    print("\n" + "=" * 60)
    print("Interactive Mode - Type rosbridge JSON commands")
    print("Examples:")
    print('  {"op":"subscribe","topic":"/odom","type":"nav_msgs/msg/Odometry"}')
    print('  {"op":"subscribe","topic":"/scan","type":"sensor_msgs/msg/LaserScan"}')
    print('  {"op":"call_service","service":"/get_state","type":"std_srvs/srv/Empty"}')
    print("Type 'quit' to exit")
    print("=" * 60 + "\n")
    
    async def receive_messages():
        try:
            while True:
                msg = await ws.recv()
                data = json.loads(msg)
                if data.get("type") == "robot_disconnected":
                    print(f"\n⚠ Robot disconnected!")
                else:
                    topic = data.get("topic", "")
                    op = data.get("op", "")
                    print(f"\n← [{op}] {topic}")
                    # Pretty print but truncate
                    formatted = json.dumps(data, indent=2)
                    if len(formatted) > 500:
                        print(formatted[:500] + "...")
                    else:
                        print(formatted)
        except websockets.exceptions.ConnectionClosed:
            print("\nConnection closed")
        except Exception as e:
            print(f"\nReceive error: {e}")
    
    # Start receiver task
    receiver = asyncio.create_task(receive_messages())
    
    # Read user input
    loop = asyncio.get_event_loop()
    try:
        while True:
            line = await loop.run_in_executor(None, input, "→ ")
            if line.lower() == 'quit':
                break
            try:
                # Validate JSON
                json.loads(line)
                await ws.send(line)
                print(f"✓ Sent")
            except json.JSONDecodeError:
                print("✗ Invalid JSON")
    except (EOFError, KeyboardInterrupt):
        pass
    
    receiver.cancel()
    await ws.close()
    print("\nDisconnected")


async def main(args):
    """Main entry point."""
    print("\n" + "=" * 60)
    print("Fleet DO Extension - Real Robot Test")
    print(f"Worker URL: {args.url}")
    print("=" * 60 + "\n")
    
    # Get list of connected robots
    log("API", "Fetching connected robots...")
    try:
        robots = await get_robots(args.url)
    except Exception as e:
        log("ERROR", f"Failed to fetch robots: {e}")
        return False
    
    if not robots:
        log("API", "⚠ No robots currently connected")
        log("API", "Please start the robot bridge and try again")
        print("\nTo connect a robot, on the robot run:")
        print("  ros2 launch webrtc_ros2_bridge bridge.launch.py")
        return False
    
    log("API", f"✓ Found {len(robots)} robot(s):")
    for i, robot in enumerate(robots):
        print(f"  [{i+1}] {robot.get('id')} - {robot.get('status')} (SFU: {robot.get('sfuSessionId', 'N/A')[:20]}...)")
    
    # Select robot
    if args.robot_id:
        robot_id = args.robot_id
        if not any(r.get('id') == robot_id for r in robots):
            log("ERROR", f"Robot '{robot_id}' not found in connected robots")
            return False
    else:
        if len(robots) == 1:
            robot_id = robots[0].get('id')
            log("TEST", f"Auto-selecting only robot: {robot_id}")
        else:
            try:
                choice = int(input("\nSelect robot number: ")) - 1
                robot_id = robots[choice].get('id')
            except (ValueError, IndexError):
                log("ERROR", "Invalid selection")
                return False
    
    print()
    
    if args.interactive:
        await interactive_test(args.url, robot_id)
        return True
    else:
        return await test_operator_connection(args.url, robot_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Fleet DO with real robot")
    parser.add_argument(
        "--url",
        default=DEFAULT_WORKER_URL,
        help=f"Fleet Worker URL (default: {DEFAULT_WORKER_URL})"
    )
    parser.add_argument(
        "--robot-id",
        help="Robot ID to connect to (if not specified, will list and prompt)"
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Interactive mode - keep connection open for manual commands"
    )
    args = parser.parse_args()
    
    try:
        success = asyncio.run(main(args))
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(0)
