"""
Quant Unified 量化交易系统
[异步工具函数库]
功能：提供 async/await 语境下的辅助工具，重点包含异步重试装饰器，确保高并发任务的健壮性。
"""
import asyncio
import traceback
from functools import wraps

async def async_retry_wrapper(func, params={}, func_name='', if_exit=True):
    """
    Async retry wrapper
    """
    max_retries = 3
    for i in range(max_retries):
        try:
            if params:
                return await func(params)
            else:
                return await func()
        except Exception as e:
            print(f'❌{func_name} 出错: {e}')
            if i < max_retries - 1:
                print(f'⏳正在重试 ({i+1}/{max_retries})...')
                await asyncio.sleep(1)
            else:
                print(traceback.format_exc())
                if if_exit:
                    raise e
    return None
