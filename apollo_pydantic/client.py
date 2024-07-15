import base64
import hashlib
import hmac
import json
import time
from types import NoneType
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote, urlencode, urljoin

from httpx import AsyncClient
from pydantic import HttpUrl

from .logger import debug_logger


class ApolloClient:
    def __init__(self, config_server: Union[str, HttpUrl],
                 appid:str,
                 cluster:str='default',
                 secret_key:Optional[str]=None):
        self.config_server = config_server
        self.appid = appid
        self.cluster = cluster
        self.secret_key = secret_key
        self._client = None

    async def __aenter__(self):
        self._client = AsyncClient()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._client.aclose()
        self._client = None

    async def _http_get(self, path: str, timeout: float=5):
        url = urljoin(self.config_server, path)
        debug_logger.debug(f'GET {url}')
        if self._client:
            res = await self._client.get(url, follow_redirects=True, headers=self.headers(path), timeout=timeout)
        else:
            async with AsyncClient() as client:
                res = await client.get(url, follow_redirects=True, headers=self.headers(path), timeout=timeout)
        if res.status_code == 304:
            return None
        return res.json()

    def _parse_path(self, path, params):
        if params:
            path = f'{path}?{urlencode(params)}'
        return path

    @staticmethod
    def signature(timestamp: str, uri: str, secret: str):
        string_to_sign = timestamp + '\n' + uri
        hmac_code = hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha1).digest()
        return base64.b64encode(hmac_code).decode()

    def headers(self, path: str, params=None):
        if self.secret_key:
            path = self._parse_path(path, params)
            timestamp = str(int(time.time()*1000))
            sig = self.signature(timestamp, path, self.secret_key)
            return {
                'Authorization': f'Apollo {self.appid}:{sig}',
                'Timestamp': timestamp,
            }
        return {}

    async def cached_config(self, namespace:str, format: str='json'):
        if format == 'json':
            path = f'/configfiles/json/{self.appid}/{self.cluster}/{namespace}'
        else:
            path = f'/configfiles/{self.appid}/{self.cluster}/{namespace}'
        return await self._http_get(path, timeout=5)

    async def uncached_config(self,
                               namespace:str,
                               release_key: Optional[str]=None,
                               messages: Union[str, Dict[str, Any], NoneType]=None,
                               label: Optional[str]=None):
        params = {}
        if release_key:
            params['releaseKey'] = release_key
        if messages:
            if not isinstance(messages, str):
                messages = json.dumps(messages)
            params['messages'] = messages
        if label:
            params['label'] = label
        path = f'/configs/{self.appid}/{self.cluster}/{namespace}'
        path = self._parse_path(path, params)
        return await self._http_get(path)

    async def notification(self, notifications: List[Dict[str, Union[str, int]]]):
        """
            notifications: [{"namespaceName": "application", "notificationId": 100}, {"namespaceName": "FX.apollo", "notificationId": 200}]
        """
        notifications = json.dumps(notifications)
        notifications = quote(notifications)
        path = f'/notifications/v2?appId={self.appid}&cluster={self.cluster}&notifications={notifications}'
        return await self._http_get(path, timeout=100)