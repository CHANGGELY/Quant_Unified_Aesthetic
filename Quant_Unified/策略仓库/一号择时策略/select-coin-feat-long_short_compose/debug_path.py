from pathlib import Path
import sys

# Mock config
try:
    from config import swap_path
    from core.utils.functions import is_trade_symbol
except ImportError:
    # If imports fail (e.g. run from wrong dir), define minimal mocks
    current_dir = Path(__file__).parent
    swap_path = current_dir / 'data' / 'swap'
    
    def is_trade_symbol(symbol, black_list=()):
        if not symbol or symbol.startswith('.') or not symbol.endswith('USDT'):
            return False
        return True

print(f"Checking path: {swap_path}")
print(f"Path exists: {swap_path.exists()}")

found_files = list(swap_path.rglob('*-USDT.csv'))
print(f"Total files found by rglob: {len(found_files)}")

valid_symbols = []
for f in found_files:
    if is_trade_symbol(f.stem):
        valid_symbols.append(f.stem)
    else:
        print(f"Invalid symbol: {f.stem}")

print(f"Valid symbols count: {len(valid_symbols)}")
if len(valid_symbols) > 0:
    print(f"First 5 valid symbols: {valid_symbols[:5]}")
