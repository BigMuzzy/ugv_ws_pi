"""Cloudflare TURN API integration."""
import json
import os
import time
import requests
from typing import Dict, List, Optional


class CloudflareTURNProvider:
    """Provider for Cloudflare TURN credentials."""

    def __init__(
        self,
        api_token: Optional[str] = None,
        turn_key_id: Optional[str] = None,
        ttl: int = 86400,
        logger=None
    ):
        """
        Initialize Cloudflare TURN provider.

        Args:
            api_token: Cloudflare API token (or use CLOUDFLARE_API_TOKEN env var)
            turn_key_id: TURN key ID (or use CLOUDFLARE_TURN_KEY_ID env var)
            ttl: Time to live for credentials in seconds (default 24 hours)
            logger: Logger instance
        """
        self._api_token = api_token or os.environ.get('CLOUDFLARE_API_TOKEN')
        self._turn_key_id = turn_key_id or os.environ.get('CLOUDFLARE_TURN_KEY_ID')
        self._ttl = ttl
        self._logger = logger
        
        # Cache for credentials
        self._cached_credentials = None
        self._cache_expiry = 0

    def get_ice_servers(self) -> List[Dict]:
        """
        Get ICE servers configuration from Cloudflare.

        Returns:
            List of ICE server configurations with credentials
        """
        # Check if we have valid cached credentials
        if self._cached_credentials and time.time() < self._cache_expiry:
            if self._logger:
                self._logger.info("Using cached Cloudflare TURN credentials")
            return self._cached_credentials

        # Fetch new credentials
        try:
            ice_servers = self._fetch_credentials()
            if ice_servers:
                # Cache credentials (expire 5 minutes before actual expiry)
                self._cached_credentials = ice_servers
                self._cache_expiry = time.time() + self._ttl - 300
                
                if self._logger:
                    self._logger.info("Fetched fresh Cloudflare TURN credentials")
                
                return ice_servers
        except Exception as e:
            if self._logger:
                self._logger.error(f"Failed to fetch Cloudflare credentials: {e}")
        
        # Return fallback configuration
        return self._get_fallback_config()

    def _fetch_credentials(self) -> Optional[List[Dict]]:
        """
        Fetch credentials from Cloudflare API.

        Returns:
            ICE servers configuration or None on failure
        """
        if not self._api_token or not self._turn_key_id:
            if self._logger:
                self._logger.warning(
                    "Cloudflare API token or TURN key ID not configured. "
                    "Set CLOUDFLARE_API_TOKEN and CLOUDFLARE_TURN_KEY_ID environment variables."
                )
            return None

        url = (
            f"https://rtc.live.cloudflare.com/v1/turn/keys/"
            f"{self._turn_key_id}/credentials/generate-ice-servers"
        )
        
        headers = {
            'Authorization': f'Bearer {self._api_token}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'ttl': self._ttl
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if self._logger:
                self._logger.info(f"Cloudflare API response: {json.dumps(data, indent=2)}")
            
            # Cloudflare returns { "iceServers": [...] }
            if 'iceServers' in data:
                return data['iceServers']
            else:
                if self._logger:
                    self._logger.error(f"Unexpected Cloudflare API response: {data}")
                return None
                
        except requests.exceptions.RequestException as e:
            if self._logger:
                self._logger.error(f"Cloudflare API request failed: {e}")
            return None
        except Exception as e:
            if self._logger:
                self._logger.error(f"Error parsing Cloudflare response: {e}")
            return None

    def _get_fallback_config(self) -> List[Dict]:
        """
        Get fallback ICE servers configuration.

        Returns:
            List with public STUN servers
        """
        if self._logger:
            self._logger.info("Using fallback STUN servers")
        
        return [
            {'urls': 'stun:stun.l.google.com:19302'},
            {'urls': 'stun:stun1.l.google.com:19302'}
        ]
