"""Read-only smoke check and symbol-metadata export. No account/order access."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import main


if __name__=='__main__':
    main.connect()
    metadata, observations = {}, []
    for base in main.WATCH:
        symbol=main.resolve(base)
        info=main.mt5.symbol_info(symbol)
        metadata[symbol]=dict(point=info.point,trade_tick_size=info.trade_tick_size,digits=info.digits)
        result=main.technical(base)
        observations.append(result)
        print(json.dumps(dict(symbol=symbol,analysis=result['analysis_status'],feed=result['live_feed_status'],as_of=result['as_of_utc'],quote=result['market_context']['quote_time_utc'],reasons=result['reasons'])),flush=True)
    Path('validation/metadata.json').write_text(json.dumps(metadata,indent=2))
    Path('validation/live-check.json').write_text(json.dumps(observations,indent=2,allow_nan=False))
