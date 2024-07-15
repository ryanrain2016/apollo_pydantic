# apollo_pydantic
apollo_pydantic包是一个[apollo](https://www.apolloconfig.com/)的客户端封装，使用pydantic_settings的类型系统自动进行配置解析和类型转换，可以方便的使用apollo配置，可以自动或者手动同步配置。
pydantic_settings详情见[pydantic_settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
当使用apollo作为微服务配置中心时，推荐使用apollo_pydantic。


## 如何安装
`apollo_pydantic`已上传至pypi，可以通过如下命令安装
```bash
pip install apollo_pydantic
```

## 注意事项
1. 建议使用一个`Base`类作为配置类基类，设置apollo的相关链接参数。当使用多个appid和cluster时，需要配置多个基类
2. 每个设置类对应一个namespace， 继承同一个配置基类下的配置类namespace不允许重复
3. 每个设置类对应一个label， 用于apollo的灰度发布使用的label
```python
class Base(ApolloSettings):
    model_config = ApolloSettingsConfigDict(
        # 官方演示地址
        config_server='http://81.68.181.139:8080',
        appid='0001234',
        cluster='dev',
        secret_key='0398e769780c4e6399d9e6f73910e155' # if set
    )

class ApolloSettingsModel(Base):
    __namespace__ = 'application'
    __label__ = None

    ...
```
4. 支持嵌套的配置项，但是要注意嵌套配置项需要继承自`pydantic.BaseModel`,并且要在根配置类前定义， 否则可能有解析失败的情况,具体详情见[pydantic_settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
```python
class Base(ApolloSettings):
    ...

class Nested(BaseModel):
    some_name: str

class ApolloSettingsModel(Base):
    __namespace__ = 'application'

    # 配置项 nested.some_name = xxx
    nested: Nested

await ApolloSettingsModel.refresh() # 主动刷新
print(ApolloSettingsModel().nested.some_name) # xxx
```

5. 支持配置项的`validation_alias`和`alias`属性， 该属性可以为配置项指定别名，如配置项`alias_name = some_value`可以设置`validation_alias = 'alias_name'`或者`alias = 'alias_name'`， 该字段会解析为`some_value`. 注意设置别名时，不要包含`.`符号， 因为`.`符号会被解析为嵌套的配置项
apollo配置如下:
```
some_name = xxx
```
python代码如下:
```python
class Base(ApolloSettings):
    ...
class ApolloSettingsModel(Base):
    __namespace__ = 'application'
    __label__ = None
    # 配置项 some_name = xxx
    some_value: str = Field(alias='some_name')

await ApolloSettingsModel.refresh() # 主动刷新
print(ApolloSettingsModel().some_value) # xxx
```
慎用`AliasPath`, 除非精通`pydantic_settings`的使用。
6. 支持自定义`Field`，相关校验参见[pydantic_settings](https://docs.pydantic.dev/latest/api/fields/)
7. 支持数组类型配置，如配置项`some_name[0] = xxx`和`some_name[1] = yyy`， 该字段会解析为`['xxx', 'yyy']`, 该种方式目前不支持数组中嵌套配置项类。如要使用这种配置项可以直接使用json来实现
```python
class Base(ApolloSettings):
    ...
class ApolloSettingsModel(Base):
    __namespace__ = 'application'
    __label__ = None
    # 配置项
    # some_name[0] = xxx
    # some_name[1] = yyy
    some_name: List[str]

    # 配置项
    # some_value = ["xxx", "yyy"]
    some_json_value: List[str]

await ApolloSettingsModel.refresh() # 主动刷新
print(ApolloSettingsModel().some_name) # ['xxx', 'yyy']
print(ApolloSettingsModel().some_json_value) # ['xxx', 'yyy']
8. 暂不支持同步线程的方式同步配置，后续会有同步线程的支持
```
## 例子
例子详见`apollo_pydantic/examples`目录。
apollo的官方演示地址为`http://81.68.181.139`
### 使用pydantic_settings
```python
import asyncio
import datetime
from typing import List, Optional

from pydantic import AliasPath, BaseModel, Field, HttpUrl

from apollo_pydantic import (ApolloSettings, ApolloSettingsConfigDict,
                             enable_debug)


class Base(ApolloSettings):
    model_config = ApolloSettingsConfigDict(
        # 官方演示地址
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
    # a.bb[0] = 123
    some_value: Optional[str] = Field(validation_alias=AliasPath('a', 'bb', 0)) # 这里使用AliasPath，需要该配置类必须要有`a`字段
    # c-dd = xxx
    c_dd: str = Field(alias='c-dd')
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
```
# 集成fastapi
```python
from fastapi import FastAPI
...
# some imports

class Base(ApolloSettings):
    model_config = ApolloSettingsConfigDict(
        # 官方演示地址
        config_server='http://81.68.181.139:8080',
        appid='0001234',
        cluster='dev',
        secret_key='0398e769780c4e6399d9e6f73910e155' # if set
    )
...
# define your settings

async def sync_settings(app: FastAPI):
    # 自动同步
    await ApolloSettings.start()
    yield app
    await ApolloSettings.stop()

app = FastAPI(lifespan=sync_settings)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)

```
# 功能
- 自动同步配置
