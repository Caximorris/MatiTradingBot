# MatiTradingBot — AGENTS.md

Bot de trading automatizado para OKX. Python 3.12+. Windows 10, PowerShell.
Leer este archivo Y `SESSION.md` antes de tocar cualquier archivo.

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
- `SWING_PLAN.md` — diseno y validacion Swing
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

## COMANDOS PRINCIPALES

```bash
python main.py backtest --strategy pro --from 2018-01-01 --to 2026-01-01 --costs realistic
python main.py walk-forward --strategy pro --costs realistic
python main.py baselines --from 2018-01-01 --to 2026-01-01 --costs realistic
python main.py backtest --strategy scalp --from 2022-01-01 --to 2026-06-01 --timeframe 1H
python main.py start --strategy pro --symbol BTC-USDT
python main.py compare --strategies "adaptive,pro" --from 2018 --to 2026
```

---

## ARQUITECTURA BACKTEST (resumen)

`BacktestClient` imita `OKXClient` al 100% — estrategias sin cambios de codigo.
Warmup: Pro Trend 380 dias, Adaptive 240 dias, Scalp 25 dias.
`equity_curve: list[tuple[datetime, Decimal]]` — timestamps UTC reales.
Journal automatico: `backtests/journal_{estrategia}_{simbolo}_{timeframe}_{ts}.json`

---

@SESSION.md
