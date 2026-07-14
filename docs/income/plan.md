# Plan "pata corta" — investigacion de estrategias de trades cortos (base $10k hipotetica)

Fecha: 2026-07-13. Estado (2026-07-14): Via A y Via B CERRADAS, ambas rejected (ver EXP-011/
EXP-012 en EXPERIMENTS.md). Via C (colector microestructura) sigue sin empezar, infra de bajo
riesgo, revision trimestral — no es una estrategia. Sin candidato vivo de "pata de ingresos"
por ahora; el objetivo del plan no se cumplio con las hipotesis probadas.
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

### Decision final Via A (2026-07-14) — REJECTED, ver EXP-011 en EXPERIMENTS.md
No solo por el fallo marginal de gate (CAGR 14.8% vs 15%, -0.2pp). Comparado contra Swing v6
por Calmar (CAGR/MaxDD, la metrica que de verdad importa para elegir vehiculo):

| Vehiculo | CAGR | Max DD | Calmar |
|---|---:|---:|---:|
| Swing v6 (2015-26 realistic) | +86.51% | -52.73% | **1.64** |
| funding_extreme A2 (risk 2%, bybit) | +14.8% | -15.06% | 0.98 |
| funding_extreme cap 1.0 sin leverage | +19.8% | -20.59% | 0.96 |
| funding_extreme risk 3%/leverage 1.5x | +22.6% | -26.61% | 0.85 (peor) |

Ninguna variante de la frontera de riesgo alcanza el Calmar de Swing; escalar con leverage
real EMPEORA el ratio. Tampoco es diversificacion real: ambos motores son long-only
direccional BTC, correlacionados en el tail risk. El insight de fondo (funding en percentil
extremo) ya esta capturado sin este vehiculo por `strategies/swing_funding_overlay.py` dentro
de v6-2 (tilt ±0.05, sin apalancamiento ni infra de perps nueva) — construir un vehiculo
propio aparte, con peor Calmar, es esfuerzo duplicado. Segunda vez que este motor se rechaza
en un framing distinto (primera vez: prop firm CFT, `docs/prop/hyrotrader-plan.md` §15).
A4 (OOS 2026) NO se ejecuta — el plan ya marca ese resultado como indicativo, no gate, y no
cambiaria el veredicto. Via A queda cerrada.

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

### Resultado B1+B2 (2026-07-14) — REJECTED, ver EXP-012 en EXPERIMENTS.md
8/8 runs del presupuesto ejecutados 2019-2024 realistic. Mejor PF de la rejilla: 0.63
(entry_mult=1.5, stop_mult=3.0) — ninguna variante cruza PF 1.0, muy lejos del gate
IS (>1.2). `time_stop_hours` (48 vs 72) resulto inerte: mismos trades/PnL exactos en
ambos casos, todo se resuelve por reversion o stop antes de llegar al time-stop. Kill
inmediato por pre-registro (necesitar las 8 variantes para buscar PF>1 = fitting).
B3 (monthly_dist) y B4 (OOS 2024-2026, single-shot) NO se ejecutan — no hay candidato
que llevar a OOS y el pre-registro prohibe gastar ese intento sin superar IS primero.
Via B queda cerrada. `strategies/mr_regime.py` se conserva en el repo (codigo valido,
registrado en `strategies/registry.py` como `mr_regime`/alias `mr`, con tests) por si
en el futuro se quiere probar una hipotesis distinta sobre el mismo esqueleto.

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

## Via D — EXP-013: Basis Carry (cash-and-carry, market-neutral)

### D0 — PRE-REGISTRO (2026-07-14)

**Hipotesis estructural:** a diferencia de todo lo probado en Via A/B (y de Swing v6),
esta NO es una apuesta direccional sobre el precio de BTC. Comprar BTC spot y abrir un
short SINTETICO de igual cantidad (solo backtest, mark-to-market por barra, patron de
`prop_swing.py`) deja la exposicion neta al precio en ~0: las ganancias/perdidas de
ambas patas se cancelan. El retorno viene SOLO del funding rate (los longs pagan a los
shorts cuando el funding es positivo). Motivo para probarlo: es la unica idea de esta
sesion que no repite el patron de fallo de EXP-011/012 (direccional, correlacionado con
Swing) — es diversificacion real, no una version mas lenta del mismo riesgo.

**Mecanica:** `strategies/basis_carry.py`. Entra cuando el promedio movil trailing de
90 settlements (30 dias) de funding Bybit es > `funding_min_avg` (default 0.0 — umbral
estructural "carry esperado positivo", no fitted); sale a plano cuando el promedio cae
por debajo. Sizing: `notional_pct` del equity en la pata spot (misma qty en la pata
corta). Fuente de datos: Bybit (igual que EXP-011 — el endpoint publico de OKX solo
retiene ~3 meses de funding, confirmado empiricamente el 2026-07-14).

**Gate (una sola config por defecto, sin grid — el parametro no se ajusta buscando
mejor resultado, es un umbral estructural fijo):** rentable neto de costes, Max DD
sustancialmente menor que Swing (se espera <5%, dado que el hedge es delta-neutral),
Calmar y/o Sharpe reportados aunque el CAGR absoluto sea bajo — el objetivo de este
vehiculo es diversificacion, no competir en CAGR con Swing.

**Ventana:** todo el historico de funding Bybit disponible (~2020-03 -> hoy), la misma
que uso EXP-011 — no hay split IS/OOS clasico porque no hay parametros de entrada/salida
que ajustar mas alla del umbral estructural fijo.

### D1 — Implementacion (hecho 2026-07-14)
- `strategies/basis_carry.py`: reusa `load_funding()` de `funding_extreme.py` (DRY) y el
  patron de short sintetico de `prop_swing.py` (mtm + accrue_funding + cierre).
  Registrado en `strategies/registry.py` (`basis_carry`, alias `basis`). 6 tests
  unitarios (senal pura + from_dict/to_dict). Suite completa 271/271.

**CAVEAT de reporting (descubierto 2026-07-14, aplica tambien a `funding_extreme` y a
los shorts de `prop_swing`):** la tabla "Ganadores/Perdedores / Avg Win / PF" del
backtest usa `BacktestEngine._compute_trade_pnl_acb`, que empareja SOLO las ordenes
reales que pasan por `place_order` (`self._client._executed`) — es CIEGA a cualquier
`adjust_balance` (mark-to-market del short sintetico, funding). Para `basis_carry` esto
es especialmente enganoso: la tabla muestra el P&L de la pata SPOT SOLA (sin cobertura),
con oscilaciones grandes que parecen una apuesta direccional volatil, cuando la cartera
real (pata corta + funding incluidos) es casi plana. **Las metricas de verdad para
esta estrategia son Balance final / CAGR / Max Drawdown / Sharpe** (vienen del balance
real, que si integra cada `adjust_balance`) — NO la tabla de trades. No arreglar el
motor generico para esto (afectaria el reporting de otras estrategias); documentar el
caveat y leer las metricas correctas basta.

**Resultado full-history (2026-07-14), `--costs bybit`, `funding_min_avg=0.0` (config
default, sin ajustar):**

| Ventana | Balance final | CAGR | Max DD | Time in market |
|---|---:|---:|---:|---:|
| 2020-06 -> 2026-01 | $9,728.36 | -0.49%/ano | **-2.60%** | 94.9% |

Lectura: la tesis de neutralidad delta se CONFIRMA con fuerza — Max DD de -2.60% en
una ventana que incluye el crash de mayo 2021 (-50%+ en semanas) y el bear 2022, contra
el -52.73% de Swing v6 en ventanas comparables. Pero la tesis de rentabilidad NO se
confirma con el gate por defecto (`funding_min_avg=0.0`, "mantener mientras el
promedio trailing sea positivo"): el resultado neto de costes es ligeramente negativo.
El motor SI capturo el episodio de funding extremo de 2021 (documentado
historicamente como uno de los regimenes de funding mas altos de la historia de
BTC) pero lo perdio de vuelta en tramos posteriores donde el funding promedio
apenas superaba cero (insuficiente para cubrir fees+slippage de mantener la cesta).
### Bug real encontrado (2026-07-14): `load_funding()` devolvia settlements SIN ordenar
`data/cache/funding_bybit_{SYMBOL}.json` esta en el orden crudo de paginacion de la API
(mas reciente primero — `tools/alpha_screens.py` pagina hacia atras con `endTime`), NUNCA
ordenado. `_advance_settle_idx`/`_accrue_funding` (puntero monotono, usado por
`basis_carry.py`, `funding_extreme.py` Y `prop_swing.py` — los tres importan
`load_funding()` de `funding_extreme.py`) asumen orden ASCENDENTE: sin ordenar, el primer
elemento tiene el timestamp MAS RECIENTE, la condicion del puntero (`settlements[idx][0]
<= ts_ms`) es falsa desde el principio para cualquier fecha de backtest anterior a hoy, y
el funding NUNCA se devenga — `model_funding=True` era un no-op silencioso en las TRES
estrategias. `build_funding_signals` no se vio afectada (ordena internamente con
`sorted(rows)` para las señales), pero el DEVENGO de funding (que mueve balance real via
`adjust_balance`) si. Fix: `load_funding()` ahora hace `sorted(rows)` antes de devolver
(`strategies/funding_extreme.py`). Suite completa 271/271 tras el fix (sin regresiones).

**Impacto en EXP-011 (funding_extreme):** los numeros de A0-A3 en este documento y en
EXPERIMENTS.md fueron calculados SIN devengo de funding real — corregidos abajo.
**Impacto en `prop_swing.py`:** el bot Prop Firm que corre en PAPER en la VM
(`prop_swing_btc_usdt`, `model_funding: true`) tenia el mismo no-op — su funding
modelado nunca se aplico hasta este fix. Es papel, no capital real, pero el veredicto
CFT (`docs/prop/hyrotrader-plan.md` §15) se baso en backtests con el mismo bug; revisar
si vale la pena re-correr esos numeros aparte de esta sesion.

### Resultado corregido Via D (2026-07-14, post-fix)
`--costs bybit`, config default (`funding_min_avg=0.0`, sin ajustar — el gate no se toco):

| Metrica | Antes del fix (bug) | Despues del fix |
|---|---:|---:|
| Balance final | $9,728.36 | **$47,151.00** |
| CAGR | -0.49%/ano | **+32.0%/ano** |
| Max DD | -2.60% | **-1.09%** |
| Calmar | -0.19 | **29.36** |
| Sharpe / Sortino | -16.34 / -16.34 | **10.45 / 67.28** |

**Decision: promising, no adoptado todavia — dos caveats reales antes de considerar
paper:**
1. **Concentracion:** de los +$37,151 totales, +$16,776 (45%) vienen de UN solo tramo
   (Q2 2021), el regimen de funding mas extremo de la historia de BTC (documentado en
   `docs/prop/hyrotrader-plan.md`). El resto del historico (2022-2025, sin verse en
   detalle aun) sostiene el resultado pero no hay que extrapolar ~32%/ano como
   expectativa futura solo por este backtest — un solo evento historico domina.
2. **Riesgo de margen/liquidacion NO modelado:** el short sintetico (patron
   `prop_swing.py`) asume balance USDT ilimitado via `adjust_balance` — CERO modelo de
   margen o liquidacion. Un cash-and-carry real requiere colateral en el perp y puede
   ser liquidado en un short-squeeze violento (comun en cripto) antes de que el spot
   compense. El backtest no puede ver ese riesgo. Cualquier paso a paper/live necesitaria
   modelar esto primero, no solo pasar el gate de CAGR/DD.

### Analisis de concentracion y riesgo de margen (2026-07-14, completado)

**Concentracion — MEJOR de lo que parecia.** No es un solo trimestre con suerte: son
DOS holds largos los que explican casi todo el resultado, no uno:
1. 2020-10-22 -> 2021-06-18 (~8 meses)
2. 2022-11-10 -> 2026-01-01 (~3.1 anos, **sigue abierto** al final del backtest — el
   gate nunca se volvio a cerrar; por eso el "Resumen trimestral" del motor solo
   mostraba 9 cierres hasta 2022-11-10 y no cuadraba con el balance final $47,151:
   el 10o hold nunca se "cierra" en el journal, pero su P&L SI esta en el balance real).

**Riesgo de margen/liquidacion — PROBLEMA SERIO, no un matiz.** Se midio el peor
movimiento de precio EN CONTRA de la pata corta durante cada hold (maximo alcanzado
menos precio de entrada):

| Hold | Entrada | Maximo alcanzado | Peor movimiento vs. la pata corta |
|---|---:|---:|---:|
| 2020-10-22 -> 2021-06-18 | ~$12,769 | $64,847 (14/04/2021) | **+407.8%** |
| 2022-11-10 -> 2026-01-01 | ~$15,921 | $126,200 (06/10/2025) | **+692.7%** |
| (resto de holds, 1-4 meses) | | | +1.7% a +51.4% |

Los DOS holds que generan casi TODO el retorno son EXACTAMENTE los que habrian sufrido
movimientos de +400-700% en contra de la pata corta. En una cuenta de margen AISLADO
(isolated margin) por posicion — la configuracion default en la mayoria de exchanges —
esto es liquidacion garantizada del short mucho antes de completar el hold, sin importar
que la pata spot estuviera ganando lo mismo al mismo tiempo (el motor de riesgo del
exchange no neta automaticamente ambas patas si viven en cuentas/margenes separados).
La UNICA forma de que esta estrategia sobreviva en real es con **margen de cartera/cruzado
(portfolio margin)**, donde el exchange neta el spot largo contra el perp corto como una
sola posicion de riesgo — soportado por OKX/Binance/Bybit pero normalmente requiere
elegibilidad de cuenta y no es la config por defecto. El backtest (via `adjust_balance`
ilimitado) es estructuralmente CIEGO a este riesgo — no es que lo subestime, es que no
puede verlo en absoluto.

**Decision: sigue sin ser candidato a paper/live** — no por el resultado (el resultado es
real y explicable, no un artefacto), sino porque:
1. Requiere confirmar POR ESCRITO que la cuenta OKX destino soporta portfolio margin y que
   neta spot+perp correctamente — sin esa confirmacion, no hay caso.
2. Incluso con portfolio margin, quedan riesgos que ningun backtest puede cuantificar:
   comportamiento del motor de margen en volatilidad extrema, riesgo de contraparte/exchange,
   timing de liquidacion de funding.
3. Las mismas ventanas que generan el edge (regimenes alcistas sostenidos) son las que
   estresarian mas la pata corta — el edge y el riesgo de liquidacion NO son independientes,
   estan correlacionados por diseño.

Cerrado por ahora. Reabrir solo si: (a) se confirma portfolio margin en la cuenta real, y
(b) se decide empezar con notional muy pequeno y monitoreo activo, no con el `notional_pct=0.90`
de este backtest.

## Via E — EXP-017: Yield sobre el stable ocioso (treasury sweep, no-direccional)

Origen: derivada viva de EXP-016 (short de calendario, rechazado). El problema real que
sobrevive: durante bear_onset/accumulation el portfolio pasa ~un año con >60-80% en stable
sin devengar nada. La monetizacion correcta NO es direccional — es yield con liquidez
instantanea. Esta via NO es una estrategia de trading: es tesoreria.

### E0 — Cuantificacion del premio (HECHO 2026-07-14)
Script sobre el journal ancla v6-2 (2015-2026 realistic, $9.53M, 137 eventos):
- Stable share medio time-weighted: **32.1%** (el "80% parado" solo ocurre en las ventanas
  muertas: 2018-01→2018-12 (~358d), 2021-11→2022-10 (~360d), y la actual desde 2025-10).
- Uplift simple (sin compounding, APR sobre stable-dollar-days $2.47B):
  **APR 2% → +0.24pp CAGR | 4% → +0.47pp | 6% → +0.71pp** (+$135k/+$270k/+$405k sobre $9.53M).
- Referencia de escala: TODO el trabajo v5→v6-2 valio +0.67pp. Un yield aburrido al 4-6%
  vale lo mismo con ~0 riesgo de mercado adicional. Esa es la tesis.
- Realidad temporal: hoy el capital es paper — no hay nada ocioso REAL hasta el live
  (septiembre 2026). Deadline natural de E1-E2 = go-live, no esta semana.

### E1 — Research de producto (sin codigo, 1 sesion)
- Cuenta EEA/MiCA (`my.okx.com`), USDT bloqueado → el producto tiene que ser sobre USDC
  (o EUR como secundario).
- Inventariar OKX EU Simple Earn / flexible savings USDC: APR real historico (no el
  promocional), mecanica de redencion (instantanea vs diferida — REQUISITO DURO, ver E2),
  disponibilidad para cuentas EEA, endpoints API v5 (`/api/v5/finance/savings/*`), y si
  existe en el entorno demo (casi seguro NO → la validacion operativa sera live con
  importe minimo).
- Descalificar formalmente off-exchange (tokenized T-bills, DeFi lending): latencia de
  transferencia + lockups violan la restriccion de liquidez, y añaden counterparty nuevo.
  Documentar el porque para no reabrirlo cada ciclo.
- Riesgo: earn añade riesgo de PRODUCTO (rehypothecation) sobre el mismo counterparty que
  ya custodia el capital. Decidir cap: p.ej. max 80% del stable en earn, buffer siempre
  liquido. La decision final de producto con dinero real es de Matias (Claude no es asesor
  financiero licenciado).

### Resultados E1 (2026-07-14) — research HECHO; gate NO se cumple a rates de hoy
- **Producto EEA existe**: "EEA Simple Earn User Agreement" en okx.com/en-eu — el flexible
  se llama ahi **"Margin Reward Flexible Term"** (rebranding EEA del Simple Earn Flexible;
  los endpoints API siguen siendo `finance/savings/*`). Sin exclusiones geograficas
  intra-EEA declaradas. Fee: **15% de los returns**.
- **API confirmada en el dominio EEA**: `GET /api/v5/finance/savings/lending-rate-summary`
  responde en `my.okx.com` (verificado 2026-07-14). Existen `purchase-redempt`, `balance`,
  `set-lending-rate`, `lending-history` (privados, requieren key real — earn casi seguro
  NO existe en demo; los endpoints de finanzas no operan con `x-simulated-trading`).
- **APR real USDC hoy**: rate publicado 2.5%; `lending-rate-history` muestra el rate
  DEVENGADO real en 1.85-2.06% bruto (hourly, ultima semana) → **~1.6-1.8% neto** tras el
  15% de fee. A ese rate el uplift es ~+0.20pp CAGR → **por debajo del gate E4 (>=0.3pp /
  APR>=2%)**. Veredicto hoy: NO automatizar; sweep manual o nada. Revisar el rate real al
  go-live (septiembre) — es variable por hora y ciclico.
- **Correlacion adversa estructural** (bajar expectativas): el lending rate lo mueve la
  demanda de margen LONG → es alto en bull (cuando el allocator esta 100% BTC y no hay
  stable que prestar) y bajo en bear (cuando el stable ocioso es maximo). El estimado de
  APR constante de E0 SOBREESTIMA el uplift realizado. La cota realista esta mas cerca del
  escenario 2% que del 4-6%.
- **La redencion NO es contractualmente instantanea**: el agreement EEA permite retrasarla
  o restringirla "a discrecion de OKX" con liquidez insuficiente (FIFO, reordenable). En
  practica es instantanea, pero el contrato no lo garantiza — y los momentos de estres de
  liquidez correlacionan con los giros de mercado donde caen los BUYs grandes. Producto
  ademas NO principal-protected y FUERA del safeguarding MiCA.
- **Dato de diseño del journal ancla (weaponiza E2): 41 de 66 BUYs consumen >80% del
  stable pre-rebalanceo en UN solo evento** (53/66 consumen >50%; los saltos a target 1.00
  drenan todo). Un "buffer liquido del 20%" NO funciona: casi cualquier BUY necesita
  redimir casi todo. El diseño obligatorio es redeem-antes-de-execute en cada BUY, con
  el retraso de redencion tratado como evento de infra (alerta + ejecutar con lo liquido +
  retry del resto), nunca como skip.

### E2 — Diseño del treasury sweep (capa EXTERNA, cero cambios en swing_allocator.py)
- Restriccion estructural que manda: UN solo rebalanceo puede necesitar TODO el stable
  (target 0.20→1.00 en un giro bear→bull). Por eso la redencion instantanea es requisito
  duro, no nice-to-have.
- Pipeline: la estrategia calcula target → el sweep redime lo necesario → se ejecuta la
  orden. Orquestacion en la capa de ejecucion (`cli/live_cmds.py`); la estrategia ve el
  balance total (liquido + earn) y no sabe que el sweep existe.
- Si la redencion no es instantanea o la API no existe para EEA: v1 se degrada a sweep
  MANUAL (mensual, buffer grande). KISS: empezar manual es perfectamente aceptable; la
  automatizacion es una mejora, no un prerequisito.
- Regla de oro: el sweep NUNCA bloquea/retrasa/altera un rebalanceo. Fallo de redencion =
  alerta Telegram + rebalancear con lo liquido disponible; jamas skip.

### Resultados E2 — medicion de sensibilidad al retraso (2026-07-14) — VEREDICTO FINAL
Harness: `tools/delay_sensitivity_replay.py` (replay del journal ancla v6-2: mismas
decisiones/targets, solo cambia el precio de ejecucion a la vela N horas despues, mismos
costes realistic; el error de modelo se cancela comparando replay-0h vs replay-Nh; sanity
replay-0h vs ancla = ratio 0.9999).

| delay | lado retrasado | final $ | CAGR | dCAGR | MaxDD |
|---|---|---|---|---|---|
| 0h | — | 9.53M | 86.56% | — | 53.17% |
| 6h | solo BUYs | 7.91M | 83.44% | **-3.12pp** | 53.62% |
| 24h | solo BUYs | 7.90M | 83.41% | **-3.15pp** | 53.06% |
| 72h | solo BUYs | 7.60M | 82.76% | **-3.80pp** | 52.87% |
| 168h | solo BUYs | 7.75M | 83.09% | -3.47pp | 54.88% |
| 24h | ambos | 9.43M | 86.41% | -0.15pp | 53.21% |
| 72h | ambos | 8.78M | 85.25% | -1.31pp | 53.79% |

Lecturas (cierran la via casi entera):
1. **Parking off-exchange: MUERTO.** Retrasar solo los BUYs 24-72h cuesta **-3.2 a -3.8pp
   de CAGR** — un orden de magnitud mas que el yield que se ganaria fuera (~+0.5-1pp).
   El stable TIENE que estar liquido en el exchange cuando el bot dispara.
2. **La perdida NO es funcion de la duracion del retraso**: 6h cuesta casi lo mismo que
   72h (-3.12 vs -3.80pp) y 168h no es peor que 72h. El daño esta concentrado en unos
   pocos eventos violentos (los saltos a target 1.00 en dias de momentum): es riesgo de
   EVENTO, no de latencia acumulada. Consecuencia: hasta una redencion manual "rapida"
   (horas) de earn ya paga el coste completo → **el sweep manual tambien esta muerto**;
   solo un auto-redeem integrado en el pipeline de ejecucion (redeem→execute en el mismo
   tick) evita el coste, y eso solo se justifica si el APR pasa el gate E4.
3. **Hallazgo operativo colateral (positivo, para F19/incidentes):** retrasar AMBOS lados
   24h cuesta solo -0.15pp — una caida total del bot de ~1 dia es barata (los retrasos
   simetricos casi se cancelan por la deriva alcista). La asimetria (solo-buys) es lo
   letal. Anotado tambien como referencia para el playbook de incidentes.

**Estado de la via tras E0-E2: PARKED con una unica condicion de reapertura** — re-medir
el APR real de USDC earn al go-live (septiembre 2026). Si el neto >=2% sostenido, disenar
el auto-redeem integrado (E2/E3/E4); si no, la via se cierra y el stable se queda liquido
en el exchange, punto. Ninguna variante off-exchange ni manual se reabre: quedaron
medidas, no opinadas.

### E3 — Ensayo en paper (capa de reporting; motor congelado intacto)
- Acrecion simulada a APR fijo en el espejo paper (`paper_state`), SOLO para ensayar la
  operativa (timing sweep/redeem vs rebalanceos), no para medir retorno.
- No entra en el forward-test contract: no toca estrategia, journals de estrategia ni
  paridad F15.

### E4 — Gates de adopcion
- 0 rebalanceos retrasados/perdidos/alterados durante >=4 semanas de ensayo.
- Uplift esperado >=0.3pp CAGR al APR real observado; si el APR real es <2%, la version
  automatizada no compensa la complejidad → quedarse en manual o descartar.
- Live: importe minimo primero (septiembre), escalar despues. Mover dinero real y `start`
  live siguen requiriendo OK explicito.

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
