
"""
test_rename_map.py - 重构路径映射生成器的单元测试

这个测试是干嘛的？
    我们在“目录中文化/目录结构统一”的重构里，会用一个脚本生成“旧路径 -> 新路径”的映射表，
    用来辅助批量替换文档/脚本里的引用。

这个测试要保证：
    映射表的 key/value 规则是稳定的，不会因为你改了别的代码就悄悄跑偏。
"""

import unittest
import os
import sys
import json

# Add the script directory to path so we can import it
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../文档/工程规划/scripts')))

from generate_rename_map import generate_map

class TestRenameMap(unittest.TestCase):
    def test_map_generation(self):
        expected_map = {
            "Quant_Unified/strategies": "Quant_Unified/策略仓库",
            "Quant_Unified/tests": "Quant_Unified/测试用例",
            "Quant_Unified/libs": "Quant_Unified/基础库",
            "Quant_Unified/apps": "Quant_Unified/应用",
            "Quant_Unified/services": "Quant_Unified/服务",
            "Quant_Unified/logs": "Quant_Unified/系统日志",
        }
        
        # Determine strict base path
        base_path = "Quant_Unified"
        
        generated = generate_map(base_path)
        
        # We only care about the keys that are actually present in the file system
        # But for the purpose of this test, we assume the spec is the truth.
        # However, the generator should verify existence. 
        # Let's mock the existence or just check if the logic produces the correct string transformation.
        
        for old, new in expected_map.items():
            self.assertIn(old, generated)
            self.assertEqual(generated[old], new)

if __name__ == '__main__':
    unittest.main()
