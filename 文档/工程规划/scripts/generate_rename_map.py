import os

def generate_map(base_path="Quant_Unified"):
    mapping = {
        "strategies": "策略仓库",
        "tests": "测试用例",
        "libs": "基础库",
        "apps": "应用",
        "services": "服务",
        "logs": "系统日志"
    }
    
    result = {}
    for old_name, new_name in mapping.items():
        old_full_path = os.path.join(base_path, old_name)
        new_full_path = os.path.join(base_path, new_name)
        
        # We include it in the map regardless of existence for the purpose of the Spec,
        # but in a real run we might want to filter. 
        # The test expects the map to contain these keys.
        result[old_full_path] = new_full_path
        
    return result

if __name__ == "__main__":
    import json
    print(json.dumps(generate_map(), indent=4, ensure_ascii=False))