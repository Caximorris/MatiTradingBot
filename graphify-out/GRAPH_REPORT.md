# Graph Report - .  (2026-07-14)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 2058 nodes · 4794 edges · 153 communities (110 shown, 43 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 251 edges (avg confidence: 0.59)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `0d246718`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- evaluate_challenge
- swing_v6_common.py
- OHLCVBar
- test_risk_manager.py
- telegram_remote.py
- pro_trend.py
- Interactive Backtest Report Template
- PropSwingBot
- ProTrendBot
- dashboard.py
- SwingAllocatorConfig
- swing_funding_overlay.py
- _Session
- ScalpMomentumBot
- report_common.py
- OKXDemoClient
- BaseStrategy
- paper_cmds.py
- prop_router_vs_swing.py
- test_exchange.py
- BacktestClient
- update_status
- test_okx_demo_client.py
- Trade
- get_or_create_bot_state
- fetch_historical_bars
- stress_usdt_depeg.py
- SwingAllocatorBot
- load_settings
- test_telegram_remote.py
- common.py
- OKXClient
- paper_snapshot.py
- swing_benchmarks.py
- RangeReversionBot
- test_paper_bots.py
- _esc
- ema
- test_anomaly_check.py
- test_backtest_pnl.py
- live_cmds.py
- registry.py
- tg_charts.py
- forward_report.py
- BTC Swing Allocator — Plan de Diseño
- test_paper_snapshot.py
- swing_chart.py
- get_session
- exchange.py
- report_cmds.py
- explain
- FundingExtremeBot
- test_monthly_dist.py
- BotState
- alpha_screens.py
- bybit_public_cost_probe.py
- ProTrendConfig
- trade_journal.py
- swing_parity_check.py
- get_market_context
- load_funding_history
- bootstrap_equity.py
- Via A — EXP-011: funding_extreme como vehiculo propio (sin corse prop)
- swing_v5_freeze_report.py
- test_data_audit.py
- swing_audit_variants.py
- journal_summary.py
- MacroContext
- degradation_report.py
- Python Runtime Dependencies
- audit_equity_recon.py
- buildView
- buildView
- __init__.py
- daily_checks.sh
- install_vm.sh
- setup_prop_cft_paper.sh
- audit_costs.py
- Brief Response Mode
- okx-trader
- HYROTRADER_PLAN.md — Estrategia prop firm (HyroTrader/Bybit)
- prop_breach_audit.py
- simulate_challenges
- MatiTradingBot — CLAUDE.md
- SESSION_ARCHIVE.md — Historial completo y referencia detallada
- prop_phase_matrix.py
- handle_command
- RiskManager
- prop_phase_frontier.py
- anomaly_check.py
- SESSION.md — Estado del proyecto (HOT — se carga en cada sesion via @SESSION.md)
- swing_ablation_matrix.py
- v6-2 Adoption Decision
- PROXIMOS PASOS (orden estricto — no cambiar parametros antes de completarlos)
- SWING ALLOCATOR — REFERENCIA
- REFACTOR_BACKLOG.md — Limpieza y refactor (post-paper)
- PRO TREND v12 — REFERENCIA COMPLETA
- REGLAS INVARIANTES ANTES DE TOCAR CODIGO
- AUDITORIA 2026-06-30 - ROADMAP DE MEJORAS
- RESULTADOS DE BACKTEST
- OKXClient Connection Trace
- Corrected v6-2 Adoption Decision
- test_client_contract.py
- Strategy Audit Checklist
- Audit Backtest Command
- Backtest Bias Audit
- Compare Results Command
- Honest Baseline Comparison
- Data Check Command
- OHLCV Determinism
- Experiment Change Command
- Isolated Reversible Hypothesis
- Compact Journal Extraction
- Journal Summary Command
- Canonical Swing Backtest
- Run Backtest Command
- Claude Project Instructions
- Shared Trading Client Interface
- Archive Rather Than Delete Research Artifacts
- Deferred Core Refactor
- Post-Paper Refactor Backlog
- Deterministic OHLCV Cache
- Pro Trend v13
- Historical Session Archive
- Swing Allocator Version History
- Funding Extreme Income Candidate
- Cross-Venue Microstructure Collector
- MR-Regime 1H Experiment
- Short-Horizon Income Research Plan
- CFT Halving-Phase Router
- Funding Extreme Alpha
- HyroTrader Challenge Rules
- HyroTrader and CFT Prop-Firm Research Plan
- Prop Swing Strategy
- Cost-Aware Rebalancing
- Percentage-Based BTC Allocation
- BTC Swing Allocator Design Plan

## God Nodes (most connected - your core abstractions)
1. `OKXClient` - 83 edges
2. `SwingAllocatorBot` - 74 edges
3. `BacktestClient` - 68 edges
4. `BacktestEngine` - 56 edges
5. `SwingAllocatorConfig` - 47 edges
6. `get_session()` - 43 edges
7. `fetch_historical_bars()` - 42 edges
8. `RiskManager` - 42 edges
9. `OrderResult` - 40 edges
10. `OKXDemoClient` - 39 edges

## Surprising Connections (you probably didn't know these)
- `Live Confirmation Gate` --semantically_similar_to--> `Paper-First Execution`  [INFERRED] [semantically similar]
  AGENTS.md → README.md
- `bot_list()` --indirect_call--> `BotState`  [INFERRED]
  cli/bot_cmds.py → core/database.py
- `start()` --indirect_call--> `BotState`  [INFERRED]
  cli/live_cmds.py → core/database.py
- `status()` --indirect_call--> `BotState`  [INFERRED]
  cli/live_cmds.py → core/database.py
- `status()` --indirect_call--> `Position`  [INFERRED]
  cli/live_cmds.py → core/database.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **v6-2 Default and Rollback State** — session_swing_allocator_v6_2_frozen_default, session_v5_rollback_and_isolated_control, session_paired_v6_2_anchor_results, session_v5_v6_bear_onset_equivalence [EXTRACTED 1.00]
- **2026-07-14 Validation Delta** — session_riskmanager_utc_daily_loss_boundary_fix, session_233_of_233_tests_passing, session_current_project_state_2026_07_14 [EXTRACTED 1.00]
- **Demo VM Activation Follow-Up** — session_okx_demo_vm_v6_2_pull_restart_pending, session_matibot_telegram_restart_requirement, session_immediate_vm_verification_steps [EXTRACTED 1.00]
- **Reliability Follow-Up** — graphify_out_memory_query_20260713_193853_track_all_conections_okxclient_connection_trace, graphify_out_memory_query_20260713_194649_whats_the_next_step_with_this_info_can_we_optimiz_client_interface_contract_gap, graphify_out_memory_query_20260713_194649_whats_the_next_step_with_this_info_can_we_optimiz_funding_cache_stale_observability, graphify_out_memory_query_20260713_194649_whats_the_next_step_with_this_info_can_we_optimiz_deferred_post_paper_refactor [INFERRED 0.85]
- **v6 Decision Correction Chain** — graphify_out_memory_query_20260713_202836_should_swing_allocator_v6_replace_frozen_v5_and_w_superseded_v5_retention_decision, graphify_out_memory_query_20260713_202836_should_swing_allocator_v6_replace_frozen_v5_and_w_later_v6_2_promotion_correction, graphify_out_memory_query_20260713_213920_should_swing_allocator_v6_replace_frozen_v5_and_w_corrected_v6_2_adoption_decision [EXTRACTED 1.00]
- **Swing v6-2 Frozen Default Consensus** — readme_swing_allocator_v6_2, agents_swing_allocator_v6_2_frozen_default, session_v6_2_promotion_record, docs_swing_v6_plan_v6_2_adoption_decision, codex_skills_mati_swing_validator_references_swing_protocol_frozen_baseline [EXTRACTED 1.00]
- **Forward-Test Governance** — session_forward_test_observability, docs_forward_test_contract_failure_taxonomy, docs_forward_test_research_lab_plan_disciplined_research_monitoring_lab, docs_ops_deploy_paper_isolated_paper_architecture [INFERRED 0.85]
- **v5 Control and Rollback** — experiments_exp_002_swing_v5_daily_on_closed_only, backtests_strategy_versions_swing_allocator_v5, docs_swing_v6_plan_v5_rollback, docs_forward_test_contract_variants_under_test [EXTRACTED 1.00]

## Communities (153 total, 43 thin omitted)

### Community 0 - "evaluate_challenge"
Cohesion: 0.13
Nodes (14): evaluate_challenge(), PropRulesConfig, Simula UN challenge que arranca en equity[start_idx].      equity: curva (ts U, curve(), drift_days(), flat_days(), datetime, Tests de core/prop_rules.py con curvas de equity sinteticas (HYROTRADER_PLAN P1) (+6 more)

### Community 1 - "swing_v6_common.py"
Cohesion: 0.11
Nodes (44): test_funding_extremes_use_shifted_thresholds_and_dedup(), test_infer_phase_prefers_rebalance_signal(), test_iter_start_dates_respects_min_days(), test_v6_default_presets_and_v5_rollback_are_explicit(), attach_forward_returns(), consistency(), deduplicate_events(), fetch_bybit_funding() (+36 more)

### Community 2 - "OHLCVBar"
Cohesion: 0.07
Nodes (49): data_audit(), Audita integridad del cache OHLCV (huecos/dups/outliers). Nunca re-descarga el c, _merge_bars(), Une dos listas de barras, deduplica por timestamp y ordena cronologicamente., BollingerBands, _compute_bb(), _compute_bb_pure(), compute_indicators() (+41 more)

### Community 3 - "test_risk_manager.py"
Cohesion: 0.14
Nodes (32): _insert_position(), _insert_trade(), _make_client(), _make_rm(), _make_settings(), patched_session(), Decimal, Tests para core/risk_manager.py.  RiskManager usa get_session() internamente ( (+24 more)

### Community 4 - "telegram_remote.py"
Cohesion: 0.15
Nodes (26): cmd_backup(), cmd_chart(), cmd_equity(), discover_bots(), _load_snapshots(), _load_tg_state(), main(), Decimal (+18 more)

### Community 5 - "pro_trend.py"
Cohesion: 0.09
Nodes (41): Gestor de riesgo global. Se consulta antes de cada operación para decidir si es, Clase abstracta base para todas las estrategias. Las estrategias no comprueban, FundingExtremeConfig, load_funding(), Funding Extreme Long — motor N4 del PLAN B prop (HYROTRADER_PLAN seccion 13)., adx(), atr(), bb_bands() (+33 more)

### Community 6 - "Interactive Backtest Report Template"
Cohesion: 0.67
Nodes (3): Swing Go/No-Go Validation Protocol, Interactive Backtest Report Template, Interactive Swing Chart Template

### Community 7 - "PropSwingBot"
Cohesion: 0.11
Nodes (14): PropSwingBot, PropSwingConfig, DataFrame, datetime, Decimal, Marca el uPnL del short contra el balance USDT (equity continua para el DD)., Devenga funding Bybit por settlement.          Lineal USDT: rate>0 => long pag, Prorratea funding acumulado al tramo cerrado y lo descuenta del realized. (+6 more)

### Community 8 - "ProTrendBot"
Cohesion: 0.11
Nodes (14): ema_slope(), Cambio porcentual de la EMA sobre N barras (proxy de pendiente)., Detecta estructura de mercado usando los últimos N barras.     Retorna 'uptrend, swing_structure(), ProTrendBot, DataFrame, Decimal, Vende partial_exit_size de la posicion long abierta. Solo se ejecuta una vez. (+6 more)

### Community 9 - "dashboard.py"
Cohesion: 0.24
Nodes (18): Layout, Panel, _balance_panel(), _bots_panel(), _elapsed(), _footer_panel(), _header_panel(), _madrid() (+10 more)

### Community 10 - "SwingAllocatorConfig"
Cohesion: 0.15
Nodes (22): Base, DeclarativeBase, SwingAllocatorConfig, BacktestClient, BlockingRisk, FakeClient, Decimal, El nombre de clase exacto activa la rama backtest en _is_backtest_client(). (+14 more)

### Community 11 - "swing_funding_overlay.py"
Cohesion: 0.10
Nodes (34): active_overlay_at(), build_overlay_events(), _cache_mtime(), _cached_events(), _deduplicate(), _empty_events(), funding_cache_path(), _funding_frame() (+26 more)

### Community 12 - "_Session"
Cohesion: 0.14
Nodes (7): Decimal, Punto único de escritura para todos los trades del sistema. Cada módulo que eje, Registra un Trade a partir de un OrderResult del exchange.         Retorna None, TradeLogger, _Q, _Session, test_build_forward_report_no_bots_is_clean()

### Community 13 - "ScalpMomentumBot"
Cohesion: 0.15
Nodes (4): DataFrame, Decimal, Day trading en 15m con contexto de 1H.      Estado persistido:     {, ScalpMomentumBot

### Community 14 - "report_common.py"
Cohesion: 0.12
Nodes (34): build_html(), build_presets_html(), main(), resolve_config(), cache_bounds(), daily_candles(), equity_series(), extract_markers() (+26 more)

### Community 15 - "OKXDemoClient"
Cohesion: 0.11
Nodes (12): OKXDemoClient, datetime, Decimal, Traduce el simbolo de la estrategia al de ejecucion (BTC-USDT -> BTC-USDC)., Presenta la quote de ejecucion con el nombre que espera la estrategia., (state, avgPx|None, accFillSz, fee, feeCcy) de una orden enviada.          Non, Una pata market del bridge. (avgPx, qty, fee, feeCcy) o None si no ejecuto., Reintenta una market cancelada por el motor demo en 2 patas via bridge. (+4 more)

### Community 16 - "BaseStrategy"
Cohesion: 0.12
Nodes (10): ABC, BaseStrategy, Decimal, Registra la apertura de un trade en el journal pendiente., Finaliza el trade pendiente y lo añade al journal., Identificador único de la estrategia. Usado en logs y en DB., Lógica principal del tick.         Llamado periódicamente por el scheduler (APS, True si las condiciones de entrada están dadas en este momento. (+2 more)

### Community 17 - "paper_cmds.py"
Cohesion: 0.17
Nodes (19): anomaly_check(), _build(), _daily_check_age_min(), _fmt_money(), paper_status(), datetime, Typer, Comandos de observabilidad del paper forward-test (plan T4.1/T5.1/T6.1/T7.1/T13. (+11 more)

### Community 18 - "prop_router_vs_swing.py"
Cohesion: 0.28
Nodes (12): factory(), Sensibilidad del umbral bear_onset (540d) del reloj de halving. Uso: python sen, _bnh_row(), _dt(), main(), _max_dd(), Any, datetime (+4 more)

### Community 19 - "test_exchange.py"
Cohesion: 0.07
Nodes (14): client(), client_with_ticker(), _live_client(), _paper_settings(), _persistent_client(), Tests de core/exchange.py — exclusivamente paper mode y degradación graceful. N, OKXClient en paper mode, sin llamadas a OKX., Cliente paper con get_ticker mockeado para devolver 65000. (+6 more)

### Community 20 - "BacktestClient"
Cohesion: 0.08
Nodes (27): BacktestClient, BacktestEngine, BacktestResult, _fetch_binance_bars(), _fetch_bitstamp_bars(), datetime, Decimal, Motor de backtesting — simula estrategias sobre datos históricos de OKX.  Dise (+19 more)

### Community 21 - "update_status"
Cohesion: 0.16
Nodes (27): append_event(), CFTMonitorConfig, _date_key(), format_status(), _iso(), load_status(), new_status(), Any (+19 more)

### Community 22 - "test_okx_demo_client.py"
Cohesion: 0.16
Nodes (29): _balance_resp(), _client(), _fake_account(), _fake_trade(), _fake_trade_bridge(), Tests de core/okx_demo_client.py — APIs falsas inyectadas, cero red.  Cubren e, SELL en BTC-USDC lo cancela el motor; las patas EUR ejecutan bien., _settings() (+21 more)

### Community 23 - "Trade"
Cohesion: 0.06
Nodes (57): Cada operación ejecutada (compra o venta), real o paper., Trade, NamedTuple, calculate_irpf_tax(), FIFOCalculator, FiscalReportGenerator, FiscalSummary, GainLossRecord (+49 more)

### Community 24 - "get_or_create_bot_state"
Cohesion: 0.17
Nodes (20): close_position(), create_trade(), get_or_create_bot_state(), get_trades(), Position, datetime, Modelos SQLAlchemy y gestión de sesiones para SQLite. Todos los importes usan D, Estado actual de cada posición abierta. (+12 more)

### Community 25 - "fetch_historical_bars"
Cohesion: 0.14
Nodes (26): backtest(), baselines(), Typer, Comandos de backtest y validación: backtest, walk-forward, baselines, sensitivit, Compara la estrategia Pro Trend contra baselines simples.      Baselines imple, Backtest continuo de una estrategia.  Las posiciones se abren y cierran     úni, Sensitivity analysis de Pro Trend v12: barre un parametro a la vez     mantenie, Validacion walk-forward: entrena en un periodo y evalua en el siguiente. (+18 more)

### Community 26 - "stress_usdt_depeg.py"
Cohesion: 0.60
Nodes (4): main(), Stress test de depeg USDT para Swing Allocator (F16).  Uso:     python tools/, _run(), StressCase

### Community 27 - "SwingAllocatorBot"
Cohesion: 0.10
Nodes (12): Decimal, Gestiona la allocation BTC/USDT dinamicamente segun senales de mercado., Primera barra: comprar base_btc_pct del capital en BTC., Agrega deltas de senales sobre la base. Aplica hard limits.         Devuelve el, RiskManager del live/paper: bloquear solo compras si se supero perdida diaria., Control minimo F14: no operar con OHLCV ausente o precio anomalo.         SOLO, Identificador del bloque 4H UTC actual, p.ej. '2026-07-02T3' (12:00-15:59)., SwingAllocatorBot (+4 more)

### Community 28 - "load_settings"
Cohesion: 0.12
Nodes (30): _bool_env(), _decimal_env(), _int_env(), load_settings(), _optional(), _parse_pairs(), Decimal, Carga y valida la configuración desde .env. Importar `settings` en cualquier mó (+22 more)

### Community 29 - "test_telegram_remote.py"
Cohesion: 0.14
Nodes (22): _add_bot(), _row(), _snap(), _snap_full(), test_format_anomalies_empty_and_populated(), test_format_heartbeat_multi_summarizes_each_bot(), test_format_status_reports_alive_paused_and_stale(), test_pause_and_resume_commands_flip_is_active() (+14 more)

### Community 30 - "common.py"
Cohesion: 0.15
Nodes (25): _annual_returns_from_curve(), _btc_year_returns(), _pct(), _print_quarterly_table(), datetime, Decimal, _quarterly_breakdown(), Helpers compartidos por todos los comandos del CLI. (+17 more)

### Community 31 - "OKXClient"
Cohesion: 0.10
Nodes (10): OKXClient, datetime, Decimal, Interfaz unificada para OKX., Verifica y descuenta balance para una market order. Debe llamarse con el lock to, Verifica órdenes limit pendientes y ejecuta las que cruzan el precio actual., Establece el balance simulado para una moneda. Útil para tests y backtest., Retorna copia de las órdenes limit pendientes en paper mode. (+2 more)

### Community 32 - "paper_snapshot.py"
Cohesion: 0.17
Nodes (21): build_snapshots(), discover_bots(), filter_bot_rebalances(), next_4h_eval(), paper_state_path_for(), perf_ratio(), datetime, Decimal (+13 more)

### Community 33 - "swing_benchmarks.py"
Cohesion: 0.45
Nodes (13): BenchResult, _buy(), _dca_weekly(), _df_from_bars(), _ema200_longflat(), main(), _metrics(), _monthly_6040() (+5 more)

### Community 34 - "RangeReversionBot"
Cohesion: 0.20
Nodes (4): Decimal, RangeReversionBot, RangeReversionConfig, Mean reversion con gate de regimen ADX.      Estado persistido:     {

### Community 35 - "test_paper_bots.py"
Cohesion: 0.15
Nodes (20): _bots(), test_bot_label_prefers_instance_id_then_name_then_legacy(), test_filter_rebalances_by_strategy(), test_paper_state_path_isolated_vs_legacy(), test_resolve_bot_by_label_and_substring_and_ambiguity(), test_safe_state_name_matches_exchange_rules(), bot_label(), filter_rebalances() (+12 more)

### Community 36 - "_esc"
Cohesion: 0.16
Nodes (25): test_parse_daily_checks_and_streak(), _bots_hint(), _pick_single(), Resuelve UN bot. Devuelve el dict, o un str de error/ayuda listo para responder., _bot_row(), _bot_status_icon(), _esc(), format_heartbeat_multi() (+17 more)

### Community 37 - "ema"
Cohesion: 0.13
Nodes (12): AdaptiveTrendBot, AdaptiveTrendConfig, Decimal, Adaptive Trend Following con detección de régimen.  Lógica en tres capas:  1, Trend follower con régimen adaptativo.      Estado persistido:     {, Descarga barras 1H, las resamplea a diario (excluyendo el día incompleto actual), detect_regime(), ema() (+4 more)

### Community 38 - "test_anomaly_check.py"
Cohesion: 0.16
Nodes (14): None = no evaluado (p.ej. dev sin cron) -> no debe fabricar una alerta falsa., Regresion 2026-07-11: el cron perdio +x 5 dias y /parity seguia mostrando 'OK' e, _snap(), test_alerts_sorted_by_severity(), test_clean_snapshot_no_alerts(), test_daily_check_fresh_not_flagged(), test_daily_check_none_not_flagged(), test_daily_check_stale_flagged() (+6 more)

### Community 39 - "test_backtest_pnl.py"
Cohesion: 0.23
Nodes (14): BacktestTrade, Alias de compatibilidad: desde 2026-07-02 el default es ACB., Pairing antiguo (pre-auditoria 2026-07-02): asocia cada venta con la compra abie, _bar(), Tests del pairing de P&L por trade (fix auditoria 2026-07-02, hallazgo B3).  _, _t(), test_coste_medio_pondera_compras(), test_market_fill_default_usa_close_actual() (+6 more)

### Community 40 - "live_cmds.py"
Cohesion: 0.24
Nodes (16): _load_settings(), _make_client(), dashboard(), mode(), Typer, Comandos de operación live/paper: start, stop, status, dashboard, mode., Parada de emergencia: cancela órdenes y desactiva todos los bots., Muestra el estado actual: bots, balance y posiciones abiertas. (+8 more)

### Community 41 - "registry.py"
Cohesion: 0.16
Nodes (14): Any, Registro central de estrategias.  Para añadir una nueva estrategia:   1. Crea, Resuelve un nombre de BotState como 'swing_allocator_btc_usdt'     buscando por, Devuelve (BotClass, ConfigClass) importando el módulo bajo demanda., Construye el objeto Config con símbolo y overrides de --config., Instancia el Bot con su config ya construida., resolve(), StrategyMeta (+6 more)

### Community 42 - "tg_charts.py"
Cohesion: 0.19
Nodes (18): test_build_equity_series_reconstructs_holdings(), build_equity_series(), _date_axis(), _dates(), _event_markers(), fetch_candles(), _fig_ax(), _fmt_dollar_axis() (+10 more)

### Community 43 - "forward_report.py"
Cohesion: 0.19
Nodes (17): forward_report(), Reporte que SOLO usa datos posteriores al inicio del forward-test., _bot_forward_metrics(), build_forward_report(), _drawdown_from_series(), _fmt(), _forward_only(), _parse_ts() (+9 more)

### Community 44 - "BTC Swing Allocator — Plan de Diseño"
Cohesion: 0.06
Nodes (35): 10. Cronograma sugerido, 11. Criterio de go/no-go, 1. Por qué Pro Trend no puede cumplir este objetivo, 2. Concepto central — lo que cambia radicalmente, 3. Constraint de costes — lo más importante, 4. Lo que sabemos que funciona (de Pro Trend), 5.1 Lógica de asignación, 5.2 Reglas de ejecución (+27 more)

### Community 45 - "test_paper_snapshot.py"
Cohesion: 0.14
Nodes (6): _FakeBot, _FakeQuery, _FakeSession, test_build_snapshots_marks_stale_and_computes_metrics(), test_read_paper_balances_parses_decimals(), _write_wallet()

### Community 46 - "swing_chart.py"
Cohesion: 0.18
Nodes (17): build_html(), build_presets(), load_bars(), load_journal(), main(), marker_data(), phase_bands(), Path (+9 more)

### Community 47 - "get_session"
Cohesion: 0.17
Nodes (20): bot_add(), bot_disable(), bot_enable(), bot_list(), Typer, Sub-comandos de gestión de bots: bot list/enable/disable/add., Lista todos los bots configurados en la DB., Activa un bot (lo crea si no existe). (+12 more)

### Community 48 - "exchange.py"
Cohesion: 0.13
Nodes (14): Settings, ExchangeError, ExchangeUnavailable, _order_result_to_dict(), _RateLimiter, Cliente OKX: REST live y simulacion paper., Error retornado por la API de OKX (código != 0)., Exchange no alcanzable: timeout, sin conexión, 5xx. (+6 more)

### Community 49 - "report_cmds.py"
Cohesion: 0.27
Nodes (8): Typer, Comandos de reporting: trades, report (fiscal IRPF)., Muestra el historial de trades recientes., Genera el informe fiscal IRPF para el año indicado (Excel + JSON)., register(), report(), trades(), OKX Trading Bot — CLI principal.  Uso:     python main.py start

### Community 50 - "explain"
Cohesion: 0.18
Nodes (16): explain(), Explica en texto plano UN rebalanceo ya ejecutado (lee swing_rebalances.jsonl)., Mismo bug de fondo que registry.resolve() (2026-07-11): un prefijo corto no debe, test_explain_rebalance_no_signals(), test_explain_rebalance_renders_readable_block(), test_explain_signal_handles_dynamic_suffix(), test_explain_signal_prefers_longest_match(), test_explain_signal_unknown_code_is_labeled_not_silently_ignored() (+8 more)

### Community 51 - "FundingExtremeBot"
Cohesion: 0.15
Nodes (12): build_funding_signals(), FundingExtremeBot, DataFrame, datetime, Long paga rate>0 / cobra rate<0 sobre el notional en cada settlement., Consume senales con settlement <= ts y programa la entrada con su delay., [(ts_ms, "hi"|"lo")] deduplicado. Umbral = percentil trailing shift(1):     el, _rows() (+4 more)

### Community 52 - "test_monthly_dist.py"
Cohesion: 0.27
Nodes (13): _dt(), Tests de tools/monthly_dist.py (plan income M0)., test_monthly_returns_basic_and_carry_forward(), test_monthly_returns_empty_and_inverted_range(), test_summarize_counts_positive_months_and_streak(), main(), _month_key(), monthly_returns() (+5 more)

### Community 53 - "BotState"
Cohesion: 0.25
Nodes (5): BotState, Configuración y estado persistente de cada bot activo., Cancela TODAS las órdenes abiertas y desactiva todos los bots en DB., _insert_bot_state(), test_emergency_stop_deactivates_all_bots()

### Community 54 - "alpha_screens.py"
Cohesion: 0.32
Nodes (13): consistency(), fetch_funding(), load_ohlcv(), main(), DataFrame, Series, N2 (PLAN B, HYROTRADER_PLAN seccion 13) — screens de alfa NO-indicador sobre dat, Funding por settlement desde BYBIT (exchange objetivo; OKX solo sirve ~3 meses). (+5 more)

### Community 55 - "bybit_public_cost_probe.py"
Cohesion: 0.36
Nodes (13): _d(), _depth_within(), _fetch_orderbook(), _fmt_bps(), _fmt_usdt(), main(), _pct(), _print_report() (+5 more)

### Community 57 - "trade_journal.py"
Cohesion: 0.24
Nodes (12): _as_float(), _augment_true_pnl(), _compute_stats(), Trade Journal — registro exhaustivo de cada operación con todos los indicadores,, Convierte cualquier valor a tipo JSON-serializable de forma recursiva., Escribe el journal completo a un archivo JSON.     Devuelve la ruta del archivo, PnL real del trade completo, incluyendo partial exits si el balance esta disponi, Anade campos de PnL real sin eliminar el PnL del cierre final. (+4 more)

### Community 58 - "swing_parity_check.py"
Cohesion: 0.67
Nodes (3): _bars_from_df(), main(), Check puntual de paridad Swing: OKXClient vs BacktestClient con las mismas velas

### Community 59 - "get_market_context"
Cohesion: 0.25
Nodes (10): _fetch_yahoo(), _fetch_yahoo_csv(), _fetch_yahoo_json(), get_market_context(), datetime, Contexto de mercado global — DXY (índice dólar) y NASDAQ-100.  Usado como filt, Devuelve el contexto de mercado global para la fecha dada.      Returns:, Intenta descargar via v8 JSON endpoint. (+2 more)

### Community 60 - "load_funding_history"
Cohesion: 0.31
Nodes (8): _fetch_page(), get_funding_rate_at(), load_funding_history(), datetime, Historial de funding rates de OKX para backtesting.  OKX perpetual swaps liqui, Devuelve la tasa de funding media del dia ANTERIOR completo.      OKX liquida, Descarga una pagina de hasta 100 registros de funding historico., Descarga el historico de funding rates para 'symbol' en el rango dado.      sy

### Community 62 - "bootstrap_equity.py"
Cohesion: 0.44
Nodes (8): main(), _max_dd(), _monthly_return_blocks(), _percentile(), datetime, Decimal, Bootstrap por bloques mensuales de la equity Swing v4.  Uso:     python tools, _run_v4()

### Community 63 - "Via A — EXP-011: funding_extreme como vehiculo propio (sin corse prop)"
Cohesion: 0.08
Nodes (23): A0 — Sanity de reproduccion (1 run), A1 — Quitar limites prop (1 run, cambio AISLADO), A2 — Sensibilidad de riesgo (2 runs, aislados sobre el ganador de A0 vs A1), A3 — Confirmacion en costes conservadores (1 run), A4 — OOS 2026 (1 run, solo lectura) — BLOQUEADO 2026-07-13, A5 — Camino a paper (SOLO si pasa el gate; NO empezar antes), B0 — PRE-REGISTRO (esto es el registro; no se toca tras el primer run), B1 — Implementacion (1 dia) (+15 more)

### Community 64 - "swing_v5_freeze_report.py"
Cohesion: 0.29
Nodes (10): Anchor, _btc_ratio(), main(), print_report(), BacktestClient, datetime, Anchor report for Swing Allocator v5 post-audit freeze.  Usage:     python to, _run() (+2 more)

### Community 65 - "test_data_audit.py"
Cohesion: 0.54
Nodes (6): _meta(), _row(), test_audit_clean_contiguous_cache(), test_audit_detects_duplicates(), test_audit_detects_high_below_low_and_hard_jump(), test_format_report_runs()

### Community 66 - "swing_audit_variants.py"
Cohesion: 0.48
Nodes (6): main(), datetime, Checks aislados de limpieza para Swing v4 (F8/F9/F10).  Uso:     python tools, _run(), VariantCase, _warmup_bars()

### Community 67 - "journal_summary.py"
Cohesion: 0.70
Nodes (4): _dump_section(), _fmt(), main(), _resolve_latest()

### Community 68 - "MacroContext"
Cohesion: 0.21
Nodes (12): date, get_macro_signal(), MacroContext, datetime, Contexto macro para BTC/ETH/SOL/BNB: MVRV ratio y ciclo de halving.  Fuentes d, Descarga datos MVRV diarios de CoinMetrics para el rango dado.         Si el ra, Busca un valor en un dict por fecha, retrocediendo hasta 7 dias.          Empi, Precio Realizado BTC: precio promedio al que el mercado 'compro' BTC.         S (+4 more)

### Community 69 - "degradation_report.py"
Cohesion: 0.67
Nodes (3): main(), _quarter(), Reporte de degradacion para Swing paper/live (F19).  Uso:     python tools/de

### Community 70 - "Python Runtime Dependencies"
Cohesion: 0.67
Nodes (3): Async HTTP and WebSocket Stack, CLI and Reporting Stack, Python Runtime Dependencies

### Community 72 - "buildView"
Cohesion: 0.67
Nodes (3): bucketKey, buildView, setTF

### Community 73 - "buildView"
Cohesion: 0.67
Nodes (3): bucketKey, buildView, setTF

### Community 90 - "HYROTRADER_PLAN.md — Estrategia prop firm (HyroTrader/Bybit)"
Cohesion: 0.07
Nodes (26): 0. REGLAS DE HYROTRADER (segun brief de Matias, 2026-07-03 — verificar en P0), 10. H1 — RE-MEDICION POST-CHECKPOINT (2026-07-03, sesion 17), 11. H2/H3 — SHORTS Y MULTI-SIMBOLO (2026-07-03, sesion 17, OK de Matias), 12. RUNS FINALES Y VEREDICTO DE CIERRE (2026-07-03, sesion 17), 13. PLAN B — REMAKE (2026-07-03, sesion 17 bis; decision de Matias: no matar el proyecto), 14. E9 COMO ESTRATEGIA STANDALONE — COMPARATIVA vs SWING v5 (2026-07-03), 15. N4 — MOTOR "FUNDING-EXTREME LONG" MEDIDO Y RECHAZADO COMO PROP (2026-07-04, sesion 18), 16. N0-LITE — COSTE PUBLICO BYBIT SIN CUENTA (2026-07-04) (+18 more)

### Community 91 - "prop_breach_audit.py"
Cohesion: 0.32
Nodes (11): closed_trades_between(), main(), datetime, run_backtest(), trade_pnl(), Return [(label, cfg, two_step)] for the selected prop-firm rule model., rule_configs(), main() (+3 more)

### Community 92 - "simulate_challenges"
Cohesion: 0.18
Nodes (18): _as_float_curve(), ChallengeResult, ChallengeStats, evaluate_two_step(), datetime, Decimal, Simulador de reglas de prop firm (HyroTrader) sobre curvas de equity.  P1 de H, Simula fase 1 y, si pasa, fase 2 desde la barra siguiente. PASSED = ambas. (+10 more)

### Community 93 - "MatiTradingBot — CLAUDE.md"
Cohesion: 0.25
Nodes (7): ARQUITECTURA BACKTEST (resumen), COMANDOS PRINCIPALES, CONVENCIONES CRITICAS, ESTILO Y CONVENCIONES (heredadas — el plugin ECC esta DESACTIVADO en este proyecto), MatiTradingBot — CLAUDE.md, REGLAS DE COMPORTAMIENTO, STACK Y ESTRUCTURA

### Community 95 - "SESSION_ARCHIVE.md — Historial completo y referencia detallada"
Cohesion: 0.13
Nodes (15): ADAPTIVE TREND (adaptive_trend.py), DATOS EXTERNOS, EVOLUCION PRO TREND, FUNDING CONTEXT (funding_context.py), INDICADORES (strategies/indicators.py — UNICO modulo activo), JOURNAL (reporting/trade_journal.py), LO QUE NO HA FUNCIONADO, MACRO CONTEXT (macro_context.py) (+7 more)

### Community 97 - "prop_phase_matrix.py"
Cohesion: 0.24
Nodes (16): Ajusta los umbrales de fase. Solo para sensitivity/ablation — no cambiar en prod, set_phase_bounds(), Candidate, _e9(), main(), make_phase_filter(), parse_candidates(), parse_phase_cases() (+8 more)

### Community 99 - "handle_command"
Cohesion: 0.16
Nodes (19): Regresion 2026-07-11: el cron perdio +x 5 dias; /parity mostraba 'OK' en verde s, test_format_parity_flags_stale_check(), cmd_audit(), cmd_logs(), cmd_restart(), cmd_signals(), cmd_update(), fetch_price() (+11 more)

### Community 100 - "RiskManager"
Cohesion: 0.19
Nodes (6): Decimal, Suma el PnL realizado de hoy desde la DB.         Retorna (limite_alcanzado: bo, Retorna (True, "") si la operación está permitida.         Retorna (False, "raz, Kelly Criterion simplificado.          Fórmula:             risk_amount  = ac, RiskManager, ScalpMomentumConfig

### Community 102 - "prop_phase_frontier.py"
Cohesion: 0.33
Nodes (10): main(), make_phase_filter(), parse_floats(), parse_windows(), phase_of(), Any, datetime, run_cell() (+2 more)

### Community 103 - "anomaly_check.py"
Cohesion: 0.23
Nodes (13): Alert, check_anomalies(), daily_check_age_minutes(), filter_new_alerts(), format_alert_line(), _liveness(), datetime, Decimal (+5 more)

### Community 104 - "SESSION.md — Estado del proyecto (HOT — se carga en cada sesion via @SESSION.md)"
Cohesion: 0.33
Nodes (5): DONDE ESTA CADA COSA (referencia rapida, sin abrir el archivo), ESTADO ACTUAL, PENDIENTES ABIERTOS, SESSION.md — Estado del proyecto (HOT — se carga en cada sesion via @SESSION.md), SIGUIENTE PASO — Swing Allocator (foco unico)

### Community 109 - "swing_ablation_matrix.py"
Cohesion: 0.36
Nodes (9): _btc_ratio(), ConfigCase, main(), BacktestClient, datetime, Ablations minimas del Swing Allocator para el plan de auditoria.  Uso:     py, _run(), _warmup_bars() (+1 more)

### Community 110 - "v6-2 Adoption Decision"
Cohesion: 0.06
Nodes (64): Mati Swing Validator Interface, Live Confirmation Gate, MatiTradingBot — AGENTS.md, Swing Allocator v6-2 Frozen Default, Swing Comparison Protocol, Registro de versiones de estrategias, Swing Allocator v5, Swing Allocator v6 (+56 more)

### Community 111 - "PROXIMOS PASOS (orden estricto — no cambiar parametros antes de completarlos)"
Cohesion: 0.22
Nodes (9): 1. Baselines ✅ COMPLETADO (2026-06-26), 2. ETH backtest ✅ COMPLETADO (2026-06-26), 3. Sensitivity analysis ✅ COMPLETADO (2026-06-29) — ADX re-corrido con bug fix, partial_exit confirmado, 4. Journal MAE/MFE/R-multiplo ✅ COMPLETADO (2026-06-29), 5. Partial exit ablation ✅ COMPLETADO (2026-06-30) — DEFAULT 150%, REVALIDAR 200%, 6. BTC 2015-2026 ✅ COMPLETADO (2026-06-30) — 3 ciclos bull validados, 7. Paper trading Pro Trend — SIGUIENTE PASO OBLIGATORIO, 8. Swing Allocator v1 — ADOPTADO COMO DEFAULT ✅ (2026-06-30) (+1 more)

### Community 112 - "SWING ALLOCATOR — REFERENCIA"
Cohesion: 0.22
Nodes (9): Archivos, BUGS RESUELTOS (no re-investigar), Comando de referencia, Concepto, Fixes implementados (2026-06-30), Mecanismo por fases, Por que gana a B&H, SWING ALLOCATOR — REFERENCIA (+1 more)

### Community 114 - "REFACTOR_BACKLOG.md — Limpieza y refactor (post-paper)"
Cohesion: 0.25
Nodes (7): Arquitectura — lo que YA es escalable (NO reconstruir), Codigo muerto confirmado — HECHO (commit `5ec7a97`, 2026-07-06), REFACTOR_BACKLOG.md — Limpieza y refactor (post-paper), Refactor del nucleo (SOLO post-paper, con red de tests + smoke de ancla en verde cada paso), Regla de oro de esta limpieza, Reorganizacion diferida (requiere auditar referencias — cron VM + skills usan rutas), Ya hecho (2026-07-06, riesgo cero)

### Community 115 - "PRO TREND v12 — REFERENCIA COMPLETA"
Cohesion: 0.25
Nodes (8): 13 gates de entrada long (en orden), Cache de indicadores, Cooldown (date-based, no barras), PRO TREND v12 — REFERENCIA COMPLETA, ProTrendConfig — valores actuales v13, Shorts sinteticos (allow_shorts=True), Sistema de puntuacion long (max ~14 pts), Sizing adaptativo

### Community 120 - "REGLAS INVARIANTES ANTES DE TOCAR CODIGO"
Cohesion: 0.25
Nodes (8): 1. Lookahead bias - tolerancia cero, 2. Overfitting - protocolo obligatorio, 3. Preservar Pro Trend v13 como rollback, 3. Preservar rollbacks, 4. Determinismo de datos, 4. Orden de trabajo tras esta auditoria, 5. Out-of-sample — ventana 2015-2026 CERRADA para optimizacion (auditoria 2026-07-02), REGLAS INVARIANTES ANTES DE TOCAR CODIGO

### Community 121 - "AUDITORIA 2026-06-30 - ROADMAP DE MEJORAS"
Cohesion: 0.40
Nodes (5): AUDITORIA 2026-06-30 - ROADMAP DE MEJORAS, Comandos de test a correr manualmente, Criterios de decision, Hallazgos criticos de lectura de codigo/journals, Orden recomendado de implementacion

### Community 122 - "RESULTADOS DE BACKTEST"
Cohesion: 0.40
Nodes (5): Baselines comparativos (realistic, 2018-2026) — CORREGIDOS 2026-06-26, Distribucion profit v12 (costes ideal), ETH Backtest (realistic, 2020-2026) — COMPLETADO 2026-06-26, RESULTADOS DE BACKTEST, Walk-Forward (realistic, 4 ventanas — 1 invalida)

### Community 123 - "OKXClient Connection Trace"
Cohesion: 0.67
Nodes (4): Direct Connection Inventory, OKXClient Connection Trace, Q: track all conections, Two-Hop Community Reach

### Community 124 - "Corrected v6-2 Adoption Decision"
Cohesion: 0.16
Nodes (17): Client Interface Contract Gap, Closed 2015-2026 Sample, Deferred Post-Paper Refactor, Funding Cache Stale Observability, Q: whats the next step with this info, can we optimize something else? or improve anything?, Reliability Before Strategy Optimization, Outcome: corrected and superseded, Later v6-2 Promotion Correction (+9 more)

### Community 127 - "test_client_contract.py"
Cohesion: 0.60
Nodes (4): _public_surface(), Contract shared by live, demo and backtest trading clients.  The strategies inte, test_all_clients_implement_strategy_contract(), test_client_specific_surface_is_explicit()

## Knowledge Gaps
- **187 isolated node(s):** `daily_checks.sh script`, `install_vm.sh script`, `setup_prop_cft_paper.sh script`, `okx-trader`, `PhasePolicy` (+182 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **43 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `OKXClient` connect `OKXClient` to `OHLCVBar`, `test_risk_manager.py`, `pro_trend.py`, `PropSwingBot`, `ProTrendBot`, `dashboard.py`, `_Session`, `ScalpMomentumBot`, `OKXDemoClient`, `BaseStrategy`, `test_exchange.py`, `common.py`, `RangeReversionBot`, `ema`, `live_cmds.py`, `exchange.py`, `FundingExtremeBot`, `ProTrendConfig`, `swing_parity_check.py`, `RiskManager`, `test_client_contract.py`?**
  _High betweenness centrality (0.103) - this node is a cross-community bridge._
- **Why does `BotState` connect `BotState` to `paper_snapshot.py`, `test_risk_manager.py`, `RiskManager`, `pro_trend.py`, `telegram_remote.py`, `PropSwingBot`, `live_cmds.py`, `dashboard.py`, `SwingAllocatorConfig`, `get_session`, `get_or_create_bot_state`, `test_telegram_remote.py`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Why does `BacktestClient` connect `BacktestClient` to `swing_v5_freeze_report.py`, `swing_benchmarks.py`, `OHLCVBar`, `swing_audit_variants.py`, `swing_parity_check.py`, `swing_v6_common.py`, `test_backtest_pnl.py`, `SwingAllocatorConfig`, `swing_ablation_matrix.py`, `report_common.py`, `prop_router_vs_swing.py`, `fetch_historical_bars`, `stress_usdt_depeg.py`, `prop_breach_audit.py`, `simulate_challenges`, `bootstrap_equity.py`, `test_client_contract.py`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Are the 20 inferred relationships involving `OKXClient` (e.g. with `Settings` and `OKXDemoClient`) actually correct?**
  _`OKXClient` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `SwingAllocatorBot` (e.g. with `BacktestClient` and `BlockingRisk`) actually correct?**
  _`SwingAllocatorBot` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `BacktestClient` (e.g. with `Base` and `OrderResult`) actually correct?**
  _`BacktestClient` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `BacktestEngine` (e.g. with `Base` and `OrderResult`) actually correct?**
  _`BacktestEngine` has 13 INFERRED edges - model-reasoned connections that need verification._