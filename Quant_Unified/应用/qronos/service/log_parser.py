"""
数据中心日志解析模块

该模块用于解析数据中心运行时的日志文件，提取时间点和操作信息。
支持解析各种数据中心操作，包括数据更新、K线获取、预处理等。

主要功能：
1. 解析日志文件格式
2. 提取操作时间点和操作类型
3. 识别操作状态（进行中、完成、失败）
4. 计算操作耗时
5. 生成结构化的操作信息
6. 按任务块分组操作（以Update开始到下一个Update为一个任务块）

日志格式：
- 时间戳格式：YYYY-MM-DD HH:MM:SS.sss +08:00:
- 状态标识：🌀（进行中）、✅（完成）、⚠️（警告）
- 操作类型：更新数据、获取K线、预处理、合并等
"""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Any

from utils.log_kit import get_logger

logger = get_logger()


class OperationStatus(str, Enum):
    """操作状态枚举"""
    IN_PROGRESS = "in_progress"  # 进行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    SKIPPED = "skipped"  # 跳过
    UNKNOWN = "unknown"  # 未知


class OperationType(str, Enum):
    """操作类型枚举"""
    UPDATE_CYCLE = "update_cycle"  # 更新周期
    EXCHANGE_INFO = "exchange_info"  # 获取交易所信息
    MARKET_CAP_UPDATE = "market_cap_update"  # 市值数据更新
    KLINE_UPDATE = "kline_update"  # K线数据更新
    KLINE_API = "kline_api"  # K线API调用
    DATA_API_UPDATE = "data_api_update"  # Data API K线更新
    PREPROCESSING = "preprocessing"  # 数据预处理
    PIVOT_PROCESSING = "pivot_processing"  # Pivot表处理
    KLINE_MERGE = "kline_merge"  # K线合并
    SKIP_OPERATION = "skip_operation"  # 跳过操作
    OTHER = "other"  # 其他


@dataclass
class LogOperation:
    """日志操作数据结构"""
    timestamp: str  # 时间戳
    datetime_obj: datetime  # 解析后的时间对象
    operation_type: OperationType  # 操作类型
    status: OperationStatus  # 操作状态
    description: str  # 操作描述
    details: Dict[str, Any]  # 详细信息
    duration: Optional[float] = None  # 耗时（秒）

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "timestamp": self.timestamp,
            "operation_type": self.operation_type.value,
            "status": self.status.value,
            "description": self.description,
            "details": self.details,
            "duration": self.duration
        }


@dataclass
class TaskBlock:
    """任务块数据结构"""
    id: str  # 任务块ID，基于运行时间生成
    start_time: str  # 任务块开始时间
    end_time: str  # 任务块结束时间
    runtime: str  # 原始运行时间字符串
    operations: List[LogOperation]  # 该任务块包含的所有操作

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "id": self.id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "runtime": self.runtime,
            "operations": [op.to_dict() for op in self.operations],
            "operation_count": len(self.operations),
            "block_duration": self._calculate_block_duration()
        }

    def _calculate_block_duration(self) -> Optional[float]:
        """计算任务块总耗时"""
        if not self.operations:
            return None
        
        # 计算开始时间到最后一个操作的时间差
        try:
            start_time = datetime.strptime(self.start_time, '%Y-%m-%d %H:%M:%S')
            last_op_time = max(op.datetime_obj.replace(tzinfo=None) for op in self.operations)
            duration = (last_op_time - start_time).total_seconds()
            return round(duration, 2)
        except Exception:
            return None


class DataCenterLogParser:
    """数据中心日志解析器"""

    # 时间戳正则表达式
    TIMESTAMP_PATTERN = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \+08:00):'

    # 操作模式匹配规则
    OPERATION_PATTERNS = [
        # 更新周期开始
        {
            'pattern': r'================== Update 5m Runtime=(.+?) ===================',
            'type': OperationType.UPDATE_CYCLE,
            'status': OperationStatus.IN_PROGRESS,
            'extract_runtime': True
        },

        # 获取交易所信息
        {
            'pattern': r'Exchange Info 与实时资金费获取成功',
            'type': OperationType.EXCHANGE_INFO,
            'status': OperationStatus.COMPLETED
        },

        # 市值数据更新
        {
            'pattern': r'🌀 更新市值数据, 当前时间=(.+)',
            'type': OperationType.MARKET_CAP_UPDATE,
            'status': OperationStatus.IN_PROGRESS,
            'extract_current_time': True
        },
        {
            'pattern': r'🌀 市值数据更新成功, 当前时间=(.+?), 耗时=(.+?)分钟',
            'type': OperationType.MARKET_CAP_UPDATE,
            'status': OperationStatus.COMPLETED,
            'extract_duration': True
        },

        # K线数据更新开始
        {
            'pattern': r'🌀 开始更新币安 (spot|swap) K 线, 交易对数量=(\d+), 当前时间=(.+)',
            'type': OperationType.KLINE_UPDATE,
            'status': OperationStatus.IN_PROGRESS,
            'extract_details': True
        },

        # K线API完成
        {
            'pattern': r'✅ Binance (spot|swap) API, 获取 5m 成功, Resample 并更新 1h 成功, 耗时=(.+?)秒, 当前时间=(.+)',
            'type': OperationType.KLINE_API,
            'status': OperationStatus.COMPLETED,
            'extract_duration': True,
            'extract_details': True
        },

        # Data API K线更新开始
        {
            'pattern': r'🌀 开始请求 Data API K 线, 当前时间=(.+)',
            'type': OperationType.DATA_API_UPDATE,
            'status': OperationStatus.IN_PROGRESS,
            'extract_data_api_time': True
        },

        # Data API请求失败重试
        {
            'pattern': r'❌ 请求 DataAPI URL 失败, 重试中, 当前时间=(.+?),',
            'type': OperationType.DATA_API_UPDATE,
            'status': OperationStatus.FAILED,
            'extract_data_api_time': True
        },

        # Data API URL就绪
        {
            'pattern': r'✅ DataAPI URL 就绪, DataAPI 时间戳=(.+?), 当前时间=(.+)',
            'type': OperationType.DATA_API_UPDATE,
            'status': OperationStatus.COMPLETED,
            'extract_data_api_ready': True
        },

        # Data API现货URL请求
        {
            'pattern': r'🌀 data_api_spot=(.+)',
            'type': OperationType.DATA_API_UPDATE,
            'status': OperationStatus.IN_PROGRESS,
            'extract_data_api_url': True
        },

        # Data API合约URL请求
        {
            'pattern': r'🌀 data_api_swap=(.+)',
            'type': OperationType.DATA_API_UPDATE,
            'status': OperationStatus.IN_PROGRESS,
            'extract_data_api_url': True
        },

        # Data API现货数据更新成功
        {
            'pattern': r'✅ 获取并合并 DataAPI 数据 spot 成功, 当前时间=(.+)',
            'type': OperationType.DATA_API_UPDATE,
            'status': OperationStatus.COMPLETED,
            'extract_data_api_success': True
        },

        # Data API合约数据更新成功
        {
            'pattern': r'✅ 获取并合并 DataAPI 数据 swap 成功, 当前时间=(.+)',
            'type': OperationType.DATA_API_UPDATE,
            'status': OperationStatus.COMPLETED,
            'extract_data_api_success': True
        },

        # 预处理开始
        {
            'pattern': r'🌀 开始预处理 (spot|swap), 当前时间=(.+)',
            'type': OperationType.PREPROCESSING,
            'status': OperationStatus.IN_PROGRESS,
            'extract_details': True
        },

        # 预处理批次完成
        {
            'pattern': r'预处理 Market Dict (spot|swap) batch(\d+) 完成, 交易对=(.+?) -- (.+?), 数据源=(.+?), 当前时间=(.+?), 耗时 (.+?) 秒',
            'type': OperationType.PREPROCESSING,
            'status': OperationStatus.IN_PROGRESS,
            'extract_batch_details': True
        },

        # 预处理完成
        {
            'pattern': r'✅ 预处理 Market Dict (spot|swap) 完成, 当前时间=(.+?), 耗时 (.+?) 秒',
            'type': OperationType.PREPROCESSING,
            'status': OperationStatus.COMPLETED,
            'extract_duration': True,
            'extract_details': True
        },

        # Pivot表处理
        {
            'pattern': r'🌀 生成 Market Pivot (spot|swap) (\d+) 完成',
            'type': OperationType.PIVOT_PROCESSING,
            'status': OperationStatus.IN_PROGRESS,
            'extract_details': True
        },
        {
            'pattern': r'✅ 预处理 Pivot Table (spot|swap) 完成, 当前时间=(.+?), 耗时 (.+?) 秒',
            'type': OperationType.PIVOT_PROCESSING,
            'status': OperationStatus.COMPLETED,
            'extract_duration': True,
            'extract_details': True
        },

        # K线合并
        {
            'pattern': r'🌀 开始合并币安 (spot|swap) 5m K 线, 当前时间=(.+)',
            'type': OperationType.KLINE_MERGE,
            'status': OperationStatus.IN_PROGRESS,
            'extract_details': True
        },
        {
            'pattern': r'✅ 合并币安 (spot|swap) 5m K 线成功, 当前时间=(.+)',
            'type': OperationType.KLINE_MERGE,
            'status': OperationStatus.COMPLETED,
            'extract_details': True
        },

        # 跳过操作
        {
            'pattern': r'🌀 Runtime=(.+?),不在 Offset=(.+?) 中，休息 60s 后，跳过',
            'type': OperationType.SKIP_OPERATION,
            'status': OperationStatus.SKIPPED,
            'extract_skip_details': True
        }
    ]

    def __init__(self):
        """初始化解析器"""
        pass

    def parse_log_file(self, log_file_path: Path, hours: Optional[int] = None) -> List[LogOperation]:
        """
        解析日志文件
        
        Args:
            log_file_path: 日志文件路径
            hours: 获取最近多少小时的日志，None表示解析全部
            
        Returns:
            解析后的操作列表
        """
        logger.info(f"开始解析日志文件: {log_file_path}")

        if not log_file_path.exists():
            logger.error(f"日志文件不存在: {log_file_path}")
            return []

        operations = []

        try:
            with open(log_file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            logger.info(f"读取日志行数: {len(lines)}")

            # 计算时间阈值（如果指定了小时数）
            time_threshold = None
            if hours is not None:
                from datetime import timedelta, timezone
                # 使用当前时间（北京时间 UTC+8）
                current_time = datetime.now(timezone(timedelta(hours=8)))
                time_threshold = current_time - timedelta(hours=hours)
                logger.info(f"时间过滤阈值: {time_threshold.strftime('%Y-%m-%d %H:%M:%S %z')} (最近{hours}小时)")

            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line:
                    continue

                operation = self._parse_log_line(line)
                if operation:
                    # 如果指定了时间范围，进行时间过滤
                    if time_threshold is not None:
                        # 比较操作时间与阈值
                        if operation.datetime_obj < time_threshold:
                            continue  # 跳过超出时间范围的操作
                    
                    operations.append(operation)

            logger.info(f"解析完成，共提取 {len(operations)} 个操作")
            if hours is not None:
                logger.info(f"时间过滤范围: 最近 {hours} 小时")

            # 按时间排序
            operations.sort(key=lambda x: x.datetime_obj)

            return operations

        except Exception as e:
            logger.error(f"解析日志文件失败: {e}")
            return []

    def _parse_log_line(self, line: str) -> Optional[LogOperation]:
        """
        解析单行日志
        
        Args:
            line: 日志行内容
            
        Returns:
            解析后的操作对象，如果无法解析则返回None
        """
        # 提取时间戳
        timestamp_match = re.match(self.TIMESTAMP_PATTERN, line)
        if not timestamp_match:
            return None

        timestamp_str = timestamp_match.group(1)
        content = line[len(timestamp_match.group(0)):].strip()

        # 解析时间戳
        try:
            datetime_obj = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S.%f %z')
        except ValueError:
            logger.warning(f"无法解析时间戳: {timestamp_str}")
            return None

        # 匹配操作模式
        for pattern_info in self.OPERATION_PATTERNS:
            match = re.search(pattern_info['pattern'], content)
            if match:
                return self._create_operation(
                    timestamp_str, datetime_obj, content, pattern_info, match
                )

        # 未匹配到已知模式，归类为其他
        return LogOperation(
            timestamp=timestamp_str,
            datetime_obj=datetime_obj,
            operation_type=OperationType.OTHER,
            status=OperationStatus.UNKNOWN,
            description=content,
            details={}
        )

    @staticmethod
    def _create_operation(timestamp_str: str, datetime_obj: datetime,
                          content: str, pattern_info: Dict, match: re.Match) -> LogOperation:
        """
        根据匹配结果创建操作对象
        
        Args:
            timestamp_str: 时间戳字符串
            datetime_obj: 时间对象
            content: 日志内容
            pattern_info: 模式信息
            match: 正则匹配结果
            
        Returns:
            操作对象
        """
        details = {}
        duration = None

        # 提取运行时时间
        if pattern_info.get('extract_runtime'):
            details['runtime'] = match.group(1)

        # 提取当前时间
        if pattern_info.get('extract_current_time'):
            details['current_time'] = match.group(1)

        # 提取Data API时间
        if pattern_info.get('extract_data_api_time'):
            details['current_time'] = match.group(1)

        # 提取Data API就绪信息
        if pattern_info.get('extract_data_api_ready'):
            details['data_api_timestamp'] = match.group(1)
            details['current_time'] = match.group(2)

        # 提取Data API URL信息
        if pattern_info.get('extract_data_api_url'):
            details['data_api_url'] = match.group(1)
            # 从描述中提取API类型（spot或swap）
            if 'data_api_spot' in content:
                details['api_type'] = 'spot'
            elif 'data_api_swap' in content:
                details['api_type'] = 'swap'

        # 提取Data API成功信息
        if pattern_info.get('extract_data_api_success'):
            details['current_time'] = match.group(1)
            # 从描述中提取数据类型（spot或swap）
            if ' spot ' in content:
                details['data_type'] = 'spot'
            elif ' swap ' in content:
                details['data_type'] = 'swap'

        # 提取耗时信息
        if pattern_info.get('extract_duration'):
            try:
                if 'spot' in content or 'swap' in content:
                    # K线API的耗时格式：耗时=16.8秒
                    duration_str = match.group(2)
                    if '秒' in duration_str:
                        duration = float(duration_str.replace('秒', ''))
                    elif '分钟' in duration_str:
                        duration = float(duration_str.replace('分钟', '')) * 60
                else:
                    # 市值数据的耗时格式：耗时=0.07分钟
                    duration_str = match.group(2)
                    if '分钟' in duration_str:
                        duration = float(duration_str.replace('分钟', '')) * 60
                    elif '秒' in duration_str:
                        duration = float(duration_str.replace('秒', ''))
            except (IndexError, ValueError) as e:
                logger.warning(f"解析耗时失败: {e}")

        # 提取详细信息
        if pattern_info.get('extract_details'):
            if pattern_info['type'] == OperationType.KLINE_UPDATE:
                details['market_type'] = match.group(1)  # spot 或 swap
                details['pair_count'] = int(match.group(2))
                details['current_time'] = match.group(3)
            elif pattern_info['type'] == OperationType.KLINE_API:
                details['market_type'] = match.group(1)
                details['current_time'] = match.group(3)
            elif pattern_info['type'] == OperationType.PREPROCESSING:
                if 'Market Dict' not in content:  # 开始预处理
                    details['market_type'] = match.group(1)
                    details['current_time'] = match.group(2)
                else:  # 预处理完成
                    details['market_type'] = match.group(1)
                    details['current_time'] = match.group(2)
            elif pattern_info['type'] == OperationType.PIVOT_PROCESSING:
                if '生成' in content:
                    details['market_type'] = match.group(1)
                    details['year'] = match.group(2)
                else:
                    details['market_type'] = match.group(1)
                    details['current_time'] = match.group(2)
            elif pattern_info['type'] == OperationType.KLINE_MERGE:
                details['market_type'] = match.group(1)
                details['current_time'] = match.group(2)

        # 提取批次处理详细信息
        if pattern_info.get('extract_batch_details'):
            details.update({
                'market_type': match.group(1),
                'batch_number': int(match.group(2)),
                'start_pair': match.group(3),
                'end_pair': match.group(4),
                'data_source': match.group(5),
                'current_time': match.group(6),
                'batch_duration': float(match.group(7))
            })

        # 提取跳过操作详细信息
        if pattern_info.get('extract_skip_details'):
            details.update({
                'runtime': match.group(1),
                'offset_range': match.group(2)
            })

        return LogOperation(
            timestamp=timestamp_str,
            datetime_obj=datetime_obj,
            operation_type=pattern_info['type'],
            status=pattern_info['status'],
            description=content,
            details=details,
            duration=duration
        )

    @staticmethod
    def group_operations_by_task_blocks(operations: List[LogOperation]) -> List[TaskBlock]:
        """
        按任务块分组操作
        
        以每个 "Update 5m Runtime" 或 "跳过操作" 为起点，将其到下一个周期开始之间的所有操作归为一个任务块。
        
        Args:
            operations: 操作列表
            
        Returns:
            任务块列表
        """
        if not operations:
            return []

        task_blocks = []
        current_block_operations = []
        current_runtime = None
        current_start_time = None

        for operation in operations:
            # 判断是否为新任务块的开始：Update周期开始 或 跳过操作
            is_new_block_start = (
                operation.operation_type == OperationType.UPDATE_CYCLE or 
                operation.operation_type == OperationType.SKIP_OPERATION
            )
            
            if is_new_block_start:
                # 遇到新的任务块开始，先保存当前任务块（如果有）
                if current_block_operations and current_runtime and current_start_time:
                    task_block = DataCenterLogParser._create_task_block(
                        current_runtime, current_start_time, current_block_operations
                    )
                    task_blocks.append(task_block)
                
                # 开始新的任务块
                if operation.operation_type == OperationType.UPDATE_CYCLE:
                    # 正常的Update周期
                    current_runtime = operation.details.get('runtime', operation.timestamp)
                else:
                    # 跳过操作：从details中提取runtime
                    current_runtime = operation.details.get('runtime', operation.timestamp)
                
                current_start_time = operation.timestamp
                current_block_operations = [operation]
            else:
                # 添加到当前任务块
                if current_block_operations is not None:
                    current_block_operations.append(operation)

        # 处理最后一个任务块
        if current_block_operations and current_runtime and current_start_time:
            task_block = DataCenterLogParser._create_task_block(
                current_runtime, current_start_time, current_block_operations
            )
            task_blocks.append(task_block)

        return task_blocks

    @staticmethod
    def _create_task_block(runtime: str, start_time: str, operations: List[LogOperation]) -> TaskBlock:
        """
        创建任务块对象
        
        Args:
            runtime: 运行时间字符串
            start_time: 开始时间
            operations: 操作列表
            
        Returns:
            任务块对象
        """
        # 生成任务块ID（基于运行时间）
        try:
            # 尝试解析运行时间并格式化为ID
            runtime_obj = datetime.fromisoformat(runtime.replace('+08:00', '+08:00'))
            task_id = runtime_obj.strftime('%Y%m%d%H%M%S')
        except Exception:
            # 如果解析失败，使用原始字符串生成ID
            import hashlib
            task_id = hashlib.md5(runtime.encode()).hexdigest()[:12]

        # 计算结束时间（最后一个操作的时间）
        if operations:
            end_time = max(op.timestamp for op in operations)
        else:
            end_time = start_time

        # 格式化开始时间（移除毫秒和时区）
        try:
            start_datetime = datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S.%f %z')
            formatted_start_time = start_datetime.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            formatted_start_time = start_time

        # 格式化结束时间
        try:
            end_datetime = datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S.%f %z')
            formatted_end_time = end_datetime.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            formatted_end_time = end_time

        return TaskBlock(
            id=task_id,
            start_time=formatted_start_time,
            end_time=formatted_end_time,
            runtime=runtime,
            operations=operations
        )

def merge_duplicate_task_blocks(task_blocks: List[TaskBlock], merge_window_minutes: int = 2) -> List[TaskBlock]:
    """
    合并跳过操作中相同Runtime的任务块
    
    针对所有包含跳过操作的任务块进行合并，基于相同的Runtime值和时间窗口进行合并。
    
    Args:
        task_blocks: 任务块列表
        merge_window_minutes: 合并时间窗口（分钟）
        
    Returns:
        合并后的任务块列表
    """
    if not task_blocks:
        return []
    
    # 分离跳过操作和其他操作
    skip_blocks = []
    other_blocks = []
    
    for block in task_blocks:
        # 检查任务块是否包含跳过操作（可能包含多个跳过操作）
        has_skip_operations = any(op.operation_type == OperationType.SKIP_OPERATION for op in block.operations)
        if has_skip_operations:
            # 进一步检查是否所有操作都是跳过操作
            all_skip = all(op.operation_type == OperationType.SKIP_OPERATION for op in block.operations)
            if all_skip:
                skip_blocks.append(block)
            else:
                # 混合类型的任务块，暂时不合并
                other_blocks.append(block)
        else:
            other_blocks.append(block)
    
    logger.info(f"找到 {len(skip_blocks)} 个跳过操作任务块，{len(other_blocks)} 个其他任务块")
    
    # 对跳过操作按Runtime分组
    runtime_groups = {}
    for block in skip_blocks:
        # 获取任务块中第一个跳过操作的runtime（同一任务块中所有跳过操作的runtime应该相同）
        runtime = None
        for operation in block.operations:
            if operation.operation_type == OperationType.SKIP_OPERATION:
                runtime = operation.details.get('runtime', '')
                break
        
        if runtime:
            if runtime not in runtime_groups:
                runtime_groups[runtime] = []
            runtime_groups[runtime].append(block)
    
    merged_skip_blocks = []
    merge_count = 0
    
    # 合并相同Runtime的跳过操作
    for runtime, blocks in runtime_groups.items():
        if len(blocks) == 1:
            # 只有一个块，无需合并
            merged_skip_blocks.append(blocks[0])
        else:
            # 有多个相同Runtime的块，需要合并
            logger.info(f"发现 {len(blocks)} 个相同Runtime的跳过操作任务块: {runtime}")
            
            # 按开始时间排序
            blocks.sort(key=lambda b: datetime.strptime(b.start_time, '%Y-%m-%d %H:%M:%S'))
            
            # 将所有相同Runtime的任务块合并为一个
            merged_block = blocks[0]  # 使用第一个块作为基础
            
            # 将后续所有块的操作添加到第一个块中
            for next_block in blocks[1:]:
                # 计算时间差（用于日志记录）
                current_time = datetime.strptime(merged_block.start_time, '%Y-%m-%d %H:%M:%S')
                next_time = datetime.strptime(next_block.start_time, '%Y-%m-%d %H:%M:%S')
                time_diff_minutes = (next_time - current_time).total_seconds() / 60
                
                logger.info(f"合并跳过操作任务块 Runtime={runtime}: "
                           f"将 {next_block.start_time} 的 {len(next_block.operations)} 个操作合并到主块")
                
                # 合并操作列表
                merged_block.operations.extend(next_block.operations)
                merge_count += 1
            
            # 更新结束时间为所有操作中的最新时间
            if merged_block.operations:
                latest_time = max(op.timestamp for op in merged_block.operations)
                try:
                    latest_datetime = datetime.strptime(latest_time, '%Y-%m-%d %H:%M:%S.%f %z')
                    merged_block.end_time = latest_datetime.strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    # 如果解析失败，使用最后一个块的结束时间
                    merged_block.end_time = blocks[-1].end_time
            
            # 按时间戳重新排序所有操作
            merged_block.operations.sort(key=lambda op: op.datetime_obj)
            
            # 添加合并后的块
            merged_skip_blocks.append(merged_block)
            
            logger.info(f"跳过操作任务块合并完成，Runtime={runtime}: "
                       f"合并了 {len(blocks)} 个任务块 -> 1个任务块，包含 {len(merged_block.operations)} 个操作")
    
    # 合并所有结果：其他任务块 + 合并后的跳过操作任务块
    all_merged_blocks = other_blocks + merged_skip_blocks
    
    # 按开始时间重新排序所有任务块
    all_merged_blocks.sort(key=lambda b: datetime.strptime(b.start_time, '%Y-%m-%d %H:%M:%S'))
    
    original_skip_count = len(skip_blocks)
    final_skip_count = len(merged_skip_blocks)
    
    logger.info(f"跳过操作合并完成: 原 {original_skip_count} 个跳过操作任务块 -> 合并后 {final_skip_count} 个 (合并了 {merge_count} 个)")
    logger.info(f"总任务块: 原 {len(task_blocks)} 个 -> 最终 {len(all_merged_blocks)} 个")
    
    return all_merged_blocks


def parse_data_center_logs(framework_id: str, hours: Optional[int] = 24) -> Dict[str, Any]:
    """
    解析指定数据中心框架的日志
    
    Args:
        framework_id: 数据中心框架ID
        hours: 获取最近多少小时的日志，None表示获取全部
        
    Returns:
        解析结果字典，包含任务块分组的数据
    """
    logger.info(f"解析数据中心日志: framework_id={framework_id}, hours={hours}")

    from db.db_ops import get_framework_status

    # 获取框架状态
    framework_status = get_framework_status(framework_id)
    if not framework_status or not framework_status.path:
        logger.error(f"数据中心框架未找到或路径为空: {framework_id}")
        return {"error": "数据中心框架未找到"}

    framework_path = Path(framework_status.path)

    # 查找日志文件
    log_files = []

    # 查找系统日志目录下的realtime_data.out-{pm2_id}.log文件
    logs_dir = framework_path / "系统日志"
    if logs_dir.exists():
        # 使用glob模式匹配realtime_data.out-*.log文件
        log_pattern = "realtime_data.out-*.log"
        matched_files = list(logs_dir.glob(log_pattern))
        
        # 过滤掉日志轮转文件
        for log_file in matched_files:
            # 跳过PM2 logrotate插件生成的拆分文件：
            # 1. 数字后缀：realtime_data.out-9.log.1, realtime_data.out-9.log.2
            # 2. 时间戳后缀：realtime_data.out-9__2025-07-12_00-15-46.log
            file_name = log_file.name
            
            # 跳过数字后缀的轮转文件
            if any(file_name.endswith(f'.{i}') for i in range(1, 10)):
                logger.debug(f"跳过数字后缀轮转文件: {file_name}")
                continue
                
            # 跳过包含双下划线时间戳的拆分文件
            if '__' in file_name and file_name.count('__') >= 1:
                # 检查是否包含日期时间格式
                if re.search(r'__\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}', file_name):
                    logger.debug(f"跳过时间戳拆分文件: {file_name}")
                    continue
            
            # 只处理主日志文件
            log_files.append(log_file)
            logger.info(f"找到数据中心日志文件: {log_file}")

    if not log_files:
        logger.warning(f"未找到数据中心日志文件: {framework_path}")
        return {"error": "未找到日志文件"}

    # 使用第一个找到的日志文件
    log_file = log_files[0]
    logger.info(f"使用日志文件: {log_file}")

    # 解析日志
    parser = DataCenterLogParser()
    operations = parser.parse_log_file(log_file, hours=hours)

    if not operations:
        return {"error": "日志解析失败或无有效操作"}

    # 过滤掉description为空的操作
    operations = [op for op in operations if op.description and op.description.strip()]
    logger.info(f"过滤空描述后，剩余 {len(operations)} 个操作")

    if not operations:
        return {"error": "过滤后无有效操作"}

    # 按任务块分组操作
    task_blocks = parser.group_operations_by_task_blocks(operations)
    
    # 合并具有相同ID的任务块
    task_blocks = merge_duplicate_task_blocks(task_blocks, merge_window_minutes=2)

    # 构建返回结果
    result = {
        "framework_info": {
            "framework_id": framework_id,
            "framework_name": framework_status.framework_name,
            "log_file": str(log_file),
            "framework_path": str(framework_path)
        },
        "task_blocks": [block.to_dict() for block in task_blocks],
        "task_blocks_count": len(task_blocks)
    }

    logger.info(f"日志解析完成，共 {len(operations)} 个操作，{len(task_blocks)} 个任务块")
    if hours is not None:
        logger.info(f"时间范围: 最近 {hours} 小时")

    return result
