import os
import ccxt
from dotenv import load_dotenv

# 加载环境变量
load_dotenv('策略仓库/八号香农策略/.env')

api_key = os.getenv("BINANCE_API_KEY")
secret = os.getenv("BINANCE_SECRET_KEY")

print(f"Loading keys from .env...")
print(f"API Key: {api_key[:10]}...")

def test_spot_demo():
    print("\n[Testing Spot API Candidates (Fake Production Mode)]")
    
    candidates = [
        ("Spot Testnet (Vision)", "https://testnet.binance.vision/api"),
        ("Spot Demo (Demo Domain)", "https://demo-api.binance.com/api"),
        ("Spot Production", "https://api.binance.com/api")
    ]
    
    found = False
    for name, base_url in candidates:
        print(f"  Trying {name}: {base_url}...")
        exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': secret,
            'options': {'defaultType': 'spot'},
            # DO NOT SET sandboxMode here
        })
        
        # Override URLs MANUALLY
        # Force production mode behavior but with custom URLs
        if 'api' not in exchange.urls: exchange.urls['api'] = {}
        
        exchange.urls['api']['public'] = base_url
        exchange.urls['api']['private'] = base_url
        exchange.urls['api']['v3'] = base_url + '/v3'
        
        # Kill sapi references in urls if they exist to prevent auto-usage
        if 'sapi' in exchange.urls: del exchange.urls['sapi']
        
        exchange.has['fetchFundingRate'] = False 
        
        try:
            # Try plain fetch_balance
            balance = exchange.fetch_balance({'type': 'spot'})
            print(f"  ✅ SUCCESS! Key is valid for: {name}")
            found = True
            break
        except Exception as e:
            msg = str(e)
            if "Invalid Api-Key" in msg or "API-key format invalid" in msg:
                 print(f"  ❌ Invalid Key for this env (-2008/-2014)")
            elif "sapi endpoints" in msg:
                 print(f"  ❌ CCXT Config Error: {msg}")
            else:
                 print(f"  ❌ Error: {msg[:100]}...")
    
    if not found:
        print("❌ All Spot candidates failed.")


def test_futures_demo():
    print("\n[Testing Futures API Candidates (Fake Production Mode)]")
    
    candidates = [
        ("Futures Testnet (Legacy)", "https://testnet.binancefuture.com/fapi"),
        ("Futures Demo (New)", "https://demo-fapi.binance.com/fapi"),
        ("Futures Production", "https://fapi.binance.com/fapi") # Just in case
    ]
    
    found = False
    for name, base_url in candidates:
        print(f"  Trying {name}: {base_url}...")
        exchange = ccxt.binanceusdm({
            'apiKey': api_key,
            'secret': secret,
            'options': {'defaultType': 'future'},
            # DO NOT SET sandboxMode here
        })
        
        v1_url = base_url + "/v1"
        
        if 'api' not in exchange.urls: exchange.urls['api'] = {}
        
        exchange.urls['api']['fapiPublic'] = v1_url
        exchange.urls['api']['fapiPrivate'] = v1_url
        exchange.urls['api']['fapiData'] = base_url.replace("fapi", "futures/data")
        exchange.urls['api']['public'] = v1_url
        exchange.urls['api']['private'] = v1_url
        
        # Kill other families to prevent issues
        for family in ['dapi', 'eapi', 'sapi', 'papi']:
            if family in exchange.urls:
                del exchange.urls[family]
        
        try:
            balance = exchange.fetch_balance()
            print(f"  ✅ SUCCESS! Key is valid for: {name}")
            found = True
            break
        except Exception as e:
            msg = str(e)
            if "Invalid Api-Key" in msg:
                 print(f"  ❌ Invalid Key for this env (Connection OK, Key Rejected)")
            elif "sapi endpoints" in msg:
                 print(f"  ❌ CCXT Config Error: {msg}")
            else:
                 print(f"  ❌ Error: {msg[:100]}...")

    if not found:
        print("❌ All Futures candidates failed.")

if __name__ == "__main__":
    if not api_key:
        print("Error: No API Key found in env")
    else:
        test_spot_demo()
        test_futures_demo()
