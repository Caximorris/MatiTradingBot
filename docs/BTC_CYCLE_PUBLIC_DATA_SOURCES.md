# Public BTC Cycle Data Sources

The pipeline is read-only and uses `urllib.request`; each response is cached under
`data/btc_cycle_audit/`, hashed, and never silently overwritten.

| Role | Source | Endpoint/documentation | Notes |
|---|---|---|---|
| Primary halving/block truth | Blockstream Esplora | https://github.com/Blockstream/esplora/blob/master/API.md | Block hash by height, then block timestamp by hash. |
| Price | Coinbase Exchange public candles | https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles | BTC-USD daily candles; provider coverage/rate limits are recorded. |
| Price | Bitstamp public OHLC | https://www.bitstamp.net/api/ | BTC/USD daily OHLCV. |
| Price | Kraken Spot OHLC | https://docs.kraken.com/api/docs/rest-api/get-ohlc-data | XBT/USD daily OHLCV; API history limits are recorded. |
| Secondary documentary/reference | Coin Metrics | https://coinmetrics.io/community-network-data/ | Add through a separate adapter when the requested metric/coverage is available. |

All timestamps are normalized to UTC. A provider failure is a failed source, not a fallback that
erases provenance. The canonical series stores provider count, min/max, dispersion, and status for
each UTC day. Historical revisions create a new content-addressed snapshot.
