import aiohttp
import logging
import json

class CloudflareCallsClient:
    """Client for Cloudflare Realtime (Calls) SFU API.
    
    Based on: https://developers.cloudflare.com/realtime/sfu/https-api/
    API Spec: https://developers.cloudflare.com/realtime/static/calls-api-2024-05-21.yaml
    """
    
    def __init__(self, app_id, app_token, logger=None):
        self.app_id = app_id
        self.app_token = app_token
        self.base_url = f"https://rtc.live.cloudflare.com/v1/apps/{app_id}"
        self.logger = logger or logging.getLogger(__name__)
        self.session_id = None
        self._http_session = None

    @property
    def _headers(self):
        return {
            "Authorization": f"Bearer {self.app_token}",
            "Content-Type": "application/json"
        }

    async def _get_http_session(self):
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def close(self):
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

    async def create_session(self):
        """Create a new SFU session.
        
        POST /apps/{appId}/sessions/new
        """
        url = f"{self.base_url}/sessions/new"
        session = await self._get_http_session()
        async with session.post(url, headers=self._headers) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                self.logger.error(f"Failed to create session: {resp.status} {text}")
                raise Exception(f"Failed to create session: {resp.status}")
            data = await resp.json()
            self.session_id = data['sessionId']
            self.logger.info(f"Created SFU session: {self.session_id}")
            return data

    async def add_tracks(self, session_id, sdp, tracks, auto_discover=False):
        """Add tracks to an existing session.
        
        POST /apps/{appId}/sessions/{sessionId}/tracks/new
        
        Args:
            session_id: The session ID
            sdp: SDP offer string
            tracks: List of track definitions, e.g.:
                [{"location": "local", "mid": "0", "trackName": "video"}]
            auto_discover: If True, automatically discover tracks from SDP
            
        Returns:
            Response with sessionDescription (answer) and track info
        """
        url = f"{self.base_url}/sessions/{session_id}/tracks/new"
        
        body = {}
        if sdp:
            body["sessionDescription"] = {
                "sdp": sdp,
                "type": "offer"
            }
        if auto_discover:
            body["autoDiscover"] = True
        else:
            body["tracks"] = tracks
            
        self.logger.info(f"Adding tracks to session {session_id}")
        
        session = await self._get_http_session()
        async with session.post(url, json=body, headers=self._headers) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                self.logger.error(f"Failed to add tracks: {resp.status} {text}")
                raise Exception(f"Failed to add tracks: {resp.status}")
            data = await resp.json()
            
            if data.get('errorCode'):
                raise Exception(f"SFU error: {data.get('errorDescription')}")
                
            self.logger.info(f"Tracks added successfully")
            return data

    async def renegotiate(self, session_id, sdp, sdp_type="answer"):
        """Renegotiate a session with new SDP.
        
        PUT /apps/{appId}/sessions/{sessionId}/renegotiate
        
        Args:
            session_id: The session ID
            sdp: SDP string
            sdp_type: "offer" or "answer"
        """
        url = f"{self.base_url}/sessions/{session_id}/renegotiate"
        body = {
            "sessionDescription": {
                "sdp": sdp,
                "type": sdp_type
            }
        }
        
        self.logger.info(f"Renegotiating session {session_id}")
        
        session = await self._get_http_session()
        async with session.put(url, json=body, headers=self._headers) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                self.logger.error(f"Failed to renegotiate: {resp.status} {text}")
                raise Exception(f"Failed to renegotiate: {resp.status}")
            data = await resp.json()
            self.logger.info(f"Renegotiation successful")
            return data

    async def create_datachannel(self, session_id, channel_name, location="local", remote_session_id=None):
        """Create or subscribe to a DataChannel.
        
        POST /apps/{appId}/sessions/{sessionId}/datachannels/new
        
        Args:
            session_id: The local session ID
            channel_name: Name of the DataChannel
            location: "local" to create, "remote" to subscribe
            remote_session_id: Required when location="remote", the session to subscribe from
        """
        url = f"{self.base_url}/sessions/{session_id}/datachannels/new"
        
        datachannel_def = {
            "location": location,
            "dataChannelName": channel_name,
        }
        if location == "remote" and remote_session_id:
            datachannel_def["sessionId"] = remote_session_id
            
        body = {
            "dataChannels": [datachannel_def]
        }
        
        self.logger.info(f"Creating datachannel '{channel_name}' (location={location}) on session {session_id}")
        
        session = await self._get_http_session()
        async with session.post(url, json=body, headers=self._headers) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                self.logger.error(f"Failed to create datachannel: {resp.status} {text}")
                raise Exception(f"Failed to create datachannel: {resp.status}")
            data = await resp.json()
            self.logger.info(f"DataChannel created: {data}")
            return data

    async def establish_datachannel(self, session_id, channel_name, location="remote", 
                                    remote_session_id=None, sdp=None):
        """Establish a DataChannel with optional SDP for renegotiation.
        
        POST /apps/{appId}/sessions/{sessionId}/datachannels/establish
        
        This endpoint handles renegotiation automatically when needed.
        
        Args:
            session_id: The local session ID
            channel_name: Name of the DataChannel
            location: "local" or "remote"
            remote_session_id: Required for remote channels
            sdp: Optional SDP offer for renegotiation
            
        Returns:
            Response which may include requiresImmediateRenegotiation and sessionDescription
        """
        url = f"{self.base_url}/sessions/{session_id}/datachannels/establish"
        
        datachannel_def = {
            "location": location,
            "dataChannelName": channel_name,
        }
        if location == "remote" and remote_session_id:
            datachannel_def["sessionId"] = remote_session_id
            
        body = {
            "dataChannel": datachannel_def
        }
        if sdp:
            body["sessionDescription"] = {
                "type": "offer",
                "sdp": sdp
            }
        
        self.logger.info(f"Establishing datachannel '{channel_name}' on session {session_id}")
        
        session = await self._get_http_session()
        async with session.post(url, json=body, headers=self._headers) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                self.logger.error(f"Failed to establish datachannel: {resp.status} {text}")
                raise Exception(f"Failed to establish datachannel: {resp.status}")
            data = await resp.json()
            self.logger.info(f"DataChannel establish response: {data}")
            return data

    async def close_tracks(self, session_id, tracks):
        """Close tracks in a session.
        
        PUT /apps/{appId}/sessions/{sessionId}/tracks/close
        
        Args:
            session_id: The session ID
            tracks: List of track mids to close
        """
        url = f"{self.base_url}/sessions/{session_id}/tracks/close"
        body = {
            "tracks": [{"mid": mid} for mid in tracks]
        }
        
        session = await self._get_http_session()
        async with session.put(url, json=body, headers=self._headers) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                self.logger.error(f"Failed to close tracks: {resp.status} {text}")
                raise Exception(f"Failed to close tracks: {resp.status}")
            return await resp.json()

    async def get_session_info(self, session_id):
        """Get information about a session.
        
        GET /apps/{appId}/sessions/{sessionId}
        """
        url = f"{self.base_url}/sessions/{session_id}"
        
        session = await self._get_http_session()
        async with session.get(url, headers=self._headers) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                self.logger.error(f"Failed to get session info: {resp.status} {text}")
                raise Exception(f"Failed to get session info: {resp.status}")
            return await resp.json()

