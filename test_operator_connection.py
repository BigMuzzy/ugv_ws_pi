#!/usr/bin/env python3
"""
Simple test script to simulate an operator connecting to a robot via Cloudflare Calls SFU.
This creates a real SFU session and DataChannel to test the full signaling flow.

Usage:
    export CLOUDFLARE_APP_ID="your-app-id"
    export CLOUDFLARE_APP_TOKEN="your-app-token"
    python3 test_operator_connection.py
"""

import asyncio
import aiohttp
import json
import os
import sys

# Configuration
CLOUDFLARE_APP_ID = os.environ.get("CLOUDFLARE_APP_ID", "f4e541276741873484e4885e3506c43f")
CLOUDFLARE_APP_TOKEN = os.environ.get("CLOUDFLARE_APP_TOKEN", "")
FLEET_WORKER_URL = os.environ.get("FLEET_WORKER_URL", "https://fleet-worker.mssemyonov.workers.dev")
CALLS_API_BASE = f"https://rtc.live.cloudflare.com/v1/apps/{CLOUDFLARE_APP_ID}"


async def main():
    if not CLOUDFLARE_APP_TOKEN:
        print("ERROR: Set CLOUDFLARE_APP_TOKEN environment variable")
        sys.exit(1)
    
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_APP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        # 1. Fetch robots
        print("\n=== Step 1: Fetch robots ===")
        async with session.get(f"{FLEET_WORKER_URL}/robots") as resp:
            robots = await resp.json()
            print(f"Found {len(robots)} robot(s):")
            for r in robots:
                print(f"  - {r['id']}: session={r.get('sfuSessionId', 'N/A')[:16]}..., track={r.get('videoTrackName', 'N/A')}")
        
        if not robots:
            print("No robots online. Start the robot first.")
            return
        
        robot = robots[0]
        print(f"\nUsing robot: {robot['id']}")
        
        # 2. Create operator SFU session
        print("\n=== Step 2: Create operator SFU session ===")
        async with session.post(f"{CALLS_API_BASE}/sessions/new", headers=headers) as resp:
            data = await resp.json()
            operator_session_id = data['sessionId']
            print(f"Created operator session: {operator_session_id}")
        
        # 3. Register a local DataChannel (cmd_vel - we will send commands)
        print("\n=== Step 3: Register cmd_vel DataChannel ===")
        dc_body = {
            "dataChannels": [{
                "location": "local",
                "dataChannelName": "cmd_vel"
            }]
        }
        async with session.post(
            f"{CALLS_API_BASE}/sessions/{operator_session_id}/datachannels/new",
            headers=headers,
            json=dc_body
        ) as resp:
            dc_data = await resp.json()
            print(f"DataChannel response: {json.dumps(dc_data, indent=2)}")
            
            if 'dataChannels' in dc_data and len(dc_data['dataChannels']) > 0:
                dc_info = dc_data['dataChannels'][0]
                if 'id' in dc_info:
                    print(f"DataChannel ID: {dc_info['id']}")
                elif 'errorCode' in dc_info:
                    print(f"DataChannel error: {dc_info['errorDescription']}")
        
        # 4. Signal the robot to subscribe to our cmd_vel channel
        print("\n=== Step 4: Signal robot via Fleet Worker ===")
        connect_body = {
            "robotId": robot['id'],
            "operatorSessionId": operator_session_id
        }
        async with session.post(
            f"{FLEET_WORKER_URL}/connect",
            json=connect_body
        ) as resp:
            result = await resp.json()
            print(f"Connect response: {result}")
        
        if result.get('success'):
            print("\n✅ SUCCESS! Signal sent to robot.")
            print(f"   Robot should now subscribe to cmd_vel from session: {operator_session_id}")
            print("\n   Check the robot logs for:")
            print("   - 'Received message: subscribe_cmd'")
            print("   - 'Subscribing to DataChannel cmd_vel'")
            print("   - 'Created negotiated DataChannel cmd_vel'")
        else:
            print(f"\n❌ Failed to signal robot: {result}")
        
        # 5. Keep session alive for a bit to see robot response
        print("\n=== Waiting 10 seconds (check robot logs) ===")
        await asyncio.sleep(10)
        
        print("\nDone. Session will expire shortly.")


if __name__ == "__main__":
    asyncio.run(main())
