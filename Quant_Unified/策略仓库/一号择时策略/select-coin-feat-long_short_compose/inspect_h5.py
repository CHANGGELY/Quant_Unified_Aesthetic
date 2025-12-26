import h5py

DATA_PATH = '/Users/chuan/Desktop/xiangmu/客户端/Quant_Unified/策略仓库/二号网格策略/data_center/ETHUSDT_1m_2019-11-01_to_2025-06-15_table.h5'

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
