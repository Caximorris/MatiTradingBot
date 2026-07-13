# Plan "pata corta" — investigacion de estrategias de trades cortos (base $10k hipotetica)

Fecha: 2026-07-13. Estado: PLAN APROBADO PARA EJECUCION (backtests si; paper/deploy con OK explicito).
Objetivo: comparar la rentabilidad de estrategias de frecuencia media/alta contra el Swing v5,
con base hipotetica $10,000, y medir si alguna sirve como "pata de ingresos" (ganancias mas
frecuentes, DD bajo). NO es un compromiso de capital real — es investigacion comparativa.

Reglas del marco (heredan SESSION.md "REGLAS INVARIANTES" y `docs/forward-test/contract.md`):
- NADA de esto toca v5/legacy/v6 ni la paridad F15. Bots nuevos = aislados, paper_state propio.
- Todo experimento se pre-registra en `EXPERIMENTS.md` (EXP-011, EXP-012) ANTES de iterar.
- Anclas de comparacion: CAGR y Max DD. PF solo como rango. Ademas, para el objetivo "ingresos":
  distribucion MENSUAL (media, mediana, % meses positivos, peor mes) — ver herramienta M0.
- Presupuestos de variantes DUROS (anti-overfit). Si se agota el presupuesto sin edge -> rejected.

---

## Benchmark: que hay que batir (base $10k)

| Estrategia | Ventana | CAGR | Max DD | $10k -> $/mes medio (aprox 1er ano) |
|---|---|---|---|---|
| Swing v5 (realistic) | 2018-26 | +47.1% | -53.7% | ~$390/mes (MUY irregular) |
| funding_extreme CON limites prop (bybit) | 2020-06 -> 2026-01 | ~+10.2% (total +71.96%) | -12.96% | ~$85/mes |
| funding_extreme CON limites prop (bybit_cons) | idem | ~+8.0% (total +53.68%) | -13.91% | ~$67/mes |

Lectura honesta: el Swing gana mucho mas pero con DD brutal; funding_extreme gana poco pero
con DD 4x menor. La pregunta de la Via A es cuanto CAGR recupera funding_extreme al quitarle
el corse prop (limites diarios pensados para un challenge, no para capital propio) y subir el
riesgo por trade. La Via B busca una fuente NUEVA (reversion condicionada por regimen).

---

## M0 — Herramienta previa: distribucion mensual (medio dia, primero de todo)

`tools/monthly_dist.py` — lee el journal de un backtest (equity_curve) SIN cargar el JSON crudo
en Claude (patron journal_summary) y saca: retorno por mes calendario, media, mediana,
% meses positivos, peor mes, mejor mes, racha max de meses negativos.

- Entrada: ruta a `backtests/journal_*.json`. Salida: tabla compacta + linea resumen.
- Es la metrica que responde "esto se parece a una nomina o no". Sin ella, la comparacion
  es solo CAGR/DD y no responde la pregunta del proyecto.
- Test minimo: equity sintetica con meses conocidos -> porcentajes correctos.

---

## Via A — EXP-011: funding_extreme como vehiculo propio (sin corse prop)

Motor YA validado (docs/prop/hyrotrader-plan.md §15): senal = funding Bybit en percentil
extremo trailing 90 settlements shift(1), dedup 72h, delay 24h en cola p95, hold 72h,
stop 2xATR14-4H, long-only. Edge estructural (cobrar a los apalancados en extremos), no
threshold fitted. Datos: `data/cache/funding_bybit_BTCUSDT.json` (2020-03 -> 2026-07-03).

### A0 — Sanity de reproduccion (1 run)
```
python main.py backtest --strategy funding --from 2020-06-01 --to 2026-01-01 --costs bybit --timeframe 1H
```
Esperado: pnl +71.96% | PF 1.44 | WR 50% | maxDD 12.96% | ~238 trades. Si no reproduce,
PARAR y entender por que antes de seguir (determinismo primero).

### A1 — Quitar limites prop (1 run, cambio AISLADO)
Los limites diarios (`max_entries_per_day=2, daily_loss_stop=0.015, daily_profit_stop=0.025,
daily_flatten=0.025`) son artefactos del challenge prop. Para capital propio se quitan.
**CUIDADO (verificado en codigo 2026-07-13):** `_manage` hace `day_pnl <= -cfg.daily_flatten`
-> poner 0.0 NO desactiva, cierra SIEMPRE. Desactivar con valores grandes:
```
--config '{"max_entries_per_day": 99, "daily_loss_stop": 1.0, "daily_profit_stop": 10.0, "daily_flatten": 1.0}'
```

### A2 — Sensibilidad de riesgo (2 runs, aislados sobre el ganador de A0 vs A1)
- `risk_per_trade`: 0.01 -> 0.02 (un run). Si escala lineal sin DD desproporcionado, bien;
  si el DD se dispara, el 1% era informacion, no eleccion.
- El run combinado (sin limites + risk 0.02) SOLO si ambos aportan por separado.

### A3 — Confirmacion en costes conservadores (1 run)
La config superviviente de A1/A2 con `--costs bybit_cons`. Si el edge desaparece con 10bps
de slippage, no hay pata de ingresos.

### A4 — OOS 2026 (1 run, solo lectura) — BLOQUEADO 2026-07-13
Refrescar cache de funding en DEV (`python tools/funding_refresh.py` — Bybit da 403 SOLO en
la VM) y correr 2026-01-01 -> hoy con la config final. ~6 meses = pocos trades: es
INDICATIVO, no gate. Se registra igual.
**BLOQUEO detectado:** el backtest post-2026-01 descargaria velas fuera del cache canonico
y lo MUTARIA (incidente prohibido 2026-07-06). Opciones antes de correrlo: (a) cache dir
alternativo si `data/ohlcv_cache.py` lo permite; (b) correr y restaurar con
`git checkout HEAD -- data/cache/BTC-USDT_1H.json` inmediatamente (remedio documentado).
Decidir con Matias — no ejecutar por defecto.

### Resultados Via A (2026-07-13, 5/6 runs — ver EXP-011 en EXPERIMENTS.md)
| Run | Config | Total | CAGR | Max DD | PF |
|---|---|---|---|---|---|
| A0 sanity | risk 1%, bybit | +72.73% | 10.3% | -12.96% | 1.44 |
| A1 sin limites | risk 1%, bybit | = A0 exacto | = | = | = |
| **A2 (ganador)** | **risk 2%, bybit** | **+115.88%** | **14.8%** | **-15.06%** | **1.42** |
| A2b sin limites | risk 2%, bybit | +116.22% | 14.8% | -16.05% | 1.41 |
| A3 conservador | risk 2%, bybit_cons | +84.08% | 11.5% | -16.58% | 1.32 |

Mensual del ganador: media +1.23%/mes | mediana +0.90% | 60% meses positivos | peor -7.1%
| racha max 3 meses neg. Lectura: los limites prop son irrelevantes (no muerden a 1%, frenan
un pelin el DD a 2%); el lever real es risk_per_trade y escala bien hasta 2% (Calmar mejora).
Gate: falla CAGR por 0.2pp (14.8 vs 15), cumple el resto. Queda A4 + decision de Matias.

### Frontera de riesgo/apalancamiento (2026-07-13, pedido por Matias — 3 runs extra)
Hallazgo previo: a risk 2% el cap `max_notional_pct=0.5` SATURA (trades entran al 50% justo)
-> el lever real de escala es el cap, no solo risk_per_trade.
| risk | cap | costes | CAGR | Max DD | PF | Calmar |
|---|---|---|---|---|---|---|
| 1% | 0.5 | bybit | 10.3% | -12.96% | 1.44 | 0.79 |
| 2% | 0.5 | bybit | 14.8% | -15.06% | 1.42 | 0.98 |
| **2%** | **1.0** | **bybit** | **19.8%** | **-20.59%** | 1.37 | **0.96** |
| 3% | 1.5 (leverage real) | bybit | 22.6% | -26.61% | 1.30 | 0.85 |
| 2% | 1.0 | realistic (OKX spot, sin funding) | 15.3% | -22.68% | 1.27 | 0.67 |
Conclusiones: (a) el tramo cap 0.5->1.0 (SIN prestamo, solo equity completo) captura casi
toda la escala disponible: +5pp CAGR por +5.5pp DD, Calmar plano; (b) leverage real (1.5x)
DEGRADA el Calmar — cada pp extra de CAGR cuesta DD desproporcionado; con stress 1.5-2x el
DD historico, 3%/1.5x vuelve a territorio Swing (-40/-53%) sin su retorno: el apalancamiento
destruye el unico diferencial de la estrategia (DD bajo); (c) ejecucion OKX SPOT (fee 10bps,
sin modelo de funding) es medible y peor: PF 1.27, Calmar 0.67, underwater max 555 dias — el
edge es fino y las fees spot se lo comen. Techo recomendado: risk 2% / cap 1.0 / sin leverage.
NOTA: dos journals de esta tanda colisionaron en timestamp (_154623, mismo segundo) y uno
sobrescribio al otro — los resultados impresos estan capturados aqui; re-correr si se
necesita el journal.

**Presupuesto total Via A: 6 runs. Gate para "candidato a pata de ingresos":**
CAGR >= 15% con Max DD <= 20%, >= 60% meses positivos (monthly_dist), PF > 1.3 en bybit_cons.
Si no pasa: se registra rejected como vehiculo propio (confirmando §15 del plan prop) y FIN.

### A5 — Camino a paper (SOLO si pasa el gate; NO empezar antes)
funding_extreme es hoy solo-backtest (funding accrual via `adjust_balance`). Para paper:
1. Feed de funding en vivo: Bybit 403 en la VM. Opciones en orden: (a) medir correlacion
   funding OKX vs Bybit en el historico comun; si r>0.9 y las senales coinciden >90%, cambiar
   fuente a OKX (`/api/v5/public/funding-rate-history`) — un experimento propio (re-run A-final
   con senales OKX); (b) si no, empujar el cache desde dev por cron/rsync.
2. Devengar funding en el paper client (o medir bruto y ajustar en reporting — decidir entonces).
Estimacion: 1-2 dias. Deploy en VM con OK explicito (regla `start`).

---

## Via B — EXP-012: "MR-Regimen 1H" (estrategia nueva, 2-6 trades/semana)

### B0 — PRE-REGISTRO (esto es el registro; no se toca tras el primer run)

**Hipotesis estructural:** en regimen macro alcista, las caidas bruscas de corto plazo en BTC
revierten (compradores de dip + tendencia de fondo); en regimen bajista esa misma senal es un
cuchillo cayendo. El edge esta en el CONDICIONAMIENTO por regimen, no en el oscilador.
(La mean reversion "a secas" ya fallo en este repo — `mean_reversion.py` borrado. Esta
hipotesis es distinta: mismo detector, universo restringido por el filtro maestro.)

**Filtro maestro (diario, dia UTC CERRADO — mismas condiciones que el regime_bull del Swing,
recalculadas internamente, SIN tocar swing_allocator.py):**
EMA50D > EMA200D AND close_D > EMA200D AND ADX14D > 15. Solo se opera si el dia ANTERIOR
cerrado cumplia (anti-lookahead identico al Swing).

**Senal 1H (default unico pre-registrado):**
- Entrada: close_1H < SMA20_1H - 2.0 * ATR14_1H -> BUY al close de esa vela. Cooldown 24h.
- Salidas: (a) close_1H >= SMA20_1H (reversion hecha); (b) time-stop 72h; (c) stop
  3.0 * ATR14_1H bajo el precio de entrada, chequeo intrabar low (patron funding_extreme).
- Sizing: riesgo 1% del equity por trade (distancia al stop). Long-only spot. Sin piramidar.

**Split de datos (INNEGOCIABLE):**
- IS (diseno): 2019-01-01 -> 2024-01-01.
- OOS (un SOLO run con la config elegida en IS): 2024-01-01 -> 2026-01-01.
- 2015-2026 completa: solo para medir robustez del resultado final, nunca para elegir params.
- Forward: paper en VM si pasa gates.

**Presupuesto de iteracion IS: 8 runs MAX**, solo sobre esta rejilla (nada fuera de ella):
mult de entrada {1.5, 2.0, 2.5} x time-stop {48h, 72h} + stop {2.5, 3.0} (los que quepan).
Costes `realistic` para iterar; el candidato final tambien `conservative`.

**Gates:**
- IS: PF > 1.2, >= 150 trades, Max DD < 25%, frecuencia en rango 2-6 trades/semana en bull.
- OOS: rentable, PF > 1.1, Max DD < 30%. Un solo intento — si falla, rejected, sin "ajustito".
- Kill inmediato: si hacen falta las 8 variantes para ver PF > 1 en IS, eso es fitting -> kill.

### B1 — Implementacion (1 dia)
- `strategies/mr_regime.py` (~300 lineas): funcion pura de senal testeable + clase bot,
  patron exacto de `funding_extreme.py` (compatible BacktestClient sin cambios de motor).
- Indicadores desde `strategies/indicators.py` (sma/ema/atr/adx — verificar que existen; si
  falta alguno, anadirlo ALLI, regla 11 de CLAUDE.md).
- Registrar en `strategies/registry.py` (name `mr_regime`, alias `mr` — el resolve ya casa
  con limite de palabra tras el fix `4b1425f`).
- Tests: senal pura (entra donde debe con OHLCV sintetico), regimen (no opera en bear),
  anti-lookahead (dia en curso no cuenta), from_dict/to_dict (leccion adx_min_entry).

### B2-B4 — Ejecucion
- B2: runs IS segun presupuesto (hasta 5 en paralelo, background).
- B3: monthly_dist del candidato + `/audit-backtest` (skill) para el chequeo de sesgos.
- B4: OOS single-shot -> decision -> EXPERIMENTS.md (accepted/rejected con metricas).
- Si pasa: proponer paper bot `mr_regime_btc_usdt` en la VM (OK explicito antes de deploy).

---

## Via C — Colector de microestructura (INFRA, no experimento; valor crece solo)

Proposito: acumular datos que NO se pueden backfillear (order book, funding cross-venue, OI,
agresion de trades). Es el prerequisito de cualquier intradia futuro y alimenta v6 (funding).
No se analiza nada ahora; revision trimestral.

### C1 — `tools/micro_collector.py` (medio dia)
Loop simple (urllib + sleep, sin dependencias nuevas; NUNCA `requests`), cada 15s por simbolo
(BTC-USDT, ETH-USDT + BTC-USDT-SWAP para lo de perps), endpoints publicos OKX (sin auth):
- `/api/v5/market/books?sz=20` -> spread, imbalance, profundidad top-20
- `/api/v5/public/funding-rate?instId=BTC-USDT-SWAP` -> funding instantaneo + next
- `/api/v5/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP`
- `/api/v5/market/trades?instId=BTC-USDT&limit=100` -> agresion buy/sell (dedup por tradeId)
Escritura: JSONL append `data/micro/YYYY-MM-DD_{inst}.jsonl`; al rotar dia -> gzip.
Presupuesto disco: ~10-20 MB/dia gz total -> <7 GB/ano. e2-micro (30 GB) OK.
Retencion: si el disco libre < 5 GB, borrar los meses mas viejos (log WARNING antes).
Robustez: backoff en errores; si 5 min sin exito -> WARNING (loguru). RAM objetivo < 50 MB.

### C2 — Reachability cross-venue desde la VM (30 min)
Probar desde la VM: OKX (sabemos que si), Bybit (403 conocido — reconfirmar), Binance
(`fapi/v1/premiumIndex`), y anadir al colector el funding de lo que responda. El funding
multi-venue es el dato mas valioso del colector (v6 + futuro intradia).

### C3 — Servicio (30 min)
`deploy/matibot-collector.service` calcado de `matibot.service` (usuario, restart=always,
`ExecStart=python tools/micro_collector.py`). Anadir chequeo `micro-collector-stale` a
`tools/anomaly_check.py` (patron daily-check-stale: mtime del ultimo JSONL > 1h = red flag).
Vigilar RAM/CPU de la e2-micro tras el deploy (ya corren 4-5 procesos).

### C4 — Tests minimos
Parser de cada endpoint con payload grabado; rotacion/gzip; dedup de trades.

---

## Orden de ejecucion propuesto (estos dias)

| Dia | Bloque | Entregable |
|---|---|---|
| 1 | M0 + A0..A4 | monthly_dist.py + 6 runs Via A + tabla comparativa vs Swing |
| 2 | B1 | mr_regime.py + tests + registry + primer run IS |
| 3 | B2-B4 | matriz IS (presupuesto 8) -> OOS single-shot -> decision EXP-012 |
| 3-4 (paralelo) | C1-C4 | colector + service + deploy VM (deploy con OK explicito) |

Pendiente PREVIO que no es de este plan (SESSION.md "SIGUIENTE PASO"): push de `7107631` +
commit/push del cliente OKX demo. No mezclar esos commits con los de este plan.

## Que NO se hace (para releerlo cuando tiente)
- No se opera intradia real: sin datos de microestructura propios no hay ventaja; el colector
  existe precisamente para reabrir esto en 6-12 meses.
- No se anaden variantes fuera de los presupuestos. No se "ajusta un poquito" tras ver el OOS.
- No se despliega nada en paper sin pasar gates + OK explicito.
- No se compara PF entre estrategias como ancla (regla invariante §2).
- No se toca pro_trend.py, swing_allocator.py, ni nada del forward-test vigente.
