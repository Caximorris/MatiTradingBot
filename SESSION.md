# SESSION.md — Estado del proyecto (HOT — se carga en cada sesion via @SESSION.md)

Complemento de CLAUDE.md. **Deliberadamente corto** para no gastar tokens en cada arranque.
El detalle historico (logs de sesion, tablas de backtest, referencia por modulo, prop/Hyro,
bloques HECHO/Descartado de sesiones 12-18) vive en **`docs/archive/session-archive.md`** — leelo BAJO DEMANDA.

**Ultima actualizacion: 2026-07-14** (v6-2 congelado; fleet desplegada = v6 simulado + v6 OKX
Demo (**Prop Firm RETIRADO** ese mismo dia, ver bloque abajo); registros legacy/v5 retirados.
Fix de retry tras rebalanceo incompleto incluido. Telegram con panel persistente sin argumentos;
status CLI multi-cartera corregido. 272 tests pasan. Mas tarde el mismo dia: via "capital
ocioso" CERRADA con medicion — EXP-016 short de calendario rechazado, EXP-017 yield/treasury
parked (ver bloque CAPITAL OCIOSO abajo).)

---

## ESTADO ACTUAL

**DEFAULT VIGENTE: Swing Allocator v6-2 — CONGELADO** (decision explicita 2026-07-13).
v6-2 = v5 + phase router `v5_equiv` + funding overlay 0.05 p10/p90, TTL/dedup 7d, solo
`accumulation`. Rollback exacto a v5: `--config '{"use_phase_policy_router": false,
"use_funding_overlay": false}'`. Anclas emparejadas (dataset canonico 102931 velas):
- 2015-26 realistic: **$9.505M | CAGR +86.51% | Max DD -52.73% | 70 reb | btc_vs_bnh 0.8499**
- 2018-26 realistic: $229.0k | +47.90% | -53.72% | 53 | 0.8785
- 2015-26 conservative: $9.255M | +86.06% | -52.88% | 70 | 0.8281

Validacion local 2026-07-14: **257/257 tests**. `RiskManager.check_daily_loss` calcula ahora el
inicio del dia desde el reloj UTC real; antes usaba la fecha local y la etiquetaba como UTC.

v6 fue promovido porque v5/v6 empezaron paper simultaneamente, no existia ventaja forward previa
de v5, y v6 domina las tres anclas y 7/8 rolling starts sin empeorar DD ni churn. Hoy seguimos en
`bear_onset`: **v6 ≡ v5 en vivo hasta ~2026-10-07**. Decision usuario 2026-07-14: se retira el
registro v5; el rollback permanece documentado y su historial/wallet/estado no se borran.

**PAPER DESPLEGADO** — VM GCP e2-micro us-central1 (free tier), Debian 13, VM `matitrbot`.
Topologia deseada: exactamente `swing_allocator_v6_btc_usdt` (simulado),
`swing_allocator_demo_btc_usdt` (OKX Demo) y `prop_swing_btc_usdt` (Prop Firm simulado).
`tools/paper_fleet_setup.py` la reconcilia: elimina registros legacy/v5, desactiva otros bots
y preserva historicos, wallets y filas internas v5/v6/demo/prop. Observabilidad excluye ahora todas
las filas internas; `/status` solo muestra v6/demo y Prop sigue en `/prop`. Telegram tiene un panel
persistente de botones para consultas v6/demo/Prop sin escribir argumentos; las acciones mutables
siguen como comandos explicitos para evitar pulsaciones accidentales. Demo se etiqueta como USDC,
su rendimiento hibrido no se presenta como PnL comparable, `/audit` detecta gaps journal/cartera y
las horas operativas se renderizan en Europe/Madrid (persistencia/scheduler siguen en UTC).
Prop entra ya en snapshots/anomaly-check y su wallet inicial de 10k se persiste al arrancar.
`reconcile-demo-journal` anexa un evento auditable/idempotente para la correccion fuera de banda;
no la disfraza como BUY/SELL ni modifica la estrategia congelada.
Operacion normal = leer heartbeat + check diario; consola innecesaria. Runbook: `docs/ops/deploy-paper.md`.
Verificacion operativa en VM 2026-07-14 (antes del retiro de Prop, ver abajo): los tres bots
tenian tick reciente, la cartera Prop persistia sus 10,000 USDT iniciales, Demo fue reconciliado
de 58.0% a 19.2% BTC con un evento `RECONCILE`, y `anomaly-check` terminaba sin anomalias.
F13 (24h), F15 (30d) y F19 siguen siendo ventanas de observacion para v6/demo, no tareas de
despliegue.

**PROP FIRM RETIRADO DE LA FLEET ACTIVA (2026-07-14, mas tarde el mismo dia).** Bug real
encontrado en `load_funding()` (settlements de funding sin ordenar — cache en orden de
paginacion API, mas reciente primero): el puntero monotono de `_advance_settle_idx`/
`_accrue_funding` nunca avanzaba, asi que `model_funding=True` era un no-op silencioso en
`prop_swing.py`, `funding_extreme.py` Y el nuevo `basis_carry.py` (donde se descubrio). Fix
de una linea en `strategies/funding_extreme.py:load_funding` (`sorted(rows)`), 272/272 tests.
Re-corrida la simulacion de reglas CFT que promovio a Prop como "candidato vivo"
(`entry_halving_phases=bear_onset,accumulation`, r1.8/n0.8, `bybit_cons`, 2020-26): **pass
45.4% (era 74.8%), breach 14.8% (era 2.0%)** — YA NO cumple el gate de adopcion (>=60% pass).
`tools/paper_fleet_setup.py` ya no incluye `prop_swing_btc_usdt` en `desired_fleet()`.
**Accion pendiente en la VM:** tras el proximo `git pull`, correr
`.venv/bin/python tools/paper_fleet_setup.py` + `sudo systemctl restart matibot` para
desactivar el bot (BotState/wallet/journal se preservan, no se borran — igual que v5).
Sin ese paso manual, el pull + restart normal NO lo desactiva por si solo. Pendiente tambien
verificar en la VM si el bot mantuvo algun short (regimen bear, `allow_shorts=true`) desde su
despliegue (2026-07-11) — de ser asi, su equity/DD registrados en ese tramo no reflejan
funding real. Detalle completo: `docs/prop/hyrotrader-plan.md`, `EXPERIMENTS.md` EXP-010/013,
`docs/income/plan.md` Via D.

**OBSERVABILIDAD FORWARD-TEST (2026-07-06)** — suite read-only que NO toca la estrategia (plan
`docs/forward-test/research-lab-plan.md`, fases 1-3). Reglas del test congeladas en
`docs/forward-test/contract.md` (inicio 2026-07-04, taxonomia fallo-estrategia vs fallo-infra).
Comandos: `paper-status` (control center v6/demo/prop), `anomaly-check` (red-flags + Telegram
dedup), `forward-report` (solo datos post-inicio, filtro duro), `data-audit` (integridad OHLCV,
nunca re-descarga). Capa pura: `tools/{paper_snapshot,anomaly_check,forward_report,data_audit}.py`
+ `cli/paper_cmds.py`. **Hallazgo de `data-audit`:** cache canonico tiene 474 filas duplicadas
benignas (identico OHLCV) en el empalme 2017 → 102457 distintas de 102931; NO deduplicar en
forward-test (mutacion de cache prohibida, ver CLAUDE.md). La suite completa pasa en dev
(257 tests); en la VM se verifican los artefactos y heartbeats, porque sus datos runtime no se
versionan.

**SEMANA 1 DEL FORWARD-TEST (revision 2026-07-11)** — v5/legacy y v6 sanos (ambos target 0.20,
señales identicas `regime_bear,halving_bear_onset`, paridad OK). Dos bugs de INFRA (contrato 6b,
no invalidan la estrategia) encontrados via Telegram+SSH y arreglados:
1. `deploy/daily_checks.sh` perdio el bit +x en el commit `2019859` → el cron fallo EN SILENCIO
   5 dias (2026-07-07→11); `/parity` seguia verde porque solo miraba el ultimo resultado, no su
   antiguedad. Fix `973d433` (+x en git) + deteccion `daily-check-stale` en anomaly_check +
   `/parity` ahora avisa VIEJO. La racha F15 se reinicia ~2026-07-11 (5 dias sin medir).
2. `registry.resolve()` casaba por prefijo sin limite de palabra: `prop_swing_btc_usdt` resolvia
   a **pro_trend** (alias corto `pro`) → el bot "prop" corrio 5 dias como Pro Trend v13 con
   config default (0 trades, cero daño, verificado en DB). Fix `4b1425f` (limite `_` + match mas
   largo + tests). Re-arrancado como PropSwing real el 2026-07-11.
Ademas: `/audit` en Telegram (mismo motor que `anomaly-check`), `main.py explain` (T5.1),
`EXPERIMENTS.md` (T11.1) — todo en `7107631` (SIN PUSH). Suite observabilidad corrida EN la VM
por primera vez: limpia (los 474 dups del cache = hallazgo conocido, no accion).

**CLIENTE OKX DEMO TRADING (desplegado 2026-07-13; verificado 2026-07-14).** Objetivo:
ejercitar por PRIMERA vez el camino de ordenes autenticado real de OKX antes del live de
septiembre 2026. `core/okx_demo_client.py` (hibrido: market data REAL flag=0 → paridad F15
intacta; ordenes/balance DEMO flag=1 con credenciales `OKX_DEMO_*`), `tools/okx_demo_setup.py`
(registro original con flags v6 desactivados; `main` actual fija v6-2 + `execution=okx_demo`),
routing en `cli/live_cmds.py` (fallo de credenciales = skip solo ese bot). Espejo de balances en
`paper_state_okx_demo.json` → Telegram `/status demo` etc. funcionan sin cambios. 12 tests nuevos
(257 tests totales). MEDIDO 2026-07-11: el feed de precios demo tiene high/low inflados $80-250/vela 1H →
NUNCA usar flag=1 para market data (confirma la regla de CLAUDE.md con datos).
El hallazgo P1 de `tgtCcy` quedó corregido el 2026-07-13 en `OKXClient` y cubierto por
`tests/test_exchange.py`; la API key demo se crea DENTRO del modo demo trading de OKX (la real
NO vale).

**PRUEBAS DEMO EN DEV (2026-07-13) — cuenta EEA/MiCA, hallazgos CRITICOS:**
- La cuenta de Matias es de la entidad europea: API en `https://my.okx.com` (keys EEA dan 60032
  contra www.okx.com). Nuevo `OKX_DEMO_DOMAIN` en settings/cliente. Feed de señales sigue global.
- **BTC-USDT y BTC-USD = sCode 51155 bloqueados por compliance (MiCA)** en su cuenta. El bot demo
  registrado como BTC-USDT NO puede operar: hace falta mapeo señal(BTC-USDT)→ejecucion(BTC-USDC
  o BTC-EUR). Fondos demo EEA: USDC/EUR/USD/XRP/ETH — CERO USDT.
- BTC-USDC permitido: BUY market OK (tgtCcy verificado contra API real). SELLs cancelados por el
  motor: book demo USDC casi muerto (top bid 59475 < banda minima de venta 51138 @59517).
  BTC-EUR funciona completo (sell filled + fee EUR). Precios demo divergen ~5% del real.
- 2 bugs del cliente arreglados con las pruebas: (a) errores code=1 ahora exponen sCode/sMsg;
  (b) fill fantasma — market aceptada (sCode=0) y luego `state=canceled` sin fill se reportaba
  como filled; ahora `_query_order` mira `state` y reporta rejected/qty real. Tests 215/215.
- Verificado contra API real: auth, balance, espejo, buy market, limit+cancel, sell market (EUR).
- **Mapeo señal→ejecucion IMPLEMENTADO** (decision Matias 2026-07-13: ejecutar en USDC — fees
  identicas a EUR pero spread real 0.02 vs 0.27 bps y misma unidad de cuenta que el backtest;
  conversion a EUR solo al retirar). `OKXDemoClient(exec_quote="USDC")`: ordenes/consultas *-USDT
  → *-USDC, balance USDC presentado como USDT; la estrategia y /status siguen en espacio USDT.
  Config del bot: `execution_quote: "USDC"` en okx_demo_setup.py, enrutado en live_cmds.py.
  Verificado E2E contra la API demo real: BUY "BTC-USDT" → fill real en BTC-USDC (219-test
  historical checkpoint; current suite 257/257).
- **DESPLEGADO EN VM 2026-07-13 ~14:36 UTC.** Primer tick: INIT BUY 0.096 BTC filled; el SELL
  a target 0.20 lo cancelo el motor (book demo USDC con bids bajo la banda 51138) → **bridge EUR
  implementado** (`execution_bridge: "EUR"`): market cancelada por el motor se reintenta en 2
  patas BTC↔EUR↔USDC (books demo EUR vivos). Verificado E2E real: sell 0.001 via bridge OK.
  Cuenta demo saneada: cartera del bot = BTC+USDC ~10k; resto aparcado en XRP (120k), USD 5k,
  ETH 1 (inertes, el bot los ignora). OJO VM: `matibot-telegram` es servicio SEPARADO — hay que
  reiniciarlo tras cada pull o /bots y las etiquetas de alertas quedan con codigo viejo (visto:
  alertas del demo salian como "[legacy]" y /status demo no existia). Precios del motor demo
  divergen ~5% del feed real (fills ~59.4k vs real 62.5k): el equity del espejo mezcla fills
  demo con valoracion real — distorsion conocida, no es PnL. La limpieza de legacy/v5 se aplicó
  con `paper_fleet_setup.py`; solo quedan los tres bots operables y sus carteras aisladas.

**Pro Trend v13 — PAUSADO INDEFINIDAMENTE** (decision sesion 14). Codigo congelado y reversible,
fuera del roadmap activo. Framework de validacion estaba completo. Detalle en archive.

**CAPITAL OCIOSO EN BEAR (2026-07-14) — VIA CERRADA CON MEDICION.** Pregunta: ¿como aprovechar
el ~80% stable parado durante bear_onset/accumulation? Respuestas, todas medidas (detalle en
`docs/income/plan.md` Via E + EXP-016/017):
- Short de calendario en bear_onset: **rechazado en fase de idea** (EXP-016) — circular (el
  "patron" es la propia regla del allocator), n=3, funding era no-op hasta el fix, liquidacion.
- Yield on-exchange (OKX "Margin Reward"/Simple Earn EEA): rate real hoy ~1.6-1.8% neto →
  +0.20pp CAGR, NO pasa el gate. **Parked con una sola llave de reapertura: re-medir APR al
  go-live (sept 2026); si neto >=2% sostenido, disenar auto-redeem integrado.**
- Parking off-exchange y sweep manual: **muertos** — `tools/delay_sensitivity_replay.py` midio
  que retrasar solo los BUYs cuesta -3.1 a -3.8pp CAGR (6h ≈ 72h: riesgo de EVENTO en los
  saltos a target 1.00, no de duracion). 41/66 BUYs consumen >80% del stable en un evento.
- **Colateral operativo (para incidentes/F19):** retrasar AMBOS lados 24h cuesta solo -0.15pp
  → una caida total del bot ~1 dia es barata; lo letal es la asimetria (vender si, comprar no).

---

## REGLAS INVARIANTES ANTES DE TOCAR CODIGO

Prioridad sobre cualquier optimizacion. Un cambio que no las cumpla NO pasa a default aunque mejore
un backtest puntual.

### 1. Lookahead bias — tolerancia cero
- Dato diario/semanal/4H usado intradia debe estar CERRADO antes del tick. No usar vela/semana/bloque
  4H en curso.
- Externos con offset conservador: MVRV/CoinMetrics = dia anterior; DXY/NDX/VIX/Yahoo = sesion anterior;
  Funding OKX = dia completo anterior.
- Indicador nuevo: documentar en codigo que timestamp representa y por que no mira futuro. Ante duda,
  asumir que el dato NO estaba disponible y desplazarlo.

### 2. Overfitting — protocolo obligatorio
- No promover un cambio que solo mejora 2018-2026 o que elimina un unico trade perdedor.
- Ventana principal BTC: **2015-01-01 a 2026-01-01** (mas trades, 3 ciclos). 2018-2026 = secundaria.
- Comparar candidatos por **CAGR y Max DD** (anclas estables); PF como rango, NO como ancla (es fragil
  al punto de inicio). Fijar siempre inicio 2015.
- Cada cambio se testea AISLADO contra baseline y luego combinado solo si aporta por separado.
- Coste minimo `--costs realistic`; candidatos finales tambien `conservative`.
- Threshold nuevo necesita justificacion ESTRUCTURAL, no "porque arregla T6/T8/T9".
- Si sube CAGR pero empeora mucho PF/MaxDD → variante agresiva, no default.

### 3. Preservar rollbacks
- No sobrescribir ni borrar journals existentes. Todo cambio nuevo debe ser reversible por config.
- Rollback conceptual Pro Trend v13: `partial_exit_pct=150.0`, `partial_exit_size=0.33`,
  `entry_score_min=9`, `adx_min_entry=15.0`, `trailing_stop_pct=0.22`, `trailing_stop_pct_bull=0.28`,
  `cooldown_atr_stop_days=30`, `macd_exit_enabled=False`, `allow_shorts=False`,
  `disable_external_filters=False`.
- Swing v1/v2 config exactas: ver "SWING ALLOCATOR — REFERENCIA" en docs/archive/session-archive.md.

### 5. Out-of-sample — ventana 2015-2026 CERRADA para optimizacion (auditoria 2026-07-02)
- Ningun cambio futuro de estrategia se adopta por mejorar 2015-2026. Esa ventana solo se usa para MEDIR
  robustez/sensibilidad de lo ya adoptado. La evidencia para cambios futuros = datos posteriores a
  2026-01-01 (forward/paper) o justificacion estructural pura + no-empeora-anclas.
- Excepcion permitida: SIMPLIFICACION (quitar componentes) si no empeora las anclas.
- Excepcion ya consumida: v6-2, aprobada explicitamente por el usuario el 2026-07-13 porque v5 y
  v6 iniciaron paper a la vez, v6 paso todas las pruebas disponibles y el cambio de default no
  autoriza live. No usar este precedente para promover v7 u otros thresholds sobre muestra cerrada.

### 4. Determinismo de datos
- Backtests deterministas via cache OHLCV (`data/cache/`). Runs con rango cacheado = velas identicas.
- Resultado SENSIBLE al punto de inicio (dataset canonico: 102931 velas; viejo 96906). El cache OHLCV
  esta VERSIONADO en git (restaurable con `git checkout`). Las herramientas de reporte clampan al rango
  del cache y NO re-descargan (incidente 2026-07-06 restaurado, ver nota CLAUDE.md). No mezclar caches
  entre maquinas.
- Backtests CONTINUOS — nunca reiniciar balance en frontera de año/mes.

---

## LABORATORIO DE INVESTIGACION Y HARDENING (2026-07-15)

- Se incorporo el ecosistema Codex de 14 especialistas y 15 skills cuantitativas; el mapa de
  autoridad, gates y workflows esta en `docs/research/subagent-ecosystem.md`. No cambia ninguna
  hipotesis, parametro ni default de estrategia.
- El backtest ahora falla cerrado en la primera excepcion de estrategia, cierra la sesion SQL,
  alinea `cancel_order(order_id, symbol)` entre clientes y reserva principal+fee en BUY limits.
  `get_balance()` expone saldo disponible; la valoracion interna conserva reservas como activo.
- `funding_context.py` conserva snapshots OKX inmutables por simbolo/ventana, rechaza conflictos,
  evita contaminacion entre activos/runs y solo se carga para Pro Trend. Es distinto del cache
  Bybit usado por Swing v6.
- Cada backtest exitoso escribe un manifest determinista en `backtests/manifests/`: revision/diff
  git, entorno, config resuelta, costes/fills, OHLCV ordenado (incluidos duplicados/warmup),
  metricas, equity/trades, artefactos y inputs externos. El cache Bybit ignorado por git queda
  identificado por ruta, presencia, tamano y SHA-256; un fallo de manifest invalida el run.
- CI cubre Python 3.12/3.13, dependencias, entrypoint, compile, 321 tests, build y un ratchet Ruff.
  El backend/entrypoint de packaging quedaron corregidos. Ruff conserva visibles 207 hallazgos
  frente al baseline versionado de 209; deuda nueva o mayor falla CI.
- Paridad Swing ejecutada con el cache local sin modificar: 102,930 barras de entrada / 96,930
  de test, realistic, $9,532,749.59, CAGR 86.56%, Max DD -52.73%, 70 rebalanceos y ratio BTC
  0.8499. Coincide con el control documentado **sin overlay** ($9.53M), no con el ancla v6
  $9.505M: el input Bybit local (SHA-256
  `23cc1952a9eed3806fb6f91e9cfdd788d0ae1dcfcc244524ea3f904b4497685f`) no reproduce el overlay
  canonico. No atribuir esta diferencia al motor ni promover resultados hasta restaurar el input
  exacto. `anomaly-check` y `/audit` ahora elevan cache ausente/stale como HIGH en vez de degradar
  sin visibilidad.
- Validacion local: `python -m pytest -q` = 321 passed; `compileall` = OK; `python -m build` = OK;
  `python tools/ruff_ratchet.py` = OK (207/209). El host actual usa Python 3.14.6 y no puede hacer
  `pip install -e ".[dev]"` porque el numba fijado por pandas-ta soporta `<3.14`; el contrato real
  del paquete y CI se limitaron honestamente a `>=3.12,<3.14`.
- Rollback: revertir los archivos de infraestructura/tests de este bloque y eliminar el hook de
  manifest/CI. No borrar manifests ni journals generados, no regenerar caches y no tocar los
  defaults congelados como parte del rollback.

---

## SIGUIENTE PASO (sesion 2026-07-14+)

El despliegue, la limpieza de fleet y la reconciliacion Demo ya estan completados. Prop se
retiro el mismo dia (ver bloque arriba) — **pendiente correr `paper_fleet_setup.py` en la VM**.
El siguiente trabajo es observacion de v6/demo, no otra migracion:
1. Confirmar el retiro de Prop en la VM (pull + `paper_fleet_setup.py` + restart), luego dejar
   correr v6 simulado + v6 Demo y revisar `main.py status`, Telegram `/audit` y el heartbeat diario.
2. Cerrar F13 (24h), F15 (30d) y F19 con sus ventanas completas; una semana sin trades no es
   una alerta por si misma para un allocator de 2–3 rebalanceos mensuales.
3. Resolver la frescura del cache de funding antes de `accumulation` (~2026-10-07); si sigue
   stale, v6 degrada silenciosamente a v5 y PropSwing modela funding=0.

**Marco general:** optimizacion de backtest del Swing = CERRADA. Hito = validacion forward:
cerrar F13 (smoke 24h), F15 (paridad 30d — racha reiniciada ~2026-07-11 por el incidente cron)
y F19 (degradacion). Bot demo = ensayo del camino de ordenes real pre-live; sus fills a precio
demo NO se comparan con los paper (distorsion ~5% conocida del motor demo). Live real planeado
para SEPTIEMBRE 2026 (`start` live requiere confirmacion explicita; el mapeo USDC y el dominio
`my.okx.com` ya estan implementados en el cliente demo, pero live sigue sin autorizacion). El paper
v5-vs-v6 empieza a dar señal desde ~2026-10-07.

---

## PENDIENTES ABIERTOS (todos cerrados/parqueados — NO reabrir sin evidencia nueva)

- **Max DD Swing (-52.73%):** frente CERRADO (sesion 15). Suelo estructural; nace en bull_peak y
  accumulation/COVID, NO en bear_onset. Todo lever probado agota CAGR o es inerte.
- **Q4 2025 ping-pong:** residual estructural, sin via viva. Descartados cooldown=7d, ADX gate,
  cap-bear_onset. Detalle en archive.
- **Pro Trend bugfixes candidatos** (P1, sin backtest aislado): fix MACD 4H key, fix VIX sizing cap.
- **`tgtCcy` en `OKXClient._live_place_order`:** ARREGLADO 2026-07-13 (market orders fijan
  `tgtCcy=base_ccy`, igual que el cliente demo; tests en `test_exchange.py`). Ya no bloquea live.
- **Funding Bybit 403 en la VM:** `funding_refresh.py` falla con HTTP 403 (IP de GCP bloqueada?).
  Sin urgencia hasta fase `accumulation` (~2026-10-07): sin ese cache, v6 degrada a v5 en silencio
  y PropSwing modela funding=0. Resolver antes de octubre. Desde 2026-07-15 `anomaly-check` y
  `/audit` lo reportan HIGH si falta o supera 26h, pero el 403 remoto sigue sin resolver.
- **Limpieza/refactor de codigo:** backlog en `docs/archive/refactor-backlog.md`. Difiere al cierre del paper
  (no romper determinismo/paridad). (El codigo muerto `execution/order_manager.py` +
  `position_tracker.py` ya se borro en `5ec7a97`, 2026-07-06.)
- **Re-medir APR de earn USDC al go-live (sept 2026):** unica llave de reapertura de EXP-017
  (yield sobre stable ocioso). Si neto >=2% sostenido → disenar auto-redeem integrado; si no,
  el stable se queda liquido en el exchange y la via se cierra del todo.
- **Descartado y NO reintentar:** latch del cap, regime_delta 0.15, VIX, MVRV, Pi Cycle, floor<0.20,
  global max_btc_pct cap, ATR intradia, halving_only, clock_aligned_cadence, fill_next_open,
  short de calendario en bear_onset (EXP-016), parking off-exchange del stable y sweep manual
  de earn (EXP-017, medidos con `delay_sensitivity_replay.py`).

---

## PUNTEROS A REFERENCIA (leer bajo demanda, NO precargar)

- `docs/handoff.md` — doc principal para continuar en otro PC (branch, setup, estado operativo,
  Prop/CFT, Swing v6, tests, siguientes pasos).
- `docs/ops/deploy-paper.md` — runbook y estado del despliegue paper en la VM.
- `docs/forward-test/contract.md` — reglas CONGELADAS del forward-test (inicio, variantes, fallo
  estrategia vs infra, playbook de incidentes). Citarlo por seccion en los reportes.
- `docs/forward-test/research-lab-plan.md` — roadmap del laboratorio de investigacion +
  monitorizacion (fases 0-6, tracking con checkboxes; fase 1-3 parcialmente HECHAS).
- `docs/swing/v6-plan.md` — plan v6 (phase router + funding overlay; criterios de promocion Fase 4).
- `docs/swing/plan.md` — diseño del Swing. `docs/swing/audits.md` — auditorias v4/v5 + plan de
  mejora F1-F19 (consolidado de los antiguos AUDITORIA_SWING_V4/V5 y PLAN_MEJORA_AUDITORIA).
- `docs/prop/hyrotrader-plan.md` — estrategia prop firm (Bybit/CFT/Hyro). Estado: motor `funding_extreme` da
  edge standalone real (PF 1.44, DD 13%) pero RECHAZADO como prop (gate two-step ~27% pass / 37%
  breach vs >=60%/<=20%). Router CFT-only (`entry_halving_phases=bear_onset,accumulation`) es el mejor
  candidato pero requiere validar reglas reales CFT/Match/MT5 — sin confirmacion escrita, NO comprar.
- `docs/archive/session-archive.md` — logs sesiones 12-18, auditorias, resultados backtest, referencia por modulo,
  detalle prop/Hyro, bloques HECHO/Descartado migrados.
- `backtests/STRATEGY_VERSIONS.md` — historial de versiones.
- Journals: NO hacer `Read` del JSON crudo (>10 MB). Usar `python tools/journal_summary.py <ruta>`
  o `/journal-summary`.

---

## DONDE ESTA CADA COSA (referencia rapida)

- Estrategias: `strategies/pro_trend.py`, `swing_allocator.py`, `adaptive_trend.py`,
  `scalp_momentum.py`, `prop_swing.py`, `funding_extreme.py`. Indicadores: `strategies/indicators.py`.
- Contexto externo: `macro_context.py` (MVRV+halving), `market_context.py` (DXY/NDX/VIX),
  `funding_context.py`. Overlay v6: `swing_funding_overlay.py`.
- Backtest: `core/backtest.py`. Cache: `data/ohlcv_cache.py`. Prop: `core/prop_rules.py`,
  `core/cft_monitor.py`. Journals: `reporting/trade_journal.py`, `reporting/swing_journal.py`.
- Ejecucion: `core/exchange.py` (OKXClient real/paper local), `core/okx_demo_client.py` (hibrido
  demo OKX: data real + ordenes demo). Registro de experimentos: `EXPERIMENTS.md` (raiz).
- Umbrales y config detallada de cada modulo: docs/archive/session-archive.md.
