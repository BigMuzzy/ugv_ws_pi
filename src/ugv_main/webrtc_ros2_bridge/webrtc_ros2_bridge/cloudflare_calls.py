import aiohttp
import logging
import json

class CloudflareCallsClient:
    def __init__(self, app_id, app_token, logger=None):
        self.app_id = app_id
        self.app_token = app_token
        self.base_url = f"https://rtc.live.cloudflare.com/v1/apps/{app_id}"
        self.logger = logger or logging.getLogger(__name__)
        self.session_id = None

    async def create_session(self):
        url = f"{self.base_url}/sessions/new"
        headers = {
            "Authorization": f"Bearer {self.app_token}",
            "Content-Type": "application/json"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as resp:
                if resp.status != 201 and resp.status != 200:
                    text = await resp.text()
                    self.logger.error(f"Failed to create session: {resp.status} {text}")
                    raise Exception(f"Failed to create session: {resp.status}")
                data = await resp.json()
                self.session_id = data['sessionId']
                self.logger.info(f"Created SFU session: {self.session_id}")
                return data

    async def create_track(self, session_id, track_name, track_type="local", sdp=None, mid=None):
        # For local tracks, we might send an SDP offer? 
        # Or maybe we just register the track and then negotiate?
        # The Calls API usually requires an SDP exchange to establish the connection.
        # But the sequence diagram simplifies it.
        # Let's assume standard Calls API:
        # POST /sessions/{sessionId}/tracks/new
        
        url = f"{self.base_url}/sessions/{session_id}/tracks/new"
        headers = {
            "Authorization": f"Bearer {self.app_token}",
            "Content-Type": "application/json"
        }
        body = {
            "sessionDescription": {
                "sdp": sdp,
                "type": "offer"
            }
        }
        # Note: The actual API might differ. I'm guessing based on "POST /tracks/new" in the diagram.
        # But usually you negotiate the connection (ICE/SDP) for the session, and then add tracks.
        # However, let's follow the diagram's endpoint names roughly but adapt to what makes sense for aiortc.
        
        # Actually, Cloudflare Calls (Orange) usually involves:
        # 1. Create Session
        # 2. Renegotiate (send Offer, get Answer) to establish transport.
        # 3. Add Tracks.
        
        # If the diagram says "POST /tracks/new (Add Local Video Track)", maybe it returns an Answer?
        pass

    async def create_datachannel(self, session_id, channel_name, type="local", remote_session_id=None):
        url = f"{self.base_url}/sessions/{session_id}/datachannels/new"
        headers = {
            "Authorization": f"Bearer {self.app_token}",
            "Content-Type": "application/json"
        }
        body = {
            "dataChannelName": channel_name,
            "type": type
        }
        if remote_session_id:
            body["sessionId"] = remote_session_id # The remote session to subscribe to?
            
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, headers=headers) as resp:
                 if resp.status != 201 and resp.status != 200:
                    text = await resp.text()
                    self.logger.error(f"Failed to create datachannel: {resp.status} {text}")
                    raise Exception(f"Failed to create datachannel: {resp.status}")
                 return await resp.json()

