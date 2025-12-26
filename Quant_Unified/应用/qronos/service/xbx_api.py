"""
XBX API 服务模块

该模块提供与第三方XBX API的交互功能，主要包括：
1. 用户认证和token管理
2. 基础代码版本获取和下载
3. 市值数据下载
4. 文件下载和解压功能
5. 自动重试和错误处理机制

主要特性：
- 单例模式管理API实例
- 自动token刷新机制
- 统一的重试装饰器
- 完善的错误处理和日志记录
- 支持大文件下载和解压

"""

import json
import os
import time
import traceback
import zipfile
import random
from datetime import datetime
from typing import Optional, Tuple
from functools import wraps
from pathlib import Path

import requests

from model.enum_kit import StatusEnum
from model.model import Pm2CfgModel
from service.command import create_pm2_cfg
from utils.constant import (
    api_qtcls_user_login_token_url, api_qtcls_data_client_basic_code_url, api_qtcls_data_coin_cap_hist_url,
    api_qtcls_user_info_url, api_qtcls_basic_code_download_ticket_url, api_qtcls_basic_code_download_link_url,
    TMP_PATH, FRAMEWORK_TYPE, DATA_CENTER_ID, FRAMEWORK_ROOT_PATH, api_qtcls_user_info_v2_url,
)
from db.db_ops import (
    get_user, save_user_credentials, update_user_xbx_token, save_framework_status, update_framework_status_and_path,
    get_framework_status
)
from utils.log_kit import logger


class TokenExpiredException(Exception):
    """
    Token过期异常
    
    当检测到多次401错误且token刷新失败时抛出此异常。
    表示用户的apikey已过期，需要重新获取wx_token和更新用户凭据。
    """

    def __init__(self, message="Token已过期，需要重新认证"):
        self.message = message
        super().__init__(self.message)


def retry_request(max_retries=5):
    """
    请求重试装饰器
    
    为网络请求提供自动重试功能，支持指数退避策略。
    当请求失败时，会自动重试指定次数，每次重试间隔递增。
    
    :param max_retries: 最大重试次数，默认5次
    :type max_retries: int
    :return: 装饰器函数
    :rtype: function
    
    Example:
        @retry_request(max_retries=3)
        def api_call():
            return requests.get("https://api.example.com")
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:  # 不是最后一次重试
                        # 指数退避策略：1-3秒 * (重试次数 + 1)
                        delay = random.uniform(1, 3) * (attempt + 1)
                        logger.warning(f"请求失败，第{attempt + 1}次重试，{delay:.2f}秒后重试: {e}")
                        time.sleep(delay)
                    else:
                        logger.error(f"请求失败，已达到最大重试次数{max_retries}: {e}")

            # 所有重试都失败，抛出最后一个异常
            if last_exception:
                raise last_exception

        return wrapper

    return decorator


def _download_file_zip(download_url, temp_path, target_path, max_retries=5):
    """
    下载并解压ZIP文件，带重试逻辑
    
    该函数实现了完整的文件下载和解压流程，包括：
    - 流式下载大文件
    - 自动重试机制
    - 损坏文件清理
    - 解压到指定目录
    
    :param download_url: 文件下载链接
    :type download_url: str
    :param temp_path: 临时文件存储路径
    :type temp_path: Path
    :param target_path: 目标解压路径
    :type target_path: Path
    :param max_retries: 最大重试次数，默认3次
    :type max_retries: int
    :return: 成功返回True，失败返回False
    :rtype: bool
    
    note:
        - 使用流式下载避免内存溢出
        - 失败时会自动清理损坏的临时文件
        - 支持断点续传（如果文件已存在则跳过下载）
    """
    # 离线模式下，不执行实际下载
    logger.warning("离线模式：跳过实际文件下载")
    return True


class XbxAPI:
    """
    XBX API 客户端类
    
    该类采用单例模式，提供与XBX第三方API的完整交互功能。
    主要功能包括用户认证、代码下载、数据获取等。
    
    Features:
        - 单例模式：确保全局只有一个API实例
        - 自动token管理：包括获取、刷新、存储
        - 统一错误处理：标准化的异常处理和重试机制
        - 数据库集成：自动保存用户凭据和状态信息

    Example:
        # 获取API实例
        api = XbxAPI.get_instance()
        
        # 设置用户凭据
        api.set_credentials("user_uuid", "user_apikey")
        
        # 登录获取token
        if api.login():
            # 获取基础代码版本
            versions = api.get_basic_code_version()
    """

    _instance: Optional['XbxAPI'] = None

    def __init__(self):
        """
        初始化XBX API客户端
        
        私有构造函数，仅在单例模式中使用。
        自动从数据库加载用户凭据和token。
        """
        self.uuid: Optional[str] = None
        self.apikey: Optional[str] = None
        self.token: Optional[str] = None
        self._auth_failure_count: int = 0  # 401认证失败计数器
        self._max_auth_failures: int = 5  # 最大允许的认证失败次数
        self._load_credentials()  # 从数据库加载用户凭据
        self._load_token()  # 从数据库加载token

    @classmethod
    def get_instance(cls, uuid=None, apikey=None):
        """
        获取XBX API单例实例
        
        :param uuid: 用户UUID，如果提供则更新凭据
        :type uuid: str, optional
        :param apikey: 用户API密钥，如果提供则更新凭据
        :type apikey: str, optional
        :return: API实例
        :rtype: XbxAPI
        
        note:
            如果是首次调用，会创建新实例。
            如果提供了uuid和apikey，会更新实例的凭据。
        """
        if cls._instance is None:
            cls._instance = XbxAPI()
        if uuid and apikey:
            cls._instance.set_credentials(uuid, apikey)
        return cls._instance

    def _load_credentials(self):
        """
        从数据库加载用户凭据
        
        从数据库中读取用户的UUID和API密钥。
        如果数据库中没有用户信息，凭据将保持为None。
        """
        user = get_user()
        if user:
            self.uuid = user.uuid
            self.apikey = user.apikey

    def _save_credentials(self):
        """
        保存用户凭据到数据库
        
        将当前的UUID和API密钥保存到数据库中。
        用于持久化用户认证信息。
        """
        save_user_credentials(self.uuid, self.apikey)

    def _load_token(self):
        """
        从数据库加载访问token
        
        从数据库中读取当前有效的访问token。
        token用于后续的API调用认证。
        """
        user = get_user()
        if user:
            self.token = user.xbx_token

    def _save_token(self, token):
        """
        保存访问token到数据库
        
        :param token: 要保存的访问token
        :type token: str
        
        将新的token保存到数据库并更新实例状态。
        """
        self.token = token
        update_user_xbx_token(token)

    def set_credentials(self, uuid: str, apikey: str):
        """
        设置用户凭据
        
        :param uuid: 用户UUID
        :type uuid: str
        :param apikey: 用户API密钥
        :type apikey: str
        
        更新实例的凭据信息并保存到数据库。
        通常在用户首次登录或更换账户时调用。
        重置认证失败计数器。
        """
        self.uuid = uuid
        self.apikey = apikey
        self._auth_failure_count = 0  # 重置认证失败计数器
        self._save_credentials()
        logger.info("用户凭据已更新，认证失败计数器已重置")

    def login(self) -> bool:
        """
        用户登录获取访问token (离线模式)
        """
        logger.info("离线模式：模拟登录成功")
        self._save_token("mock_token_offline")
        return True

    def _ensure_token(self):
        """
        确保有有效的访问token (离线模式)
        """
        self._load_token()
        if not self.token:
             self.login()

    def _handle_token_refresh(self, resp, params, url, method='GET'):
        """
        统一处理token刷新逻辑 (离线模式)
        """
        return None

    def get_basic_code_version(self, version: str = '') -> dict:
        """
        获取基础代码版本信息 (离线模式)
        
        扫描本地 FRAMEWORK_ROOT_PATH 目录，返回存在的框架。
        """
        logger.info("离线模式：扫描本地框架版本")
        
        # 构造 mock 数据结构
        data_list = []
        
        # 遍历定义的框架类型
        for fw_id, fw_type in FRAMEWORK_TYPE.items():
            # 检查本地是否有对应的文件夹
            # 这里假设用户手动放置的文件夹名称包含类型名
            # 简单起见，我们查找所有子目录，如果包含类型名则认为匹配
            
            versions = []
            if FRAMEWORK_ROOT_PATH.exists():
                for item in FRAMEWORK_ROOT_PATH.iterdir():
                    if item.is_dir():
                        # 简单的匹配逻辑，或者直接列出所有文件夹
                        # 为了配合 get_basic_code_version 的返回值结构，我们需要构造 version 对象
                        versions.append({
                            "time": datetime.fromtimestamp(item.stat().st_mtime).strftime('%Y-%m-%d %H:%M'),
                            "hidden": False,
                            "file": {
                                "id": fw_id,
                                "name": item.name
                            }
                        })
            
            # 如果没有找到，为了演示，添加一个虚拟版本
            if not versions:
                 versions.append({
                    "time": datetime.now().strftime('%Y-%m-%d %H:%M'),
                    "hidden": False,
                    "file": {
                        "id": fw_id,
                        "name": f"{fw_type}_offline_v1"
                    }
                })

            data_list.append({
                "id": fw_id,
                "name": fw_type,
                "title": fw_type,
                "versions": versions
            })

        return {"data": data_list}

    @staticmethod
    def _create_pm2_config(framework_id: str, framework_path, app_configs: list):
        """
        创建PM2配置文件
        """
        logger.info(f"为框架 {framework_id} 创建PM2配置，应用列表: {app_configs}")
        pm2_cfg = Pm2CfgModel(apps=[
            create_pm2_cfg(app_name=app_name, framework_id=framework_id, framework_path=framework_path)
            for app_name in app_configs
        ])
        config_path = framework_path / 'startup.json'
        config_path.write_text(json.dumps(pm2_cfg.model_dump(), ensure_ascii=False, indent=2))
        logger.info(f"PM2配置文件已保存: {config_path}")

    def download_data_center_latest(self):
        """
        下载最新的数据中心代码 (离线模式)
        """
        logger.info("离线模式：检查数据中心是否存在")
        
        # 假设用户已经将数据中心代码放入了 FRAMEWORK_ROOT_PATH 下的某个目录
        # 我们扫描该目录，找到可能是数据中心的文件夹
        found = False
        if FRAMEWORK_ROOT_PATH.exists():
            for item in FRAMEWORK_ROOT_PATH.iterdir():
                if item.is_dir() and "data_center" in item.name:
                    logger.info(f"发现本地数据中心: {item}")
                    
                    # 更新数据库状态
                    save_framework_status(
                        DATA_CENTER_ID,
                        item.name,
                        StatusEnum.FINISHED,
                        "data_center",
                        datetime.fromtimestamp(item.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
                    )
                    
                    update_framework_status_and_path(
                        DATA_CENTER_ID,
                        StatusEnum.FINISHED,
                        item
                    )
                    
                    self._create_pm2_config(DATA_CENTER_ID, item, ['realtime_data'])
                    found = True
                    break
        
        if not found:
            logger.warning("未发现本地数据中心文件夹 (需包含 'data_center')")


    def download_basic_code_for_id(self, framework_id):
        """
        根据框架ID下载指定的基础代码 (离线模式)
        """
        logger.info(f"离线模式：下载框架 {framework_id}")
        # 逻辑同上，扫描本地文件夹
        fw_type = FRAMEWORK_TYPE.get(framework_id, "unknown")
        
        found = False
        if FRAMEWORK_ROOT_PATH.exists():
            for item in FRAMEWORK_ROOT_PATH.iterdir():
                if item.is_dir() and fw_type in item.name:
                    logger.info(f"发现本地框架: {item}")
                    
                    save_framework_status(
                        framework_id,
                        item.name,
                        StatusEnum.FINISHED,
                        fw_type,
                        datetime.fromtimestamp(item.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
                    )
                    
                    update_framework_status_and_path(
                        framework_id,
                        StatusEnum.FINISHED,
                        item
                    )
                    
                    if framework_id == DATA_CENTER_ID:
                         self._create_pm2_config(framework_id, item, ['realtime_data'])
                    else:
                         self._create_pm2_config(framework_id, item, ['startup', 'delist', 'monitor'])
                    
                    found = True
                    break
                    
        if not found:
             logger.warning(f"未发现本地框架文件夹 (需包含 '{fw_type}')")

    def download_coin_cap_hist(self, coin_cap_path):
        """
        下载历史市值数据 (离线模式)
        """
        logger.info(f"离线模式：假装下载市值数据到 {coin_cap_path}")
        coin_cap_path.mkdir(parents=True, exist_ok=True)
        return True

    def get_user_info(self, authorization: str):
        """
        获取用户信息 (离线模式)
        """
        return self.get_user_info_by_authorization(authorization)

    @staticmethod
    def get_user_info_by_authorization(authorization: str):
        """
        获取用户信息 (离线模式)
        """
        logger.info("离线模式：返回 Mock 用户信息")
        return {
            "uuid": "local-uuid-123456",
            "apiKey": "local-api-key-abcdef",
            "username": "OfflineUser",
            "email": "offline@local.host"
        }

    def get_user_info_by_token(self):
        """
        获取用户信息v2 (离线模式)
        """
        logger.info("离线模式：返回 Mock 用户信息 v2")
        return {
            "uuid": "local-uuid-123456",
            "apiKey": "local-api-key-abcdef",
            "username": "OfflineUser",
            "email": "offline@local.host"
        }

    def _get_download_ticket(self, code_id: str) -> Optional[str]:
        return "mock_ticket"

    def get_download_url_for_code(self, code_id: str) -> Tuple[bool, Optional[str], Optional[str]]:
        return True, "http://localhost/mock.zip", "mock_ticket"

    def download_basic_code(self, code_id):
        return True, Path("/mock/path")
