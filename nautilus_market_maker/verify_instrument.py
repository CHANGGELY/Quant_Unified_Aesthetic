
from decimal import Decimal
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.currencies import BTC, USDT, USDC
from nautilus_trader.model.objects import Price, Quantity, Money

def test_provider_example():
    print("Testing Provider Example...")
    return CryptoPerpetual(
        InstrumentId(
            symbol=Symbol("BTCUSDT-PERP"),
            venue=Venue("BINANCE"),
        ),
        raw_symbol=Symbol("BTCUSDT"),
        base_currency=BTC,
        quote_currency=USDT,
        settlement_currency=USDT,
        is_inverse=False,
        price_precision=1,
        price_increment=Price.from_str("0.1"),
        size_precision=3,
        size_increment=Quantity.from_str("0.001"),
        max_quantity=Quantity.from_str("1000.000"),
        min_quantity=Quantity.from_str("0.001"),
        max_notional=None,
        min_notional=Money(10.00, USDT),
        max_price=Price.from_str("809484.0"),
        min_price=Price.from_str("261.1"),
        margin_init=Decimal("0.0500"),
        margin_maint=Decimal("0.0250"),
        maker_fee=Decimal("0.000200"),
        taker_fee=Decimal("0.000180"),
        ts_event=0,
        ts_init=0,
    )

def test_my_instrument():
    print("Testing My Instrument...")
    instrument_id = InstrumentId(Symbol("BTCUSDC"), Venue("BINANCE"))
    return CryptoPerpetual(
        instrument_id=instrument_id,
        raw_symbol=Symbol("BTCUSDC"),
        base_currency=BTC,
        quote_currency=USDC,
        settlement_currency=USDC,
        is_inverse=False,
        price_precision=2,
        price_increment=Price.from_str("0.01"),
        size_precision=3,
        size_increment=Quantity.from_str("0.001"),
        max_quantity=Quantity.from_str("1000.000"),
        min_quantity=Quantity.from_str("0.001"),
        max_notional=None,
        min_notional=Money(5.00, USDC),
        max_price=Price.from_str("1000000.0"),
        min_price=Price.from_str("0.01"),
        margin_init=Decimal("0.0500"),
        margin_maint=Decimal("0.0250"),
        maker_fee=Decimal("0.000200"),
        taker_fee=Decimal("0.000400"),
        # ts_event=0, # Try commenting out
        # ts_init=0,
    )

if __name__ == "__main__":
    try:
        i1 = test_provider_example()
        print("Provider example: OK")
    except Exception as e:
        print(f"Provider example failed: {e}")

    try:
        i2 = test_my_instrument()
        print("My instrument: OK")
    except Exception as e:
        print(f"My instrument failed: {e}")
