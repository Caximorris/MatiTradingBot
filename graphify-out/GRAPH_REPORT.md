# Graph Report - .  (2026-07-13)

## Corpus Check
- 160 files · ~161,299 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1838 nodes · 4575 edges · 90 communities (81 shown, 9 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 264 edges (avg confidence: 0.61)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Prop Challenge Rules
- Macro Halving Context
- Indicators Data Audit
- Bot State Risk
- Telegram Remote Control
- Adaptive Trend Indicators
- Research Archive History
- Prop Swing Engine
- Pro Trend Engine
- Backtest Validation Commands
- Bot CLI Management
- Funding Overlay Events
- Swing Allocator Core
- Scalp Momentum Strategy
- Backtest HTML Reporting
- OKX Demo Client
- Strategy Exchange Abstractions
- Paper Monitoring CLI
- Historical Backtest Data
- Exchange Client Tests
- Backtest Execution Engine
- CFT Monitoring Status
- Demo Client Tests
- Fiscal FIFO Tests
- Database Trading Models
- Backtest CLI Commands
- Backtest Client Interface
- Swing Control Tests
- Runtime Settings
- Telegram Remote Tests
- Performance Breakdown Metrics
- OKX Live Client
- Paper Snapshot Metrics
- Fiscal Report Generator
- Range Reversion Strategy
- Paper Bot Helpers
- Telegram Parity Views
- Adaptive Trend Bot
- Anomaly Detection Tests
- Backtest PnL Accounting
- Terminal Dashboard
- Strategy Registry
- Telegram Equity Charts
- Forward Test Reports
- Paper Exchange Execution
- Paper Snapshot Tests
- Swing Chart Generator
- Live Operations CLI
- Exchange Settings Errors
- IRPF Tax Calculation
- Decision Explanation Tests
- Funding Extreme Strategy
- Monthly Distribution Tools
- Forward Report Tests
- Alpha Screening Tools
- Bybit Cost Probe
- Swing Benchmark Strategies
- Trade Journal Analytics
- Funding Signal Tests
- Market Context Data
- Trade Logging Models
- Funding History Context
- Equity Bootstrap Analysis
- OKX Demo Smoke
- Swing Freeze Report
- Data Audit Tests
- Swing Audit Variants
- Journal Summary Tool
- Rate Limiter Tests
- Degradation Reporting
- Python Dependencies
- Equity Reconciliation Audit
- Backtest Report Interactions
- Swing Chart Interactions
- CLI Package
- Daily Check Automation
- VM Installation
- Prop Paper Setup
- Cost Sensitivity Audit
- Brief Response Mode
- OKX Trader Package

## God Nodes (most connected - your core abstractions)
1. `OKXClient` - 82 edges
2. `SwingAllocatorBot` - 74 edges
3. `BacktestClient` - 67 edges
4. `BacktestEngine` - 56 edges
5. `SwingAllocatorConfig` - 45 edges
6. `get_session()` - 43 edges
7. `fetch_historical_bars()` - 42 edges
8. `RiskManager` - 42 edges
9. `OrderResult` - 40 edges
10. `OKXDemoClient` - 38 edges

## Surprising Connections (you probably didn't know these)
- `Strategy Audit HTML Template` --semantically_similar_to--> `Swing Allocator Audits and Remediation Plan`  [INFERRED] [semantically similar]
  tools/strategy_audit_template.html → docs/swing/audits.md
- `Honest Baseline Comparison` --semantically_similar_to--> `Profit Factor Fragility`  [INFERRED] [semantically similar]
  .claude/commands/compare-results.md → backtests/STRATEGY_VERSIONS.md
- `Client Interface Parity` --semantically_similar_to--> `Shared Trading Client Interface`  [INFERRED] [semantically similar]
  README.md → CLAUDE.md
- `Swing v2 regime_off_on_bear_onset` --semantically_similar_to--> `Swing Allocator v2`  [INFERRED] [semantically similar]
  EXPERIMENTS.md → backtests/STRATEGY_VERSIONS.md
- `Swing v5 daily_on_closed_only` --semantically_similar_to--> `Swing Allocator v5`  [INFERRED] [semantically similar]
  EXPERIMENTS.md → backtests/STRATEGY_VERSIONS.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Swing Validation Discipline** — _codex_skills_mati_swing_validator_skill_mati_swing_validator, _codex_skills_mati_swing_validator_references_swing_protocol_swing_validation_protocol, _claude_commands_compare_results_compare_results, _claude_commands_run_backtest_run_backtest [INFERRED 0.95]
- **Anti-Backtest Deception System** — _claude_commands_audit_backtest_backtest_bias_audit, _claude_commands_data_check_ohlcv_determinism, agents_lookahead_invariants, session_closed_optimization_window [INFERRED 0.85]
- **Swing Allocator Version Lineage** — backtests_strategy_versions_swing_allocator_v2, backtests_strategy_versions_swing_allocator_v3, backtests_strategy_versions_swing_allocator_v4, backtests_strategy_versions_swing_allocator_v5 [EXTRACTED 1.00]
- **Paper Forward-Validation System** — docs_forward_test_contract_forward_test_contract, docs_forward_test_research_lab_plan_research_lab_plan, docs_ops_deploy_paper_paper_deployment_runbook, docs_handoff_handoff_snapshot [INFERRED 0.95]
- **Swing Allocator Design, Audit, and Successor Evolution** — docs_swing_plan_swing_allocator_design_plan, docs_swing_audits_swing_audits, docs_swing_v6_plan_swing_v6_plan, docs_archive_session_archive_swing_allocator_version_history [INFERRED 0.95]
- **Funding Alpha Research Transfer** — docs_prop_hyrotrader_plan_funding_extreme_alpha, docs_income_plan_funding_extreme_income_candidate, docs_swing_v6_plan_funding_extreme_overlay [INFERRED 0.85]

## Communities (90 total, 9 thin omitted)

### Community 0 - "Prop Challenge Rules"
Cohesion: 0.05
Nodes (67): _as_float_curve(), ChallengeResult, ChallengeStats, evaluate_challenge(), evaluate_two_step(), PropRulesConfig, datetime, Decimal (+59 more)

### Community 1 - "Macro Halving Context"
Cohesion: 0.08
Nodes (52): date, get_macro_signal(), load_macro_context(), MacroContext, datetime, Contexto macro para BTC/ETH/SOL/BNB: MVRV ratio y ciclo de halving.  Fuentes d, Descarga datos MVRV diarios de CoinMetrics para el rango dado.         Si el ra, Busca un valor en un dict por fecha, retrocediendo hasta 7 dias.          Empi (+44 more)

### Community 2 - "Indicators Data Audit"
Cohesion: 0.07
Nodes (47): data_audit(), Audita integridad del cache OHLCV (huecos/dups/outliers). Nunca re-descarga el c, BollingerBands, _compute_bb(), _compute_bb_pure(), compute_indicators(), _compute_rsi(), _compute_rsi_pure() (+39 more)

### Community 3 - "Bot State Risk"
Cohesion: 0.08
Nodes (42): BotState, Configuración y estado persistente de cada bot activo., Decimal, Suma el PnL realizado de hoy desde la DB.         Retorna (limite_alcanzado: bo, Cancela TODAS las órdenes abiertas y desactiva todos los bots en DB., Retorna (True, "") si la operación está permitida.         Retorna (False, "raz, Kelly Criterion simplificado.          Fórmula:             risk_amount  = ac, RiskManager (+34 more)

### Community 4 - "Telegram Remote Control"
Cohesion: 0.10
Nodes (51): bot_snapshots(), _bots_hint(), cmd_audit(), cmd_backup(), cmd_chart(), cmd_equity(), cmd_logs(), cmd_restart() (+43 more)

### Community 5 - "Adaptive Trend Indicators"
Cohesion: 0.10
Nodes (43): Adaptive Trend Following con detección de régimen.  Lógica en tres capas:  1, adx(), atr(), bb_bands(), detect_regime(), ema(), ema_slope(), fvg_zones() (+35 more)

### Community 6 - "Research Archive History"
Cohesion: 0.07
Nodes (46): Archive Rather Than Delete Research Artifacts, Deferred Core Refactor, Post-Paper Refactor Backlog, Deterministic OHLCV Cache, Pro Trend v13, Historical Session Archive, Swing Allocator Version History, Forward-Test Failure Taxonomy (+38 more)

### Community 7 - "Prop Swing Engine"
Cohesion: 0.11
Nodes (14): PropSwingBot, PropSwingConfig, DataFrame, datetime, Decimal, Marca el uPnL del short contra el balance USDT (equity continua para el DD)., Devenga funding Bybit por settlement.          Lineal USDT: rate>0 => long pag, Prorratea funding acumulado al tramo cerrado y lo descuenta del realized. (+6 more)

### Community 8 - "Pro Trend Engine"
Cohesion: 0.11
Nodes (11): ProTrendBot, ProTrendConfig, DataFrame, Decimal, Vende partial_exit_size de la posicion long abierta. Solo se ejecuta una vez., Tras 2 perdidas consecutivas activa cooldown extra para evitar re-entradas en pu, Bloquea nuevas entradas durante N días.         Si days=None, usa cooldown_bars, Construye un snapshot plano de todos los indicadores para el journal. (+3 more)

### Community 9 - "Backtest Validation Commands"
Cohesion: 0.07
Nodes (41): Audit Backtest Command, Backtest Bias Audit, Compare Results Command, Honest Baseline Comparison, Data Check Command, OHLCV Determinism, Experiment Change Command, Isolated Reversible Hypothesis (+33 more)

### Community 10 - "Bot CLI Management"
Cohesion: 0.10
Nodes (35): bot_add(), bot_disable(), bot_enable(), bot_list(), Typer, Sub-comandos de gestión de bots: bot list/enable/disable/add., Lista todos los bots configurados en la DB., Activa un bot (lo crea si no existe). (+27 more)

### Community 11 - "Funding Overlay Events"
Cohesion: 0.10
Nodes (34): active_overlay_at(), build_overlay_events(), _cache_mtime(), _cached_events(), _deduplicate(), _empty_events(), funding_cache_path(), _funding_frame() (+26 more)

### Community 12 - "Swing Allocator Core"
Cohesion: 0.10
Nodes (12): Decimal, Gestiona la allocation BTC/USDT dinamicamente segun senales de mercado., Primera barra: comprar base_btc_pct del capital en BTC., Agrega deltas de senales sobre la base. Aplica hard limits.         Devuelve el, RiskManager del live/paper: bloquear solo compras si se supero perdida diaria., Control minimo F14: no operar con OHLCV ausente o precio anomalo.         SOLO, Identificador del bloque 4H UTC actual, p.ej. '2026-07-02T3' (12:00-15:59)., SwingAllocatorBot (+4 more)

### Community 13 - "Scalp Momentum Strategy"
Cohesion: 0.14
Nodes (5): DataFrame, Decimal, Day trading en 15m con contexto de 1H.      Estado persistido:     {, ScalpMomentumBot, ScalpMomentumConfig

### Community 14 - "Backtest HTML Reporting"
Cohesion: 0.12
Nodes (34): build_html(), build_presets_html(), main(), resolve_config(), cache_bounds(), daily_candles(), equity_series(), extract_markers() (+26 more)

### Community 15 - "OKX Demo Client"
Cohesion: 0.11
Nodes (12): OKXDemoClient, datetime, Decimal, Traduce el simbolo de la estrategia al de ejecucion (BTC-USDT -> BTC-USDC)., Presenta la quote de ejecucion con el nombre que espera la estrategia., (state, avgPx|None, accFillSz, fee, feeCcy) de una orden enviada.          Non, Una pata market del bridge. (avgPx, qty, fee, feeCcy) o None si no ejecuto., Reintenta una market cancelada por el motor demo en 2 patas via bridge. (+4 more)

### Community 16 - "Strategy Exchange Abstractions"
Cohesion: 0.09
Nodes (20): ABC, Cliente OKX: REST live y simulacion paper., Gestor de riesgo global. Se consulta antes de cada operación para decidir si es, BaseStrategy, Decimal, Clase abstracta base para todas las estrategias. Las estrategias no comprueban, Registra la apertura de un trade en el journal pendiente., Finaliza el trade pendiente y lo añade al journal. (+12 more)

### Community 17 - "Paper Monitoring CLI"
Cohesion: 0.11
Nodes (32): anomaly_check(), _build(), _daily_check_age_min(), _fmt_money(), paper_status(), datetime, Typer, Comandos de observabilidad del paper forward-test (plan T4.1/T5.1/T6.1/T7.1/T13. (+24 more)

### Community 18 - "Historical Backtest Data"
Cohesion: 0.11
Nodes (29): _fetch_binance_bars(), fetch_historical_bars(), _merge_bars(), Motor de backtesting — simula estrategias sobre datos históricos de OKX.  Dise, Une dos listas de barras, deduplica por timestamp y ordena cronologicamente., Descarga datos OHLCV históricos desde la API pública de OKX.     No requiere au, Fallback: descarga OHLCV desde Binance API publica (sin auth).     Usado cuando, factory() (+21 more)

### Community 19 - "Exchange Client Tests"
Cohesion: 0.07
Nodes (12): client(), _live_client(), _paper_settings(), _persistent_client(), Tests de core/exchange.py — exclusivamente paper mode y degradación graceful. N, OKXClient en paper mode, sin llamadas a OKX., test_live_limit_order_no_tgtccy_and_has_px(), test_live_market_buy_sets_tgtccy_base() (+4 more)

### Community 20 - "Backtest Execution Engine"
Cohesion: 0.12
Nodes (15): BacktestEngine, BacktestResult, _fetch_bitstamp_bars(), datetime, Decimal, Filas para la tabla de resultados rich., Mueve el cursor a la barra idx.         Chequea qué órdenes límite se habrían e, Devuelve los fills generados en el último advance() para que la estrategia (+7 more)

### Community 21 - "CFT Monitoring Status"
Cohesion: 0.16
Nodes (27): append_event(), CFTMonitorConfig, _date_key(), format_status(), _iso(), load_status(), new_status(), Any (+19 more)

### Community 22 - "Demo Client Tests"
Cohesion: 0.16
Nodes (29): _balance_resp(), _client(), _fake_account(), _fake_trade(), _fake_trade_bridge(), Tests de core/okx_demo_client.py — APIs falsas inyectadas, cero red.  Cubren e, SELL en BTC-USDC lo cancela el motor; las patas EUR ejecutan bien., _settings() (+21 more)

### Community 23 - "Fiscal FIFO Tests"
Cohesion: 0.13
Nodes (28): FIFOCalculator, Aplica el método FIFO para emparejar compras y ventas.      Para cada símbolo, _make_trade(), Tests para reporting/fiscal_report.py — FIFO, IRPF 2026, sin Excel real., Venta de 2 BTC consume dos lotes con precios distintos., Venta parcial deja el resto del lote disponible para la siguiente venta., Los lotes de BTC y ETH son completamente independientes., Venta sin compra previa se registra en unmatched_sells, no crashea. (+20 more)

### Community 24 - "Database Trading Models"
Cohesion: 0.15
Nodes (22): Base, close_position(), create_trade(), get_or_create_bot_state(), get_trades(), Position, datetime, Modelos SQLAlchemy y gestión de sesiones para SQLite. Todos los importes usan D (+14 more)

### Community 25 - "Backtest CLI Commands"
Cohesion: 0.15
Nodes (24): backtest(), baselines(), Typer, Comandos de backtest y validación: backtest, walk-forward, baselines, sensitivit, Compara la estrategia Pro Trend contra baselines simples.      Baselines imple, Backtest continuo de una estrategia.  Las posiciones se abren y cierran     úni, Sensitivity analysis de Pro Trend v12: barre un parametro a la vez     mantenie, Validacion walk-forward: entrena en un periodo y evalua en el siguiente. (+16 more)

### Community 26 - "Backtest Client Interface"
Cohesion: 0.11
Nodes (17): BacktestClient, Reemplaza OKXClient durante el backtest.     Las estrategias llaman exactamente, Devuelve un DataFrame OHLCV igual que OKXClient.get_ohlcv para compatibilidad., Ajusta directamente el saldo — usado para liquidar P&L de cortos sintéticos., Devuelve el funding rate historico del dia actual de la simulacion., _btc_ratio(), ConfigCase, main() (+9 more)

### Community 27 - "Swing Control Tests"
Cohesion: 0.18
Nodes (19): SwingAllocatorConfig, BacktestClient, BlockingRisk, FakeClient, Decimal, El nombre de clase exacto activa la rama backtest en _is_backtest_client()., _target_for_phase_policy_case(), test_funding_overlay_adds_to_phase_router_target() (+11 more)

### Community 28 - "Runtime Settings"
Cohesion: 0.17
Nodes (22): _bool_env(), _decimal_env(), _int_env(), load_settings(), _optional(), _parse_pairs(), Decimal, Carga y valida la configuración desde .env. Importar `settings` en cualquier mó (+14 more)

### Community 29 - "Telegram Remote Tests"
Cohesion: 0.14
Nodes (22): _add_bot(), _row(), _snap(), _snap_full(), test_format_anomalies_empty_and_populated(), test_format_heartbeat_multi_summarizes_each_bot(), test_format_status_reports_alive_paused_and_stale(), test_pause_and_resume_commands_flip_is_active() (+14 more)

### Community 30 - "Performance Breakdown Metrics"
Cohesion: 0.17
Nodes (21): _annual_returns_from_curve(), _btc_year_returns(), _pct(), _print_quarterly_table(), datetime, Decimal, _quarterly_breakdown(), Helpers compartidos por todos los comandos del CLI. (+13 more)

### Community 31 - "OKX Live Client"
Cohesion: 0.13
Nodes (6): OKXClient, Interfaz unificada para OKX., Retorna copia de las órdenes limit pendientes en paper mode., Carga balances paper persistidos. Debe llamarse solo desde __init__ (sin lock aú, client_with_ticker(), Cliente paper con get_ticker mockeado para devolver 65000.

### Community 32 - "Paper Snapshot Metrics"
Cohesion: 0.17
Nodes (21): build_snapshots(), discover_bots(), filter_bot_rebalances(), next_4h_eval(), paper_state_path_for(), perf_ratio(), datetime, Decimal (+13 more)

### Community 33 - "Fiscal Report Generator"
Cohesion: 0.16
Nodes (11): NamedTuple, FiscalReportGenerator, FiscalSummary, GainLossRecord, PurchaseLot, Decimal, Generador de informe fiscal IRPF España para criptomonedas.  Aplica el método, Procesa un trade y actualiza el estado FIFO. (+3 more)

### Community 34 - "Range Reversion Strategy"
Cohesion: 0.20
Nodes (4): Decimal, RangeReversionBot, RangeReversionConfig, Mean reversion con gate de regimen ADX.      Estado persistido:     {

### Community 35 - "Paper Bot Helpers"
Cohesion: 0.15
Nodes (19): _bots(), test_bot_label_prefers_instance_id_then_name_then_legacy(), test_filter_rebalances_by_strategy(), test_paper_state_path_isolated_vs_legacy(), test_resolve_bot_by_label_and_substring_and_ambiguity(), test_safe_state_name_matches_exchange_rules(), bot_label(), filter_rebalances() (+11 more)

### Community 36 - "Telegram Parity Views"
Cohesion: 0.20
Nodes (20): Regresion 2026-07-11: el cron perdio +x 5 dias; /parity mostraba 'OK' en verde s, test_format_parity_flags_stale_check(), test_parse_daily_checks_and_streak(), _bot_row(), _bot_status_icon(), format_heartbeat_multi(), format_parity(), format_status() (+12 more)

### Community 37 - "Adaptive Trend Bot"
Cohesion: 0.19
Nodes (5): AdaptiveTrendBot, AdaptiveTrendConfig, Decimal, Trend follower con régimen adaptativo.      Estado persistido:     {, Descarga barras 1H, las resamplea a diario (excluyendo el día incompleto actual)

### Community 38 - "Anomaly Detection Tests"
Cohesion: 0.16
Nodes (14): None = no evaluado (p.ej. dev sin cron) -> no debe fabricar una alerta falsa., Regresion 2026-07-11: el cron perdio +x 5 dias y /parity seguia mostrando 'OK' e, _snap(), test_alerts_sorted_by_severity(), test_clean_snapshot_no_alerts(), test_daily_check_fresh_not_flagged(), test_daily_check_none_not_flagged(), test_daily_check_stale_flagged() (+6 more)

### Community 39 - "Backtest PnL Accounting"
Cohesion: 0.20
Nodes (15): BacktestTrade, Alias de compatibilidad: desde 2026-07-02 el default es ACB., P&L por trade con coste medio ponderado (average cost basis).          Cada BU, Pairing antiguo (pre-auditoria 2026-07-02): asocia cada venta con la compra abie, _bar(), Tests del pairing de P&L por trade (fix auditoria 2026-07-02, hallazgo B3).  _, _t(), test_coste_medio_pondera_compras() (+7 more)

### Community 40 - "Terminal Dashboard"
Cohesion: 0.24
Nodes (18): Layout, Panel, _balance_panel(), _bots_panel(), _elapsed(), _footer_panel(), _header_panel(), _madrid() (+10 more)

### Community 41 - "Strategy Registry"
Cohesion: 0.16
Nodes (14): Any, Registro central de estrategias.  Para añadir una nueva estrategia:   1. Crea, Resuelve un nombre de BotState como 'swing_allocator_btc_usdt'     buscando por, Devuelve (BotClass, ConfigClass) importando el módulo bajo demanda., Construye el objeto Config con símbolo y overrides de --config., Instancia el Bot con su config ya construida., resolve(), StrategyMeta (+6 more)

### Community 42 - "Telegram Equity Charts"
Cohesion: 0.19
Nodes (18): test_build_equity_series_reconstructs_holdings(), build_equity_series(), _date_axis(), _dates(), _event_markers(), fetch_candles(), _fig_ax(), _fmt_dollar_axis() (+10 more)

### Community 43 - "Forward Test Reports"
Cohesion: 0.19
Nodes (17): forward_report(), Reporte que SOLO usa datos posteriores al inicio del forward-test., _bot_forward_metrics(), build_forward_report(), _drawdown_from_series(), _fmt(), _forward_only(), _parse_ts() (+9 more)

### Community 44 - "Paper Exchange Execution"
Cohesion: 0.18
Nodes (6): datetime, Decimal, Verifica y descuenta balance para una market order. Debe llamarse con el lock to, Verifica órdenes limit pendientes y ejecuta las que cruzan el precio actual., Establece el balance simulado para una moneda. Útil para tests y backtest., Escribe balances paper a disco. Llamar con self._paper_lock tomado.

### Community 45 - "Paper Snapshot Tests"
Cohesion: 0.14
Nodes (6): _FakeBot, _FakeQuery, _FakeSession, test_build_snapshots_marks_stale_and_computes_metrics(), test_read_paper_balances_parses_decimals(), _write_wallet()

### Community 46 - "Swing Chart Generator"
Cohesion: 0.18
Nodes (17): build_html(), build_presets(), load_bars(), load_journal(), main(), marker_data(), phase_bands(), Path (+9 more)

### Community 47 - "Live Operations CLI"
Cohesion: 0.24
Nodes (16): _load_settings(), _make_client(), dashboard(), mode(), Typer, Comandos de operación live/paper: start, stop, status, dashboard, mode., Parada de emergencia: cancela órdenes y desactiva todos los bots., Muestra el estado actual: bots, balance y posiciones abiertas. (+8 more)

### Community 48 - "Exchange Settings Errors"
Cohesion: 0.17
Nodes (10): Settings, ExchangeError, ExchangeUnavailable, Error retornado por la API de OKX (código != 0)., Exchange no alcanzable: timeout, sin conexión, 5xx., _with_retry(), Any, Path (+2 more)

### Community 49 - "IRPF Tax Calculation"
Cohesion: 0.12
Nodes (16): calculate_irpf_tax(), Aplica los tramos progresivos de la base del ahorro IRPF 2026.     Retorna la e, 3000€ de ganancia → 3000 * 19% = 570€., 6000€ → 6000 * 19% = 1140€., 10000€ → 6000*19% + 4000*21% = 1140 + 840 = 1980€., 60000€ → 6000*19% + 44000*21% + 10000*23%., Ganancia muy alta incluye tramo del 28%., El tipo efectivo es menor que el tipo marginal del tramo más alto. (+8 more)

### Community 50 - "Decision Explanation Tests"
Cohesion: 0.21
Nodes (14): Mismo bug de fondo que registry.resolve() (2026-07-11): un prefijo corto no debe, test_explain_rebalance_no_signals(), test_explain_rebalance_renders_readable_block(), test_explain_signal_handles_dynamic_suffix(), test_explain_signal_prefers_longest_match(), test_explain_signal_unknown_code_is_labeled_not_silently_ignored(), test_find_rebalance_filters_by_strategy_and_date(), explain_rebalance() (+6 more)

### Community 51 - "Funding Extreme Strategy"
Cohesion: 0.23
Nodes (4): FundingExtremeBot, datetime, Long paga rate>0 / cobra rate<0 sobre el notional en cada settlement., Consume senales con settlement <= ts y programa la entrada con su delay.

### Community 52 - "Monthly Distribution Tools"
Cohesion: 0.27
Nodes (13): _dt(), Tests de tools/monthly_dist.py (plan income M0)., test_monthly_returns_basic_and_carry_forward(), test_monthly_returns_empty_and_inverted_range(), test_summarize_counts_positive_months_and_streak(), main(), _month_key(), monthly_returns() (+5 more)

### Community 53 - "Forward Report Tests"
Cohesion: 0.16
Nodes (3): _Q, _Session, test_build_forward_report_no_bots_is_clean()

### Community 54 - "Alpha Screening Tools"
Cohesion: 0.32
Nodes (13): consistency(), fetch_funding(), load_ohlcv(), main(), DataFrame, Series, N2 (PLAN B, HYROTRADER_PLAN seccion 13) — screens de alfa NO-indicador sobre dat, Funding por settlement desde BYBIT (exchange objetivo; OKX solo sirve ~3 meses). (+5 more)

### Community 55 - "Bybit Cost Probe"
Cohesion: 0.36
Nodes (13): _d(), _depth_within(), _fetch_orderbook(), _fmt_bps(), _fmt_usdt(), main(), _pct(), _print_report() (+5 more)

### Community 56 - "Swing Benchmark Strategies"
Cohesion: 0.45
Nodes (13): BenchResult, _buy(), _dca_weekly(), _df_from_bars(), _ema200_longflat(), main(), _metrics(), _monthly_6040() (+5 more)

### Community 57 - "Trade Journal Analytics"
Cohesion: 0.24
Nodes (12): _as_float(), _augment_true_pnl(), _compute_stats(), Trade Journal — registro exhaustivo de cada operación con todos los indicadores,, Convierte cualquier valor a tipo JSON-serializable de forma recursiva., Escribe el journal completo a un archivo JSON.     Devuelve la ruta del archivo, PnL real del trade completo, incluyendo partial exits si el balance esta disponi, Anade campos de PnL real sin eliminar el PnL del cierre final. (+4 more)

### Community 58 - "Funding Signal Tests"
Cohesion: 0.27
Nodes (9): build_funding_signals(), FundingExtremeConfig, DataFrame, [(ts_ms, "hi"|"lo")] deduplicado. Umbral = percentil trailing shift(1):     el, _rows(), test_hi_lo_and_dedup(), test_no_signals_with_flat_funding(), test_threshold_is_trailing_shift1() (+1 more)

### Community 59 - "Market Context Data"
Cohesion: 0.23
Nodes (12): _fetch_yahoo(), _fetch_yahoo_csv(), _fetch_yahoo_json(), get_market_context(), load_market_context(), datetime, Contexto de mercado global — DXY (índice dólar) y NASDAQ-100.  Usado como filt, Descarga DXY y NASDAQ para el período indicado + 30 días de margen.     Llamar (+4 more)

### Community 60 - "Trade Logging Models"
Cohesion: 0.33
Nodes (6): Cada operación ejecutada (compra o venta), real o paper., Trade, Decimal, Punto único de escritura para todos los trades del sistema. Cada módulo que eje, Registra un Trade a partir de un OrderResult del exchange.         Retorna None, TradeLogger

### Community 61 - "Funding History Context"
Cohesion: 0.31
Nodes (8): _fetch_page(), get_funding_rate_at(), load_funding_history(), datetime, Historial de funding rates de OKX para backtesting.  OKX perpetual swaps liqui, Devuelve la tasa de funding media del dia ANTERIOR completo.      OKX liquida, Descarga una pagina de hasta 100 registros de funding historico., Descarga el historico de funding rates para 'symbol' en el rango dado.      sy

### Community 62 - "Equity Bootstrap Analysis"
Cohesion: 0.44
Nodes (8): main(), _max_dd(), _monthly_return_blocks(), _percentile(), datetime, Decimal, Bootstrap por bloques mensuales de la equity Swing v4.  Uso:     python tools, _run_v4()

### Community 63 - "OKX Demo Smoke"
Cohesion: 0.50
Nodes (8): cmd_flatten(), cmd_read_only(), cmd_trade_cycle(), _fmt_balance(), main(), _print_order(), Decimal, Vende a USDT todo activo no-USDT con par directo. Deja la cuenta lista para INIT

### Community 64 - "Swing Freeze Report"
Cohesion: 0.39
Nodes (8): Anchor, _btc_ratio(), main(), BacktestClient, datetime, Anchor report for Swing Allocator v5 post-audit freeze.  Usage:     python to, _run(), _warmup_bars()

### Community 65 - "Data Audit Tests"
Cohesion: 0.54
Nodes (6): _meta(), _row(), test_audit_clean_contiguous_cache(), test_audit_detects_duplicates(), test_audit_detects_high_below_low_and_hard_jump(), test_format_report_runs()

### Community 66 - "Swing Audit Variants"
Cohesion: 0.48
Nodes (6): main(), datetime, Checks aislados de limpieza para Swing v4 (F8/F9/F10).  Uso:     python tools, _run(), VariantCase, _warmup_bars()

### Community 67 - "Journal Summary Tool"
Cohesion: 0.70
Nodes (4): _dump_section(), _fmt(), main(), _resolve_latest()

### Community 69 - "Degradation Reporting"
Cohesion: 0.67
Nodes (3): main(), _quarter(), Reporte de degradacion para Swing paper/live (F19).  Uso:     python tools/de

### Community 70 - "Python Dependencies"
Cohesion: 0.67
Nodes (3): Async HTTP and WebSocket Stack, CLI and Reporting Stack, Python Runtime Dependencies

### Community 72 - "Backtest Report Interactions"
Cohesion: 0.67
Nodes (3): bucketKey, buildView, setTF

### Community 73 - "Swing Chart Interactions"
Cohesion: 0.67
Nodes (3): bucketKey, buildView, setTF

## Knowledge Gaps
- **31 isolated node(s):** `daily_checks.sh script`, `install_vm.sh script`, `setup_prop_cft_paper.sh script`, `okx-trader`, `PhasePolicy` (+26 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `OKXClient` connect `OKX Live Client` to `Indicators Data Audit`, `Bot State Risk`, `Adaptive Trend Indicators`, `Prop Swing Engine`, `Pro Trend Engine`, `Scalp Momentum Strategy`, `OKX Demo Client`, `Strategy Exchange Abstractions`, `Exchange Client Tests`, `Backtest Client Interface`, `Performance Breakdown Metrics`, `Range Reversion Strategy`, `Adaptive Trend Bot`, `Terminal Dashboard`, `Paper Exchange Execution`, `Live Operations CLI`, `Exchange Settings Errors`, `Funding Extreme Strategy`, `Forward Report Tests`, `Funding Signal Tests`?**
  _High betweenness centrality (0.112) - this node is a cross-community bridge._
- **Why does `BotState` connect `Bot State Risk` to `Paper Snapshot Metrics`, `Telegram Remote Control`, `Prop Swing Engine`, `Terminal Dashboard`, `Bot CLI Management`, `Live Operations CLI`, `Strategy Exchange Abstractions`, `Database Trading Models`, `Swing Control Tests`, `Telegram Remote Tests`?**
  _High betweenness centrality (0.090) - this node is a cross-community bridge._
- **Why does `Trade` connect `Trade Logging Models` to `Fiscal Report Generator`, `Bot State Risk`, `Terminal Dashboard`, `Bot CLI Management`, `Live Operations CLI`, `Strategy Exchange Abstractions`, `Fiscal FIFO Tests`, `Database Trading Models`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Are the 20 inferred relationships involving `OKXClient` (e.g. with `Settings` and `OKXDemoClient`) actually correct?**
  _`OKXClient` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `SwingAllocatorBot` (e.g. with `BacktestClient` and `BlockingRisk`) actually correct?**
  _`SwingAllocatorBot` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `BacktestClient` (e.g. with `Base` and `OrderResult`) actually correct?**
  _`BacktestClient` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `BacktestEngine` (e.g. with `Base` and `OrderResult`) actually correct?**
  _`BacktestEngine` has 13 INFERRED edges - model-reasoned connections that need verification._