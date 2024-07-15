import asyncio
import json
import os
import re
from collections import defaultdict
from functools import lru_cache
from typing import Any, Dict, List, Optional, Set, Tuple, Type, Union

import httpx
from pydantic import (AliasChoices, AliasPath, HttpUrl, SecretStr,
                      ValidationError, model_validator)
from pydantic_settings import BaseSettings, SettingsConfigDict

from apollo_pydantic.logger import debug_logger, logger

from .client import ApolloClient


class ApolloSettingsConfigDict(SettingsConfigDict):
    config_server: HttpUrl
    appid: str
    cluster: str
    secret_key: Optional[SecretStr]

ClientKey = Tuple[Union[HttpUrl, str], str, str]

ARRAY_RE = re.compile(r'^(?P<name>[\w\-_\.]+)\[(?P<index>\d+)\]$')

def _add_alias_to_set(aliases: Set[str], alias: Union[str, AliasChoices, AliasPath]):
    if isinstance(alias, str):
        aliases.add(alias)
    elif isinstance(alias, AliasPath):
        aliases.add(alias.path[0])
    elif isinstance(alias, AliasChoices):
        for choice in alias.choices:
            if isinstance(choice, str):
                aliases.add(choice)
            elif isinstance(choice, AliasPath):
                aliases.add(choice.path[0])
    return aliases

class ApolloSettingsMetadata:
    def __init__(self, onerror_retry_interval: int = 10, onerror_resume: bool = True):
        self._clients: Dict[ClientKey, ApolloClient] = {}
        self._registered: Dict[ApolloClient, Dict[str, Type["ApolloSettings"]]] = defaultdict(dict)
        self._notifications: Dict[ApolloClient, List[Dict[str, Union[str, int]]]] = defaultdict(list)
        self._release_keys: Dict[ApolloClient, Dict[str, str]] = defaultdict(dict)
        self._started: bool = False
        self._running_fut = None
        self._started_fut = None
        self._onerror_retry_interval = onerror_retry_interval
        self._onerror_resume = onerror_resume

    def _get_key(self, cls: Type["ApolloSettings"]):
        namespace = cls.__namespace__
        model_config = cls.model_config
        key = (
            model_config.get('config_server'),
            model_config.get('appid'),
            model_config.get('cluster'),
            namespace
        )
        return key

    def register(self, cls: Type["ApolloSettings"]):
        key = self._get_key(cls)
        if not all(key):
            raise ValueError(f'{cls.__name__}:config_server, appid, cluster must all be set in model_config')
        key, namespace = key[:-1], key[-1]
        if key in self._registered and namespace in self._registered.get(key):
            msg = 'config_server=%s appid=%s cluster=%s namespace=%s already defined' % key
            raise ValueError(f'{cls.__name__}:{msg}')
        client = self._clients.get(key, ApolloClient(*key, secret_key=cls.model_config.get('secret_key')))
        if key not in self._clients:
            self._clients[key] = client
        self._registered[client][namespace] = cls
        self._notifications[client].append({'namespaceName': namespace, 'notificationId': -1})
        self._release_keys[client][namespace] = None

    def _get_client(self, cls: Type["ApolloSettings"]):
        key = self._get_key(cls)
        return self._clients.get(key[:-1])

    async def _notification_once(self, key: ClientKey, client: ApolloClient):
        notifications = self._notifications[client]
        async with client:
            res = await client.notification(notifications)
            if not res:
                return key, client
            for notification in res:
                for notif in self._notifications[client]:
                    if notif['namespaceName'] == notification['namespaceName']:
                        notif['notificationId'] = notification['notificationId']
            await self._update(client, res)
        return key, client

    async def _notification_one(self, key: ClientKey, client: ApolloClient, onerror_resume: bool = True):
        try:
            return await self._notification_once(key, client)
        except Exception as e:
            if not onerror_resume:
                raise e
            if isinstance(e, ValidationError):
                logger.error("Settings validation failed: %s", e)
            elif isinstance(e, httpx.HTTPError):
                logger.error("Settings fetch failed: %s", e)
            else:
                logger.exception(e)
            await asyncio.sleep(self._onerror_retry_interval)
        return key, client

    async def _update(self, client: ApolloClient, res: Dict[str, Any]):
        if not res:
            return
        tasks = set()
        for notification in res:
            namespace = notification['namespaceName']
            messages = notification['messages']
            label = self._registered[client][namespace].model_config.get('label')
            tasks.add(asyncio.create_task(client.uncached_config(namespace,
                                                                  messages=messages,
                                                                  label=label)))
        result = await asyncio.gather(*tasks)
        for res in result:
            if res:
                self._update_metadata(client, res)

    def _update_metadata(self, client: ApolloClient, res: Dict[str, Any]):
        if not res:
            return
        namespace = res['namespaceName']
        cls = self._registered[client][namespace]
        self._release_keys[client][namespace] = res['releaseKey']
        self._update_instances(cls, res['configurations'])

    @lru_cache
    def _get_alias(self, cls: Type["ApolloSettings"]):
        aliases = set()
        for field_info in cls.model_fields.values():
            if field_info.alias:
                _add_alias_to_set(aliases=aliases, alias=field_info.alias)
            if field_info.validation_alias:
                _add_alias_to_set(aliases=aliases, alias=field_info.validation_alias)
        return aliases

    def _update_instances(self, cls: Type["ApolloSettings"], config: Dict[str, str]):
        prefix = cls.model_config.get('env_prefix') or ''
        env_nested_delimiter = cls.model_config.get('env_nested_delimiter') or '__'
        aliases = self._get_alias(cls)
        arr_map = defaultdict(list)
        for k, v in config.items():
            key = k.replace(".", env_nested_delimiter)
            if m := ARRAY_RE.match(key):
                arr_map[m.group('name')].append((int(m.group('index')), v))
                continue
            if k not in aliases:
                key = f'{prefix}{key}'
            os.environ[key] = v

        for k, vs in arr_map.items():
            if k not in aliases:
                k = f'{prefix}{k}'
            os.environ[k] = json.dumps([v for _, v in sorted(vs)])

        if cls in ApolloSettings.__instances__:
            inst = ApolloSettings.__instances__[cls]
        else:
            inst = cls()
            ApolloSettings.__instances__[cls] = inst
        inst._init()

    async def _update_by_release_key(self, cls: Type["ApolloSettings"]):
        namespace = cls.__namespace__
        if not namespace:
            raise ValueError(f'{cls.__name__}:namespace must be set in model_config')
        client = self._get_client(cls)
        if not client:
            raise ValueError(f'{cls.__name__}:apollo client not found for {namespace}')
        release_key = self._release_keys[client][namespace]
        label = cls.__label__
        res = await client.uncached_config(namespace, release_key=release_key, label=label)
        if res:
            self._update_metadata(client, res)

    async def _start(self):
        if self._started:
            return
        self._started = True
        self._running_fut = asyncio.Future()
        # ensure all instances are initialized
        init_tasks, _ = await asyncio.wait({asyncio.create_task(self._notification_one(key, client, onerror_resume=False))
                            for key, client in self._clients.items()})
        for task in init_tasks:
            if e := task.exception():
                # instances init failed, raise it
                raise e
        self._started_fut.set_result(None)
        tasks = {asyncio.create_task(self._notification_one(key, client, self._onerror_resume))
                            for key, client in self._clients.items()}
        while self._started:
            done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                key, client = await task
                tasks.add(asyncio.create_task(self._notification_one(key, client, self._onerror_resume)))
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._running_fut.set_result(None)

    async def start(self):
        self._started_fut = asyncio.Future()
        asyncio.create_task(self._start())
        await self._started_fut

    async def stop(self):
        if not self._started:
            return
        self._started = False
        await self._running_fut

class ApolloSettings(BaseSettings):
    __metadata__:ApolloSettingsMetadata = ApolloSettingsMetadata()
    __instances__: Dict[Type["ApolloSettings"], "ApolloSettings"] = {}
    __namespace__: Optional[str] = None
    __label__: Optional[str] = None

    model_config = ApolloSettingsConfigDict(
        from_attributes=True,
        validate_assignment=True,
        env_nested_delimiter='__',
        env_prefix='APOLLO_',
    )

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs):
        namespace = cls.__namespace__
        if not namespace:
            return
        ApolloSettings.__metadata__.register(cls)

    # ensure singleton
    def __new__(cls, **kwargs):
        if cls not in cls.__instances__:
            inst = super().__new__(cls)
            cls.__instances__[cls] = inst
        return cls.__instances__[cls]

    def _init(self, **kwargs):
        super().__init__(**kwargs)

    def __init__(self, **kwargs):
        pass

    @classmethod
    async def start(cls):
        return await cls.__metadata__.start()

    @classmethod
    async def stop(cls):
        return await cls.__metadata__.stop()

    @classmethod
    async def refresh(cls):
        try:
            await ApolloSettings.__metadata__._update_by_release_key(cls)
            return True
        except:
            return False

    @model_validator(mode='before')
    @classmethod
    def debug_data(cls, data: Any):
        debug_logger.debug(f'data validation for {cls.__name__}: {data}')
        return data

    @classmethod
    def get(cls, name: str):
        for c in cls.__instances__.values():
            fields = c.model_fields
            if name in fields:
                return getattr(c, name)