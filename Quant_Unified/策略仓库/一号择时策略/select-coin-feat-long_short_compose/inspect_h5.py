import h5py

from common_core.data_center import 生成分钟K线文件名, 获取分钟K线H5文件

DATA_PATH = 获取分钟K线H5文件(
    生成分钟K线文件名("ETHUSDT", 开始日期="2019-11-01", 结束日期="2025-06-15", 带table后缀=True)
)

def inspect_h5(path):
    print(f"Inspecting {path}...")
    try:
        with h5py.File(path, 'r') as f:
            print("Keys:", list(f.keys()))
            
            def print_attrs(name, obj):
                print(name)
                for key, val in obj.attrs.items():
                    print(f"    {key}: {val}")
                if isinstance(obj, h5py.Dataset):
                    print(f"    Shape: {obj.shape}, Dtype: {obj.dtype}")

            f.visititems(print_attrs)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    inspect_h5(DATA_PATH)
