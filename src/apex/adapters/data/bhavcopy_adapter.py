# apex-quant/src/apex/adapters/data/bhavcopy_adapter.py
"""NSE Bhavcopy & finstack EOD Historical Data Adapter.

Solves the Survivorship Bias limitation:
1. Ingests full NSE/BSE Bhavcopy CSVs containing ALL traded securities on any given trade date,
   including companies subsequently delisted, relegated to Z-group, or suspended.
2. Normalizes records into immutable Bar objects with is_closed=True.
3. Filters exclusively for Equity series ('EQ') to exclude debt/warrants/odd-lot instruments.
"""
import csv
from datetime import datetime
import io
from pathlib import Path
from typing import Dict, List, Optional, Sequence, AsyncIterator
from ...domain.enums import Timeframe
from ...domain.models import Bar
from ...ports.data_port import MarketDataPort
from ...core.ingestion import DataQualityError


class BhavcopyAdapter(MarketDataPort):
    """Historical data adapter loading survivor-bias-free NSE Bhavcopy archives."""

    def __init__(self, archive_dir: Optional[Path | str] = None) -> None:
        self.archive_dir = Path(archive_dir) if archive_dir else None
        # Internal in-memory historical storage: symbol -> list of Bars
        self._bars_by_symbol: Dict[str, List[Bar]] = {}

    def load_bhavcopy_csv(self, csv_content: str | Path) -> int:
        """Parse an official NSE Bhavcopy CSV (file path or string content).
        
        Supported formats:
        - Old format: SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TOTTRDQTY, TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN
        - UDiFF format: TckrSymb, SctySrs, OpnPric, HghPric, LwPric, ClsPric, PrvsClsgPric, TtlTradgVol, TtlTrfVal, TradDt
        """
        if isinstance(csv_content, Path) or (isinstance(csv_content, str) and "\n" not in csv_content and Path(csv_content).exists()):
            with open(csv_content, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            content = str(csv_content)

        reader = csv.DictReader(io.StringIO(content.strip()))
        loaded_count = 0

        for row in reader:
            # Strip whitespace from keys and values
            clean_row = {k.strip(): (v.strip() if v else "") for k, v in row.items() if k}

            # Filter for EQ series
            series = clean_row.get("SERIES", clean_row.get("SctySrs", ""))
            if series.upper() != "EQ":
                continue

            symbol_raw = clean_row.get("SYMBOL", clean_row.get("TckrSymb", ""))
            if not symbol_raw:
                continue

            symbol = f"{symbol_raw}.NS" if not symbol_raw.endswith(".NS") else symbol_raw

            # Date parsing
            date_str = clean_row.get("TIMESTAMP", clean_row.get("TradDt", ""))
            try:
                # Try standard NSE formats (DD-MMM-YYYY or YYYY-MM-DD)
                if "-" in date_str and len(date_str.split("-")[1]) == 3:
                    ts = datetime.strptime(date_str, "%d-%b-%Y")
                elif "-" in date_str:
                    ts = datetime.strptime(date_str, "%Y-%m-%d")
                else:
                    ts = datetime.now()
            except Exception:
                ts = datetime.now()

            try:
                opn = float(clean_row.get("OPEN", clean_row.get("OpnPric", 0.0)))
                hgh = float(clean_row.get("HIGH", clean_row.get("HghPric", 0.0)))
                low = float(clean_row.get("LOW", clean_row.get("LwPric", 0.0)))
                cls_p = float(clean_row.get("CLOSE", clean_row.get("ClsPric", 0.0)))
                vol = float(clean_row.get("TOTTRDQTY", clean_row.get("TtlTradgVol", 0.0)))
            except (ValueError, TypeError):
                continue

            # Ingestion sanity assertion
            if hgh < low or opn <= 0 or cls_p <= 0:
                continue

            bar = Bar(
                symbol=symbol,
                timeframe=Timeframe.D1,
                timestamp=ts,
                open=opn,
                high=hgh,
                low=low,
                close=cls_p,
                volume=vol,
                is_closed=True,
            )

            if symbol not in self._bars_by_symbol:
                self._bars_by_symbol[symbol] = []
            self._bars_by_symbol[symbol].append(bar)
            loaded_count += 1

        # Sort each series chronologically
        for sym in self._bars_by_symbol:
            self._bars_by_symbol[sym].sort(key=lambda b: b.timestamp)

        return loaded_count

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe = Timeframe.D1,
        bars: int = 100,
    ) -> Sequence[Bar]:
        """Fetch historical bars for symbol without survivorship filter."""
        formatted_symbol = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
        series = self._bars_by_symbol.get(formatted_symbol, [])
        if not series:
            return ()
        return series[-bars:]

    def get_all_traded_symbols(self) -> List[str]:
        """Return list of all symbols present in the Bhavcopy archive (including delisted)."""
        return list(self._bars_by_symbol.keys())

    async def stream_bars(
        self, symbols: Sequence[str], timeframe: Timeframe = Timeframe.D1
    ) -> AsyncIterator[Bar]:
        """Stream historical bars from the Bhavcopy archive."""
        for sym in symbols:
            bars = await self.get_ohlcv(sym, timeframe, 1)
            for b in bars:
                yield b
