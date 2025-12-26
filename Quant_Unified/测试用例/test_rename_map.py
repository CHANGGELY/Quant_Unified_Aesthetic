
import unittest
import os
import sys
import json

# Add the script directory to path so we can import it
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../conductor/scripts')))

from generate_rename_map import generate_map

class TestRenameMap(unittest.TestCase):
    def test_map_generation(self):
        expected_map = {
            "Quant_Unified.策略仓库": "Quant_Unified/策略仓库",
            "Quant_Unified.测试用例": "Quant_Unified/测试用例",
            "Quant_Unified.基础库": "Quant_Unified/基础库",
            "Quant_Unified.应用": "Quant_Unified/应用",
            "Quant_Unified.服务": "Quant_Unified/服务",
            "Quant_Unified.系统日志": "Quant_Unified/系统日志"
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
