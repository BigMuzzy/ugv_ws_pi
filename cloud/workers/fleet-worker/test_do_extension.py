#!/usr/bin/env python3
"""
Test script for Fleet DO Extension - rosbridge proxy functionality.

This script tests:
1. Robot WebSocket connection and status registration
2. Operator WebSocket connection via /ws/operator?robotId=xxx
3. Bidirectional rosbridge message routing

Usage:
    python test_do_extension.py [--url URL]
    
    Default URL: wss://fleet-worker.maxpioneer.workers.dev
"""

import asyncio
import json
import argparse
import sys
from datetime import datetime

try:
    import websockets
except ImportError:
    print("ERROR: websockets library not installed. Run: pip install websockets")
    sys.exit(1)


# Default Fleet Worker URL
DEFAULT_WORKER_URL = "wss://fleet-worker.maxpioneer.workers.dev"


def log(role: str, message: str):
    """Print a timestamped log message."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] [{role}] {message}")


async def test_robot_connection(base_url: str, robot_id: str) -> websockets.WebSocketClientProtocol:
    """
    Test 1: Robot connects and sends status message.
    Returns the WebSocket for further testing.
    """
    log("ROBOT", f"Connecting to {base_url}/ws/robot")
    
    ws = await websockets.connect(f"{base_url}/ws/robot")
    log("ROBOT", "✓ Connected")
    
    # Send status message
    status_msg = {
        "type": "status",
        "robotId": robot_id,
        "sfuSessionId": "test-sfu-session-123",
        "videoTrackName": f"{robot_id}-video"
    }
    await ws.send(json.dumps(status_msg))
    log("ROBOT", f"✓ Sent status: {json.dumps(status_msg)}")
    
    return ws


async def test_operator_connection(base_url: str, robot_id: str) -> websockets.WebSocketClientProtocol:
    """
    Test 2: Operator connects to /ws/operator with robotId.
    Returns the WebSocket for further testing.
    """
    url = f"{base_url}/ws/operator?robotId={robot_id}"
    log("OPERATOR", f"Connecting to {url}")
    
    ws = await websockets.connect(url)
    log("OPERATOR", "✓ Connected")
    
    # Wait for connection confirmation
    try:
        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
        data = json.loads(msg)
        log("OPERATOR", f"✓ Received: {json.dumps(data, indent=2)}")
        
        if data.get("type") == "connected":
            log("OPERATOR", f"✓ Connection confirmed - operatorSessionId: {data.get('operatorSessionId')}")
            log("OPERATOR", f"  Robot connected: {data.get('robotConnected')}")
        else:
            log("OPERATOR", f"⚠ Unexpected message type: {data.get('type')}")
    except asyncio.TimeoutError:
        log("OPERATOR", "⚠ No connection confirmation received (timeout)")
    
    return ws


async def test_operator_to_robot_routing(robot_ws, operator_ws, robot_id: str):
    """
    Test 3: Operator sends rosbridge message, robot receives it.
    """
    log("TEST", "=== Testing Operator → Robot routing ===")
    
    # Operator sends a rosbridge subscribe message
    rosbridge_msg = {
        "op": "subscribe",
        "topic": "/odom",
        "type": "nav_msgs/Odometry"
    }
    await operator_ws.send(json.dumps(rosbridge_msg))
    log("OPERATOR", f"✓ Sent rosbridge message: {json.dumps(rosbridge_msg)}")
    
    # Robot should receive it wrapped
    try:
        msg = await asyncio.wait_for(robot_ws.recv(), timeout=5.0)
        data = json.loads(msg)
        log("ROBOT", f"✓ Received: {json.dumps(data, indent=2)}")
        
        if data.get("type") == "rosbridge":
            payload = data.get("payload", {})
            if payload.get("op") == "subscribe" and payload.get("topic") == "/odom":
                log("TEST", "✓ Operator → Robot routing PASSED")
                return True
            else:
                log("TEST", f"✗ Payload mismatch: {payload}")
        else:
            log("TEST", f"✗ Wrong message type: {data.get('type')}")
    except asyncio.TimeoutError:
        log("TEST", "✗ Robot did not receive message (timeout)")
    
    return False


async def test_robot_to_operator_routing(robot_ws, operator_ws, robot_id: str):
    """
    Test 4: Robot sends rosbridge message, operator receives it.
    """
    log("TEST", "=== Testing Robot → Operator routing ===")
    
    # Robot sends a wrapped rosbridge publish message
    rosbridge_msg = {
        "type": "rosbridge",
        "payload": {
            "op": "publish",
            "topic": "/odom",
            "msg": {
                "header": {"stamp": {"sec": 12345, "nanosec": 0}},
                "pose": {"pose": {"position": {"x": 1.0, "y": 2.0, "z": 0.0}}}
            }
        }
    }
    await robot_ws.send(json.dumps(rosbridge_msg))
    log("ROBOT", f"✓ Sent rosbridge message")
    
    # Operator should receive raw rosbridge JSON (not wrapped)
    try:
        msg = await asyncio.wait_for(operator_ws.recv(), timeout=5.0)
        data = json.loads(msg)
        log("OPERATOR", f"✓ Received: {json.dumps(data, indent=2)}")
        
        if data.get("op") == "publish" and data.get("topic") == "/odom":
            log("TEST", "✓ Robot → Operator routing PASSED")
            return True
        else:
            log("TEST", f"✗ Unexpected message: {data}")
    except asyncio.TimeoutError:
        log("TEST", "✗ Operator did not receive message (timeout)")
    
    return False


async def test_robot_disconnect_notification(robot_ws, operator_ws, robot_id: str):
    """
    Test 5: When robot disconnects, operator receives notification.
    """
    log("TEST", "=== Testing Robot Disconnect Notification ===")
    
    # Close robot connection
    await robot_ws.close()
    log("ROBOT", "✓ Disconnected")
    
    # Operator should receive disconnect notification
    try:
        msg = await asyncio.wait_for(operator_ws.recv(), timeout=5.0)
        data = json.loads(msg)
        log("OPERATOR", f"✓ Received: {json.dumps(data, indent=2)}")
        
        if data.get("type") == "robot_disconnected" and data.get("robotId") == robot_id:
            log("TEST", "✓ Disconnect notification PASSED")
            return True
        else:
            log("TEST", f"✗ Unexpected message: {data}")
    except asyncio.TimeoutError:
        log("TEST", "✗ Operator did not receive disconnect notification (timeout)")
    
    return False


async def test_get_robots_api(base_url: str, robot_id: str):
    """
    Test 6: GET /robots API returns registered robot.
    """
    log("TEST", "=== Testing GET /robots API ===")
    
    # Convert wss:// to https://
    http_url = base_url.replace("wss://", "https://").replace("ws://", "http://")
    
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{http_url}/robots") as response:
                data = await response.json()
                log("API", f"✓ GET /robots response: {json.dumps(data, indent=2)}")
                
                # Check if our robot is in the list
                robot_found = any(r.get("id") == robot_id for r in data)
                if robot_found:
                    log("TEST", "✓ GET /robots API PASSED - robot found")
                    return True
                else:
                    log("TEST", f"✗ Robot {robot_id} not found in response")
                    return False
    except ImportError:
        log("TEST", "⚠ aiohttp not installed, skipping HTTP API test")
        return None
    except Exception as e:
        log("TEST", f"✗ API request failed: {e}")
        return False


async def run_all_tests(base_url: str):
    """Run all tests in sequence."""
    robot_id = f"test-robot-{int(datetime.now().timestamp())}"
    
    print("\n" + "=" * 60)
    print("Fleet DO Extension - Test Suite")
    print(f"Worker URL: {base_url}")
    print(f"Robot ID: {robot_id}")
    print("=" * 60 + "\n")
    
    results = {}
    robot_ws = None
    operator_ws = None
    
    try:
        # Test 1: Robot connection
        log("TEST", "=== Test 1: Robot Connection ===")
        robot_ws = await test_robot_connection(base_url, robot_id)
        results["robot_connection"] = True
        
        # Delay for KV propagation (KV has eventual consistency)
        log("TEST", "Waiting for KV propagation (2s)...")
        await asyncio.sleep(2)
        
        # Test 2: GET /robots API
        api_result = await test_get_robots_api(base_url, robot_id)
        if api_result is not None:
            results["get_robots_api"] = api_result
        
        # Test 3: Operator connection
        log("TEST", "\n=== Test 2: Operator Connection ===")
        operator_ws = await test_operator_connection(base_url, robot_id)
        results["operator_connection"] = True
        
        # Test 4: Operator → Robot routing
        results["operator_to_robot"] = await test_operator_to_robot_routing(
            robot_ws, operator_ws, robot_id
        )
        
        # Test 5: Robot → Operator routing
        results["robot_to_operator"] = await test_robot_to_operator_routing(
            robot_ws, operator_ws, robot_id
        )
        
        # Test 6: Robot disconnect notification
        results["disconnect_notification"] = await test_robot_disconnect_notification(
            robot_ws, operator_ws, robot_id
        )
        robot_ws = None  # Already closed
        
    except Exception as e:
        log("ERROR", f"Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        if robot_ws:
            await robot_ws.close()
        if operator_ws:
            await operator_ws.close()
    
    # Print summary
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)
    
    all_passed = True
    for test_name, passed in results.items():
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"  {test_name}: {status}")
        if not passed:
            all_passed = False
    
    print("=" * 60)
    if all_passed:
        print("All tests PASSED! ✓")
    else:
        print("Some tests FAILED! ✗")
    print()
    
    return all_passed


def main():
    parser = argparse.ArgumentParser(description="Test Fleet DO Extension")
    parser.add_argument(
        "--url",
        default=DEFAULT_WORKER_URL,
        help=f"Fleet Worker URL (default: {DEFAULT_WORKER_URL})"
    )
    args = parser.parse_args()
    
    # Run tests
    success = asyncio.run(run_all_tests(args.url))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
