# MatiTradingBot — AGENTS.md

Bot de trading automatizado para OKX. Python 3.12 o 3.13. Windows 10, PowerShell.
Leer este archivo Y `SESSION.md` antes de tocar cualquier archivo.

---

## CONTRATO OPERATIVO

Este archivo es un contrato de ejecucion para Codex, no un README. Priorizar acciones
reproducibles y evidencia sobre explicaciones genericas. Antes de usar un comando,
confirmar que existe en el repositorio y que no cambia estado externo. Si una instruccion
de aqui contradice el estado vivo de `SESSION.md`, prevalece `SESSION.md` para el estado
operativo y este archivo para el procedimiento general.

Reglas de trabajo por defecto:

- Inspeccionar antes de editar: `git status`, el archivo objetivo, sus tests y sus
  consumidores directos.
- Hacer el cambio minimo mantenible, conservar rollbacks y no ampliar el alcance sin
  evidencia.
- Preferir comandos no interactivos y PowerShell valido para Windows.
- No declarar una tarea terminada solo porque un test pasa: revisar tambien el diff,
  seguridad, determinismo, efectos secundarios y criterios de aceptacion.
- En informes, separar hechos observados (`[Certain]`), inferencias (`[Likely]`) e
  incertidumbres (`[Guessing]`).

## POLITICA DE TRABAJO AUTONOMO

Codex puede, dentro del alcance de la tarea:

- inspeccionar el repositorio completo, respetando la regla de no leer journals crudos;
- crear ramas y worktrees;
- modificar codigo, documentacion y tests;
- instalar dependencias de desarrollo cuando exista una razon verificable;
- ejecutar builds, tests, linters, backtests offline y servicios locales;
- crear commits atomicos;
- publicar una rama y abrir un pull request en modo draft cuando la tarea pida esa entrega.

Codex no puede:

- hacer push directo a `main`, hacer merge ni borrar ramas protegidas;
- desplegar en produccion, entrar por SSH a la VM o reiniciar servicios remotos;
- modificar, imprimir, copiar o commitear secretos, tokens, claves privadas o `.env`;
- ejecutar migraciones destructivas, borrar datos, resetear wallets o editar la DB runtime
  directamente;
- debilitar autenticacion, autorizacion, validacion, limites de riesgo o controles de
  lookahead para conseguir un resultado verde;
- silenciar tests, warnings de seguridad o fallos de integridad;
- cambiar el dataset canonico, journals historicos o resultados para hacer coincidir una
  expectativa.

Las acciones autonomas terminan en el repositorio local y en servicios locales salvo que
la tarea autorice expresamente otra cosa. Crear un commit no autoriza hacer push; abrir un
draft PR requiere que la tarea incluya publicacion.

## ARQUITECTURA Y LIMITES

No existe un frontend web separado actualmente. La frontera de interfaz es:

- **Interfaz:** `main.py`, `cli/`, `tools/telegram_remote.py`, `tools/prop_telegram.py`
  y dashboards/reportes. Parsean comandos, muestran estado y delegan en servicios;
  no deben contener reglas nuevas de estrategia ni secretos embebidos.
- **Backend de dominio y aplicacion:** `strategies/` decide senales/asignaciones;
  `core/` contiene contratos de cliente, backtest, riesgo, persistencia y ejecucion.
  Una estrategia debe funcionar contra `BacktestClient`, `OKXClient` y
  `OKXDemoClient` mediante el mismo contrato, sin saber si el entorno es backtest, paper,
  demo o live.
- **Datos e integraciones:** `data/` y los clientes/contextos externos obtienen y
  normalizan OHLCV, funding y contexto macro/mercado. Toda red usa `aiohttp` o
  `urllib.request`; no introducir `requests`.
- **Persistencia y reporting:** `core/database.py`, `trading.db` y `reporting/` guardan
  o presentan estado. Reporting puede leer y resumir, pero no debe cambiar decisiones de
  estrategia ni reescribir historiales.
- **Infraestructura:** `deploy/`, systemd, cron, la VM GCP y credenciales externas.
  Los tests locales no deben depender de la VM ni mutarla. Un cambio en infraestructura
  debe incluir runbook, rollback y comprobacion de salud.

Direccion de dependencias: interfaz -> aplicacion/core -> estrategias y adaptadores de
datos; `deploy/` queda fuera del dominio. No importar secretos, comandos de despliegue o
detalles de Telegram desde una estrategia. Si se incorpora un frontend futuro, debe vivir
en un modulo propio y llamar a servicios de aplicacion, nunca a SQL/runtime directamente.

---

## SISTEMA MULTI-AGENTE DE INVESTIGACION

Para solicitudes cuantitativas amplias, ambiguas o con varias puertas de validacion, el
agente raiz debe usar `$quant-orchestrate-research` y delegar directamente en los especialistas
de `.codex/agents/`. El mapa operativo y los workflows viven en
`docs/research/subagent-ecosystem.md` y en
`.codex/skills/quant-orchestrate-research/references/skill-map.md`.

Reglas de orquestacion:

- El agente raiz conserva la decision, selecciona el minimo de especialistas y sintetiza;
  no delegar recursivamente por defecto.
- Paralelizar solo auditorias/analisis independientes y de lectura. Maximo un agente escritor
  a la vez; ningun implementador certifica su propio trabajo.
- Datos, ejecucion, backtest, riesgo, robustez y calidad de codigo son puertas distintas.
  Un veredicto invalido o bloqueado no puede ser suavizado por el orquestador ni por reporting.
- `experiment-operator` ejecuta matrices congeladas; `robustness-statistician` las disena y
  emite el veredicto de generalizacion; `evidence-curator` preserva y comunica la evidencia.
- Cambios de estrategia van a `strategy-engineer`; infraestructura de research/backtest va a
  `research-systems-engineer`. Ambos requieren revision independiente.
- No crear agentes por cada indicador, arquetipo de estrategia, fee o tipo de grafico. Usar los
  especialistas persistentes y pasarles un encargo acotado.

---

## Available model tiers

Last verified: 2026-07-14. Use the selector values for the tool currently running:

- Current lightweight model — Codex: `GPT-5.6 Luna` (`gpt-5.6-luna`); Claude Code: `haiku`
- Standard development model — Codex: `GPT-5.6 Terra` (`gpt-5.6-terra`); Claude Code: `sonnet`
- Strongest reasoning model — Codex: `GPT-5.6 Sol` (`gpt-5.6-sol`); Claude Code: `fable`
- Claude Code high-capability model: `opus` (use when `fable` is unavailable)

In Claude Code, these aliases select the latest available model in each family: Haiku,
Sonnet, Opus, and Fable. In Codex, use the exact display names above. Luna is for
low-risk, repetitive work; Terra is the default for normal development; Sol is for
complex reasoning and high-risk work. If a selector no longer offers one of these
values, inspect the current selector and update this section before relying on it.

## Model routing and escalation protocol

This gate applies to every request: questions, analysis, reviews, planning, diagnostics,
backtests, and implementation. Before substantive work, classify the task and announce the
recommended model. The user changes the selector manually.

Use this routing:

- **Luna** (`GPT-5.6 Luna`, `gpt-5.6-luna`; Claude Code: `haiku`): explanations, documentation,
  extraction, classification, structured summaries, formatting, renaming, and isolated
  mechanical edits.
- **Terra** (`GPT-5.6 Terra`, `gpt-5.6-terra`; Claude Code: `sonnet`): multi-file changes,
  normal production features, tests, business-logic debugging, limited refactors, and tasks
  with several related files.
- **Sol** (`GPT-5.6 Sol`, `gpt-5.6-sol`; Claude Code: `fable`, or `opus` if unavailable):
  architecture, security, authentication or permissions,
  database migrations, concurrency, transactions, caching, queues, distributed state,
  infrastructure, deployment, CI/CD, networking, broad audits, data-loss risk, ambiguous
  requirements, or an unclear root cause.

Use the selector syntax for the active tool: Codex display names/IDs for Codex, and the Claude
Code aliases above for Claude Code. If an alias is unavailable, use the closest exact model name
shown by that tool's selector.

At the beginning of every response, before doing the work, state:

```text
MODEL ROUTING: <recommended selector value>
Reason: <one concise reason>
```

If the current model is below the recommended tier, stop immediately after classification and
use the exact escalation format below. Do not inspect project files, run tests or backtests,
edit files, commit, push, deploy, or continue the task. If the current model is not visible,
still recommend the required selector value without pretending to know the current selection.

When uncertain between tiers, choose the higher tier. Do not escalate merely because a task is
long; escalate based on reasoning difficulty, ambiguity, blast radius, reversibility, security
impact, and the likelihood of incorrect architectural assumptions.

### Mandatory behavior when escalation is needed

When the current model is below the recommended tier:

1. Do not modify files.
2. Do not run destructive commands.
3. You may perform only the minimum read-only inspection needed to classify the task.
4. Stop immediately after classification.
5. State exactly which model should be selected, using the real selector value for the
   current tool (`GPT-5.6 Terra`/`GPT-5.6 Sol` in Codex or `sonnet`/`opus`/`fable` in
   Claude Code).
6. Produce a complete replacement prompt that I can paste into a new thread.
7. Include all relevant context discovered during the read-only inspection.
8. Do not merely suggest using another model and then continue the task.

Use this exact response structure:

MODEL ESCALATION REQUIRED

Recommended model: <exact model name>

Reason:
<brief explanation of the complexity, risk, or ambiguity>

Replacement prompt:

```text
<self-contained prompt ready to paste into a new thread>
```

The replacement prompt must include:

- The exact objective.
- Relevant repository and architecture context.
- Files or directories likely involved.
- Constraints from this AGENTS.md.
- What has already been inspected.
- Required implementation steps.
- Validation commands and acceptance criteria.
- Risks and edge cases.
- An instruction to inspect before editing.
- An instruction not to commit, push, deploy, or modify production resources unless
  explicitly requested.

## Do not split cohesive implementation work unnecessarily

If the current task is already in progress and changing models would lose important
context, stop and generate a handoff prompt containing:

- The original request.
- Current findings.
- Files inspected.
- Files modified.
- Commands executed.
- Test results.
- Unresolved questions.
- The exact next step.

Never assume the next thread can see this thread's conversation history.



## STACK Y ESTRUCTURA

**No usar `requests`** — usar `urllib.request` (HTTP sincrono) o `aiohttp` (async).

Directorio raiz: `C:\Users\Matias\Documents\Mati\matiproyects\MatiTradingBot\`

Archivos clave:
- `main.py` — CLI typer (todos los comandos)
- `core/backtest.py` — BacktestClient + BacktestEngine
- `strategies/pro_trend.py` — estrategia principal
- `strategies/swing_allocator.py` — Swing Allocator v6-2 DEFAULT actual (congelado)
- `strategies/indicators.py` — UNICO modulo de indicadores activo (`data/indicators.py` es el antiguo, ignorar)
- `strategies/macro_context.py` — MVRV + halving (CoinMetrics API)
- `strategies/market_context.py` — DXY + NASDAQ + VIX (Yahoo Finance)
- `strategies/funding_context.py` — funding rate historico OKX
- `reporting/swing_journal.py` — journal de rebalanceos Swing
- `docs/swing/plan.md` — diseno y validacion Swing
- `backtests/STRATEGY_VERSIONS.md` — registro de versiones y descartes

Archivos eliminados (no buscar): `strategies/mean_reversion.py`, `strategies/signal_follower.py`

---

## CONVENCIONES CRITICAS

- Importes monetarios: `Decimal`, NUNCA `float`
- Fechas en DB: UTC siempre. Conversion a Europe/Madrid SOLO en reporting
- Paper mode por defecto. `TRADING_MODE=live` requiere confirmacion explicita
- Logs con `loguru`. Nunca `print()` para logs
- `OrderResult` siempre requiere `size` y `limit_price` — no omitir (errores silenciosos)
- Backtests CONTINUOS — nunca reiniciar balance en frontera de año/mes
- Backtests DETERMINISTAS: `data/cache/{symbol}_{bar}.json` cachea OHLCV. Misma ventana debe dar mismo conteo de velas.
- Maximo 800 lineas por archivo
- `transient=True` en Rich Progress. Evitar Unicode en Windows (cp1252)

---

## REGLAS DE COMPORTAMIENTO

1. **Backtests: SI ejecutar automaticamente** si el usuario pide analizar/validar estrategia.
   Maximo 5 en paralelo, siempre reportar resultados. Live/paper (`python main.py start ...`) requiere confirmacion explicita.

2. **No tocar parametros de Pro Trend** hasta completar paper trading 6 meses. Foco actual: Swing Allocator.

3. **Lookahead fixes aplicados — no revertir:**
   - `macro_context._lookup`: offset empieza en 1 (MVRV = dia anterior)
   - `market_context._spot/_pct`: delta empieza en 1 (VIX/DXY/NDX = sesion anterior)
   - `pro_trend._build_4h_context`: excluye bloque 4H actual incompleto
   - `funding_context.get_funding_rate_at`: delta empieza en 1 (dia completo anterior)
   - `backtest._fill_market`: usa `self._fee_rate` y `self._slippage_bps` (configurable)

4. **MACD exit DESACTIVADO** (`macd_exit_enabled=False`). No reactivar sin justificacion backtest.

5. **allow_shorts=False** por defecto. Para activar: `{"allow_shorts": true}`.

6. **ScalpMomentum se corre en 1H** (no 15m): `--timeframe 1H`

7. **Cooldown Pro Trend es DATE-BASED** (`_cooldown_until: "YYYY-MM-DD"`). ScalpMomentum es de barras.

8. **`disable_external_filters=True`** en ProTrendConfig desactiva MVRV/VIX/DXY/NDX/funding/Pi Cycle. Solo para ablation tests, nunca en produccion.

9. **Costes en backtest:**
   - `--costs ideal` = 0.1% fee, 0 slippage (defecto)
   - `--costs realistic` = 0.1% fee + 5bps slippage
   - `--costs conservative` = 0.1% fee + 15bps slippage

10. **walk-forward y baselines** corren 8 y 5 sub-backtests respectivamente. ~40-60 min total. Normal.

11. **Codex skill persistente**: para tareas de Swing, usar `mati-swing-validator`.
    La copia versionada esta en `.codex/skills/mati-swing-validator/` y la copia instalada en `C:\Users\Matias\.codex\skills\mati-swing-validator\`.

12. **Swing Allocator v6-2 es el default actual y esta CONGELADO**:
    - `regime_off_on_bear_onset=True`
    - `bull_peak_ema50_cap_enabled=True`, `bull_peak_ema50_cap=0.85`
    - `use_regime=True`, `use_halving=True`, resto False
    - `daily_on_closed_only=True` (unico delta de comportamiento v5 vs v4)
    - `delta_post_halving=0.20`, `delta_bear_onset=-0.30`
    - `base_btc_pct=0.60`, `min_btc_pct=0.20`, `max_btc_pct=1.00`
    - v2 suprime SOLO `regime_bull` durante `bear_onset`; mantiene `regime_bear`.
    - v3 capea target a 85% en `bull_peak` solo si BTC pierde la EMA50D del dia anterior cerrado.
    - v4 baja el floor a 20% y `delta_bear_onset` a -0.30.
    - v6-2: `use_phase_policy_router=True`, `phase_policy_profile="v5_equiv"`,
      `use_funding_overlay=True`, delta `0.05`, p10/p90, TTL/dedup 7d, solo `accumulation`.
    - Rollback v5: `--config '{"use_phase_policy_router": false, "use_funding_overlay": false}'`
    - Rollback v4: rollback v5 + `"daily_on_closed_only": false`
    - Rollback v3: `--config '{"min_btc_pct": 0.30, "delta_bear_onset": -0.20}'`

13. **Protocolo de comparacion Swing**:
    - Baseline v6 BTC 2015-2026 realistic: $9.505M, CAGR +86.51%, Max DD -52.73%, 70 reb, `btc_vs_bnh_ratio=0.8499`.
    - BTC 2018-2026 realistic v6: $229.0k, CAGR +47.90%, Max DD -53.72%, 53 reb, `btc_vs_bnh_ratio=0.8785`.
    - BTC 2015-2026 conservative v6: $9.255M, CAGR +86.06%, Max DD -52.88%, 70 reb, `btc_vs_bnh_ratio=0.8281`.
    - Comparar v5/v6 por el mismo harness y exactamente las mismas velas; no mezclar resultados CLI/harness.
    - Anclas: CAGR y Max DD. PF es fragil al punto de inicio; usarlo como rango, no como veredicto unico.
    - Siempre comprobar mismo dataset/conteo de velas, misma ventana y mismos costes.
    - Reportar tambien `final_btc_qty`, `bnh_initial_btc` y `btc_vs_bnh_ratio`; para un holder BTC, mas USDT con menos BTC no es automaticamente mejor.
    - La ventana 2015-2026 sigue CERRADA para nuevas optimizaciones. La promocion v6-2 es una
      excepcion explicita del usuario: v5/v6 iniciaron paper simultaneamente, v6 domina todas las
      anclas/rolling starts y el default sigue en paper. Live real aun requiere confirmacion.

14. **Estado siguiente Swing (2026-07-13)**:
    - v6-2 fue ADOPTADO y congelado como default por decision explicita del usuario el 2026-07-13.
    - v6-1 (`phase_policy_profile=v5_equiv`) reproduce v5; v6-2 añade el overlay de funding.
    - v5 y v6 son identicos en vivo durante `bear_onset`; la primera divergencia esperada es aproximadamente 2026-10-07.
    - Mantener el bot v5 aislado como control/rollback. Resolver la frescura del cache funding en
      la VM antes de `accumulation`; si esta stale, v6 degrada a v5 en silencio.
    - Siguen DESCARTADOS: caps globales, todo-o-nada, `min_btc_pct=0.0` como default, latch del cap, chop guards de un solo ciclo y shorts/perps.

15. **`adx_min_entry` en ProTrendConfig**: existe en el dataclass y en el gate (_g_adx_min),
    y ahora esta correctamente en `from_dict()` y `to_dict()`. Bug corregido 2026-06-29.
    Las variantes ADX del sensitivity del 2026-06-28 son invalidas (corrieron todas con 15.0).
    Re-correr antes de sacar conclusiones sobre el gate ADX.

16. **Al crear nuevos indicadores**, añadirlos a `strategies/indicators.py`.

17. **Windows + PowerShell**: sintaxis PS. Para POSIX usar Bash tool.

---

## SEGURIDAD Y ACCIONES CON APROBACION HUMANA

- El modo por defecto es paper. `TRADING_MODE=live`, cualquier orden real, cualquier
  llamada mutante a OKX/Telegram y cualquier ejecucion de `start`, `stop` o
  `tools/paper_fleet_setup.py` requiere confirmacion explicita en la tarea actual.
- No leer ni mostrar el contenido de `.env`, credenciales, headers de autenticacion,
  tokens de Telegram, claves API ni dumps de configuracion secreta. En logs y reportes,
  redactar secretos y datos sensibles.
- No desactivar TLS, comprobaciones de firma, autenticacion, autorizacion, validacion de
  parametros, limites de riesgo ni rate limits. Las llamadas HTTP nuevas deben usar
  timeouts, manejo de errores y el cliente permitido (`aiohttp` o `urllib.request`).
- Validar toda entrada de CLI, JSON, entorno y respuestas externas. Usar SQL parametrizado;
  nunca interpolar entrada del usuario en SQL o comandos del sistema.
- Usar `Decimal` para dinero y UTC para persistencia. No convertir a `float` para ahorrar
  trabajo ni cambiar la zona horaria de la DB.
- Antes de tocar una accion externa, comprobar el modo, el bot objetivo, el simbolo,
  el tamano, el precio, el balance y el rollback. Un test no puede colocar ordenes reales.

Requieren aprobacion humana explicita antes de implementarse o ejecutarse:

- cambios en autenticacion/autorizacion, firma de requests, `core/exchange.py`,
  `core/okx_demo_client.py`, limites de riesgo, sizing u ordenes;
- cualquier cambio al default congelado de Swing, a `strategies/pro_trend.py`, a
  `allow_shorts`, a filtros externos o a costes/lookahead de backtest;
- migraciones de esquema, cambios directos en `trading.db`, borrado de historiales,
  regeneracion del cache canonico o cualquier accion destructiva;
- instalacion de una dependencia con permisos de sistema, una integracion que envie
  dinero/mensajes o un cambio de `deploy/`, systemd, cron, VM, CI o permisos de repositorio;
- push, merge, release, despliegue o cualquier PR listo para mergear. Un draft PR puede
  abrirse solo si la tarea lo solicita expresamente.

## ARCHIVOS Y ARTEFACTOS PROTEGIDOS

No modificar automaticamente, salvo aprobacion expresa y un plan de rollback:

- `strategies/pro_trend.py` (congelado indefinidamente) y los defaults de
  `strategies/swing_allocator.py` (v6-2 congelado);
- `.env`, cualquier archivo de secretos, `.git/` y configuracion de credenciales;
- `data/cache/BTC-USDT_1H.json` y otros caches canonicos versionados; durante el
  forward-test no deduplicar, extender, truncar ni re-descargar el cache;
- `trading.db` y cualquier DB/wallet runtime; no editar SQLite con SQL manual;
- `backtests/journal_*.json`, `logs/`, `graphify-out/`, `.pytest_cache/`, `__pycache__/`,
  `build/` y `dist/` como si fueran codigo fuente. Son artefactos generados o evidencia;
  no borrarlos para ocultar un fallo.

`SESSION.md`, `EXPERIMENTS.md`, `docs/swing/plan.md` y los planes de `docs/` solo se actualizan
cuando cambia el estado o la decision documentada, con fecha, evidencia y rollback. No
reescribir historia para hacerla coincidir con el codigo actual.

---

## COMANDOS PRINCIPALES

Todos los comandos se ejecutan desde la raiz y con Python 3.12 o 3.13 activo. En PowerShell se
puede crear un entorno reproducible asi:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" ruff build
```

Comandos canonicos:

```powershell
# Build y comprobacion de sintaxis
python -m compileall -q .
python -m build

# Tests completos o focalizados
python -m pytest -q
python -m pytest -q tests/test_swing_allocator_controls.py

# Lint
python -m ruff check .

# Ayuda y ejecucion read-only
python main.py --help
python main.py mode
python main.py status
python main.py paper-status
python main.py anomaly-check
python main.py data-audit

# Backtest reproducible del default Swing v6-2
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs conservative
python main.py walk-forward --strategy swing --costs realistic
python main.py baselines --from 2015-01-01 --to 2026-01-01 --costs realistic

# Comparacion de estrategias; no usarla para cambiar el default sin el protocolo Swing
python main.py compare --strategies "adaptive,pro" --from 2018-01-01 --to 2026-01-01

# Paper/live: solo con confirmacion humana explicita en la tarea
python main.py start --tick 30
python main.py dashboard
```

`python main.py start` no es un smoke test: inicia procesos y puede tocar estado externo.
`python main.py stop` es una accion operativa de emergencia y tambien requiere confirmacion
explicita salvo que un runbook de incidente autorizado diga lo contrario. Walk-forward y
baselines lanzan varios sub-backtests y pueden tardar 40-60 minutos.

Si falta `ruff` o `build`, instalar solo la dependencia de desarrollo indicada arriba; no
usar `pip install` global ni modificar production. Si un comando documentado no coincide
con `--help`, detenerse, corregir primero este contrato y reportar la discrepancia. Si el
lint o build falla por deuda preexistente, conservar el fallo visible, no usar `--exit-zero`
ni eliminar codigo o tests no relacionados para maquillarlo. Al 2026-07-15, la linea base
observada es: `python -m pytest -q` = 279 passed; `python -m compileall -q .` = OK;
`python -m ruff check .` = 209 errores existentes; `python -m build` = falla al cargar
`setuptools.backends.legacy:build`. Revalidar estos numeros antes de usarlos como evidencia;
no atribuir esos dos fallos a una tarea que no haya tocado su causa.

---

## CRITERIOS DE ACEPTACION Y CIERRE

Antes de declarar una tarea terminada, Codex debe:

1. Reproducir o verificar el problema con un comando, test, inspeccion o evidencia concreta.
2. Identificar la causa raiz y distinguirla de sintomas o hipotesis.
3. Implementar la correccion minima mantenible, sin tocar archivos protegidos fuera de alcance.
4. Anadir o actualizar tests cuando cambie comportamiento; para documentacion, validar enlaces,
   comandos y consistencia con el repositorio real.
5. Ejecutar los checks relevantes. Para cambios de codigo, como minimo:
   `python -m pytest -q`, `python -m ruff check .`, `python -m compileall -q .` y
   `python -m build`, salvo que una razon documentada haga uno irrelevante.
6. Para cambios de estrategia/backtest, comprobar misma ventana, mismo cache, mismo conteo de
   velas, mismos costes, ausencia de lookahead, rollback y metricas CAGR, Max DD,
   `final_btc_qty`, `bnh_initial_btc` y `btc_vs_bnh_ratio`.
7. Revisar `git status`, `git diff --stat`, `git diff --check` y el diff completo. Confirmar que
   no entraron secretos, DBs, caches, journals, logs ni artefactos generados.
8. Documentar comandos ejecutados, resultados, riesgos, incertidumbres y cualquier check omitido.
   Nunca escribir "tests pasan" si no se ejecutaron o si fallaron.

No se acepta una tarea porque el resultado sea mejor en una sola ventana, porque un warning
desaparezca o porque se haya ocultado un error. Si el cambio afecta una interfaz publica,
persistencia, seguridad o despliegue, los criterios incluyen compatibilidad, rollback y un
smoke test no mutante.

## CUANDO DETENERSE

Detener el trabajo y pedir direccion concreta cuando:

- falta una decision que cambia el alcance, la arquitectura, el riesgo o el comportamiento
  de produccion;
- la tarea exige una accion con aprobacion humana y esa aprobacion no existe;
- aparece un diff previo no relacionado, un secreto, un cambio en un archivo protegido o una
  discrepancia entre `AGENTS.md`, `SESSION.md` y el codigo que no puede resolverse de forma segura;
- un test, build, lint o backtest falla y la correccion requeriria ampliar el alcance,
  debilitar una invariante o modificar datos de referencia;
- no puede demostrarse determinismo, rollback, seguridad o el criterio de aceptacion.

Al detenerse, conservar los cambios seguros, describir el bloqueo con evidencia y dar el
siguiente comando o decision necesaria. No improvisar un workaround silencioso, no borrar
artefactos para limpiar el estado y no seguir con acciones externas.

## POLITICA DE GIT

- Trabajar preferentemente en una rama `codex/<tema>` o worktree dedicado; nunca desarrollar
  directamente sobre `main`.
- Commits pequenos y atomicos con formato `<type>: <descripcion>` usando `feat`, `fix`,
  `refactor`, `docs`, `test`, `chore`, `perf` o `ci`. No anadir `Co-Authored-By`.
- Antes de commitear: revisar `git status`, `git diff --check`, el diff completo y que no haya
  secretos, runtime state, cache canonico ni artefactos generados.
- No usar `git reset --hard`, `git checkout --`, `git clean -fd`, force-push ni reescribir
  commits ajenos. Para descartar cambios, pedir aprobacion y especificar las rutas.
- Codex puede crear el commit y, si la tarea lo pide, publicar la rama y abrir un draft PR.
  Push a `main`, merge, release y deploy requieren aprobacion humana separada.

---

## ARQUITECTURA BACKTEST (resumen)

`BacktestClient` imita `OKXClient` al 100% — estrategias sin cambios de codigo.
Warmup: Pro Trend 380 dias, Adaptive 240 dias, Scalp 25 dias.
`equity_curve: list[tuple[datetime, Decimal]]` — timestamps UTC reales.
Journal automatico: `backtests/journal_{estrategia}_{simbolo}_{timeframe}_{ts}.json`

---

@SESSION.md
