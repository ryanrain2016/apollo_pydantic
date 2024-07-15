import asyncio
import datetime
from typing import List, Optional

from pydantic import AliasPath, BaseModel, Field, HttpUrl

from apollo_pydantic import (ApolloSettings, ApolloSettingsConfigDict,
                             enable_debug)


class Base(ApolloSettings):
    model_config = ApolloSettingsConfigDict(
        config_server='http://81.68.181.139:8080',
        appid='0001234',
        cluster='dev',
        secret_key='0398e769780c4e6399d9e6f73910e155' # if set
    )

class B(BaseModel):
    bb: List[int]
    cc: int = Field(validation_alias=AliasPath('bb', 0))

class ApolloSettingsModel(Base):
    __namespace__ = 'application'
    __label__ = None

    # apollo 的官方演示地址
    url: HttpUrl = 'http://81.68.181.139:8080'
    key1: str
    white_list: List[int] = Field(default_factory=lambda: ['1', '2', '3'])
    port: int
    redis_port: int
    is_encrypted: bool
    # a.bb[0] = xxx
    some_value: Optional[str] = Field(validation_alias=AliasPath('a', 'bb', 0))
    # c-dd = xxx
    cdd: str = Field(alias='c-dd')
    a: B
    start: datetime.timedelta = 1
    arr: List

class Abc(Base):
    __label__ = None
    __namespace__ = 'aUQTr9'

    aaa: str = Field(alias='abc')
    abc: int

async def main():
    # enable_debug()
    # 自动更新
    await ApolloSettings.start()
    while True:
        # 手动更新
        # await ApolloSettingsModel.refresh()
        print(ApolloSettingsModel(), datetime.datetime.now())
        print(Abc(), '###' * 20)
        await asyncio.sleep(10)

if __name__ == '__main__':
    # apollo配置如下
    """
    key1 = value1
    white_list = [1, 2, 3,"5",3734985]
    port = 3306
    redis_port = 6379
    is_encrypted = true
    123 = fsfg范德萨gf
    xxx = {"业务编号":"123","通道":"123"} # ignore
    a.bb[0] = 1
    a.bb[1] = 2
    c-dd = fgfg
    arr[0] = 123
    arr[1] = 2
    """
    enable_debug()
    print('##' * 20)
    asyncio.run(main())