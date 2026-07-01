"""
MatiTradingBot — GUI Backtest Viewer
Migrates the terminal CLI backtest viewer to a dedicated GUI window using Tkinter.
Retains 100% of the behavior, style, and keyboard controls of the terminal version.
Optimized for high-speed scrolling and dynamic window resizing.
Integrates custom vector equity curve charts and guarantees no-overflow vertical layout.
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from io import StringIO
from pathlib import Path

# Tkinter imports
import tkinter as tk
from tkinter import messagebox
import tkinter.font as tkfont

# Third-party imports (assumes rich is installed)
try:
    from rich.align import Align
    from rich.box import ROUNDED, SIMPLE
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError:
    print("Error: The 'rich' library is required to run this script. Please run 'pip install rich'")
    sys.exit(1)

# Enable high-DPI awareness on Windows so text looks extremely crisp
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# Regular expression to parse ANSI escape sequences
ansi_re = re.compile(r'\x1b\[([0-9;]*)m')


def parse_date(date_str):
    """Safely parse various date string formats."""
    if not date_str:
        return None
    # Try parsing with full timezone first
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d%z"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
            
    # Try parsing without timezone or after stripping it
    clean_str = date_str.split("+")[0].split("Z")[0].split(".")[0]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(clean_str, fmt)
        except ValueError:
            continue
    return None


def format_datetime_to_dmy(ts_str) -> str:
    """Convert any ISO timestamp YYYY-MM-DDTHH:MM:SS... or datetime to DD-MM-YYYY HH:MM:SS."""
    if not ts_str or ts_str == "Unknown" or ts_str == "N/A":
        return ts_str
    if isinstance(ts_str, datetime):
        return ts_str.strftime("%d-%m-%Y %H:%M:%S")
    try:
        ts_str = str(ts_str)
        clean = ts_str.replace("T", " ").split("+")[0].split(".")[0]
        parts = clean.strip().split(" ")
        date_part = parts[0]
        date_subparts = date_part.split("-")
        if len(date_subparts) == 3 and len(date_subparts[0]) == 4:
            dmy = f"{date_subparts[2]}-{date_subparts[1]}-{date_subparts[0]}"
            if len(parts) > 1:
                return f"{dmy} {parts[1]}"
            return dmy
    except Exception:
        pass
    return str(ts_str)


class BacktestData:
    def __init__(self, filepath: Path, data: dict):
        self.filepath = filepath
        self.filename = filepath.name
        
        meta = data.get("meta", {})
        self.strategy = meta.get("strategy", "Unknown")
        self.symbol = meta.get("symbol", "Unknown")
        self.timeframe = meta.get("timeframe", "Unknown")
        
        # Period parsing
        self.period = meta.get("period")
        if self.period and "->" in self.period:
            parts = self.period.split("->")
            if len(parts) == 2:
                self.period = f"{format_datetime_to_dmy(parts[0].strip())} -> {format_datetime_to_dmy(parts[1].strip())}"
        else:
            from_d = meta.get("from_date")
            to_d = meta.get("to_date")
            if from_d and to_d:
                self.period = f"{format_datetime_to_dmy(from_d)} -> {format_datetime_to_dmy(to_d)}"
            else:
                self.period = "Unknown"
                
        self.cost_mode = meta.get("cost_mode", "Unknown")
        self.generated_at = format_datetime_to_dmy(meta.get("generated_at", ""))
        
        # Determine strategy type
        self.is_swing = self.strategy.startswith("swing_allocator")
        
        # Statistics
        stats = data.get("statistics", {})
        backtest = meta.get("backtest", {})
        
        # Initial & Final Balance
        self.initial_balance = float(backtest.get("initial_balance") or stats.get("initial_balance_usdt") or 10000.0)
        self.final_balance = float(backtest.get("final_balance") or stats.get("final_balance_usdt") or 10000.0)
        
        # PnL %
        self.pnl_pct = float(backtest.get("total_return_pct") or stats.get("pnl_pct") or 0.0)
        if self.pnl_pct == 0.0 and self.initial_balance > 0:
            self.pnl_pct = ((self.final_balance - self.initial_balance) / self.initial_balance) * 100.0
            
        # CAGR %
        self.cagr = backtest.get("cagr_pct")
        if self.cagr is not None:
            self.cagr = float(self.cagr)
        else:
            # Estimate CAGR from period and returns
            from_date, to_date = None, None
            if "from_date" in meta and "to_date" in meta:
                from_date = str(meta["from_date"])
                to_date = str(meta["to_date"])
            elif "period" in meta and "->" in meta["period"]:
                parts = meta["period"].split("->")
                if len(parts) == 2:
                    from_date = parts[0].strip()
                    to_date = parts[1].strip()
            
            if from_date and to_date:
                fd = parse_date(from_date)
                td = parse_date(to_date)
                if fd and td:
                    years = (td - fd).days / 365.25
                    if years > 0 and self.initial_balance > 0 and self.final_balance > 0:
                        self.cagr = ((self.final_balance / self.initial_balance) ** (1 / years) - 1) * 100.0
            if self.cagr is None:
                self.cagr = 0.0
                
        # Max Drawdown
        self.max_dd = backtest.get("max_drawdown_pct") or stats.get("max_drawdown_pct") or 0.0
        self.max_dd = float(self.max_dd)
        
        # Profit Factor
        self.profit_factor = backtest.get("profit_factor") or stats.get("profit_factor") or 0.0
        self.profit_factor = float(self.profit_factor)
        
        # Trades / Rebalances Count
        if self.is_swing:
            self.total_trades = int(stats.get("total_rebalances") or len(data.get("rebalances", [])))
            self.win_rate = 0.0
        else:
            self.total_trades = int(backtest.get("total_trades") or stats.get("total_trades") or len(data.get("trades", [])))
            self.win_rate = float(backtest.get("win_rate_pct") or stats.get("win_rate_pct") or 0.0)
            
        # Raw Trades
        self.raw_trades = data.get("trades") or data.get("rebalances") or []
        
        self.from_date = parse_date(meta.get("from_date"))
        if not self.from_date and "period" in meta and "->" in meta["period"]:
            parts = meta["period"].split("->")
            if len(parts) == 2:
                self.from_date = parse_date(parts[0].strip())
                
        self.to_date = parse_date(meta.get("to_date"))
        if not self.to_date and "period" in meta and "->" in meta["period"]:
            parts = meta["period"].split("->")
            if len(parts) == 2:
                self.to_date = parse_date(parts[1].strip())


def get_equity_curve(bt: BacktestData) -> list[tuple[float, float, str]]:
    """Constructs an equity curve series: (timestamp, balance_usdt, date_str) from trades/rebalances."""
    points = []
    
    # Establish start datetime
    start_dt = bt.from_date
    if not start_dt and bt.raw_trades:
        first_item = bt.raw_trades[0]
        if bt.is_swing:
            start_dt = parse_date(first_item.get("timestamp"))
        else:
            start_dt = parse_date(first_item.get("open", {}).get("timestamp"))
            
    if not start_dt:
        start_dt = datetime(2018, 1, 1)
        
    start_ts = start_dt.timestamp()
    points.append((start_ts, bt.initial_balance, start_dt.strftime("%d-%m-%Y %H:%M")))
    
    current_bal = bt.initial_balance
    
    for item in bt.raw_trades:
        if bt.is_swing:
            ts_str = item.get("timestamp", "")
            dt = parse_date(ts_str)
            val = float(item.get("portfolio_usdt") or current_bal)
            current_bal = val
            if dt:
                points.append((dt.timestamp(), current_bal, dt.strftime("%d-%m-%Y %H:%M")))
        else:
            open_dt = parse_date(item.get("open", {}).get("timestamp"))
            close_dt = parse_date(item.get("close", {}).get("timestamp"))
            pnl_usdt = float(item.get("close", {}).get("true_pnl_usdt") or item.get("close", {}).get("pnl_usdt") or 0.0)
            
            # Step flat before trade closes
            if open_dt:
                points.append((open_dt.timestamp(), current_bal, open_dt.strftime("%d-%m-%Y %H:%M")))
            
            current_bal += pnl_usdt
            if close_dt:
                points.append((close_dt.timestamp(), current_bal, close_dt.strftime("%d-%m-%Y %H:%M")))
                
    # Sort points by timestamp to avoid rendering errors
    points.sort(key=lambda x: x[0])
    
    # End flat period
    end_dt = bt.to_date
    if not end_dt and bt.raw_trades:
        last_item = bt.raw_trades[-1]
        if bt.is_swing:
            end_dt = parse_date(last_item.get("timestamp"))
        else:
            end_dt = parse_date(last_item.get("close", {}).get("timestamp"))
            
    if end_dt:
        end_ts = end_dt.timestamp()
        if end_ts > points[-1][0]:
            points.append((end_ts, current_bal, end_dt.strftime("%d-%m-%Y %H:%M")))
            
    return points


# Drawing helpers that write to a string buffer instead of terminal stdout
def draw_header(console, title: str, subtitle: str = ""):
    """Draw a clean, beautiful header panel."""
    header_text = Text(title, style="bold cyan")
    if subtitle:
        header_text.append(f"\n{subtitle}", style="dim italic")
    
    panel = Panel(
        Align.center(header_text),
        box=ROUNDED,
        border_style="blue",
        padding=(0, 2)
    )
    console.print(panel)


def draw_backtests_table(
    console,
    backtests: list[BacktestData],
    selected_idx: int,
    scroll_offset: int,
    max_visible: int,
    sort_by: str
):
    """Draw the table containing all backtest runs, with pagination/scrolling."""
    table = Table(box=ROUNDED, border_style="dim blue", expand=True)
    table.add_column("", justify="center", width=2)
    table.add_column("Strategy", style="bold white")
    table.add_column("Symbol", justify="center")
    table.add_column("TF", justify="center")
    table.add_column("Period", justify="center", style="dim")
    table.add_column("PnL %", justify="right")
    table.add_column("CAGR %", justify="right")
    table.add_column("Max DD %", justify="right")
    table.add_column("PF", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("Win %", justify="right")
    table.add_column("Cost Mode", justify="center", style="dim")
    
    end_idx = min(len(backtests), scroll_offset + max_visible)
    for i in range(scroll_offset, end_idx):
        bt = backtests[i]
        is_selected = (i == selected_idx)
        marker = ">" if is_selected else " "
        row_style = "bold yellow on blue" if is_selected else ("dim" if bt.is_swing else "")
        
        # Colors based on performance
        pnl_color = "green" if bt.pnl_pct > 0 else ("red" if bt.pnl_pct < 0 else "white")
        cagr_color = "green" if bt.cagr > 0 else ("red" if bt.cagr < 0 else "white")
        
        pnl_str = f"[{pnl_color}]{bt.pnl_pct:+.2f}%[/{pnl_color}]"
        cagr_str = f"[{cagr_color}]{bt.cagr:+.2f}%[/{cagr_color}]"
        dd_str = f"[red]-{abs(bt.max_dd):.2f}%[/red]" if bt.max_dd != 0.0 else "N/A"
        pf_str = f"{bt.profit_factor:.2f}" if bt.profit_factor > 0 else "N/A"
        win_str = f"{bt.win_rate:.1f}%" if not bt.is_swing else "N/A"
        
        table.add_row(
            marker,
            bt.strategy,
            bt.symbol,
            bt.timeframe,
            bt.period,
            pnl_str,
            cagr_str,
            dd_str,
            pf_str,
            str(bt.total_trades),
            win_str,
            bt.cost_mode,
            style=row_style
        )
    
    console.print(table)
    
    # Scroll / count indicator
    total = len(backtests)
    console.print(f"[dim]Showing {scroll_offset + 1}-{end_idx} of {total} backtests | Sorted by: [bold yellow]{sort_by.upper()}[/bold yellow] (descending)[/dim]")


def draw_trades_table(
    console,
    bt: BacktestData,
    selected_idx: int,
    scroll_offset: int,
    max_visible: int
):
    """Draw the trades or rebalances list for the selected backtest."""
    title = f"Trades for {bt.strategy} ({bt.symbol} {bt.timeframe})"
    subtitle = f"Initial: ${bt.initial_balance:,.2f} -> Final: ${bt.final_balance:,.2f} ({bt.pnl_pct:+.2f}%) | Total: {bt.total_trades}"
    draw_header(console, title, subtitle)
    
    table = Table(box=ROUNDED, border_style="dim green", expand=True)
    table.add_column("", justify="center", width=2)
    
    if bt.is_swing:
        # Columns for Swing rebalances
        table.add_column("Num", justify="center")
        table.add_column("Timestamp", justify="center")
        table.add_column("Direction", justify="center")
        table.add_column("Price", justify="right")
        table.add_column("Qty", justify="right")
        table.add_column("BTC % Before", justify="right")
        table.add_column("BTC % After", justify="right")
        table.add_column("Portfolio Value", justify="right")
        table.add_column("Signals Triggered", style="dim")
        
        end_idx = min(len(bt.raw_trades), scroll_offset + max_visible)
        for i in range(scroll_offset, end_idx):
            reb = bt.raw_trades[i]
            is_selected = (i == selected_idx)
            marker = ">" if is_selected else " "
            row_style = "bold yellow on green" if is_selected else ""
            
            # Format fields
            num = str(reb.get("num", i + 1))
            ts = format_datetime_to_dmy(reb.get("timestamp", "Unknown"))
            dir_val = reb.get("direction", "Unknown")
            if dir_val == "BUY":
                dir_str = "[green]BUY[/green]"
            elif dir_val == "SELL":
                dir_str = "[red]SELL[/red]"
            else:
                dir_str = "[cyan]INIT[/cyan]"
                
            price = f"${reb.get('price', 0.0):,.2f}"
            qty = f"{reb.get('qty', 0.0):.6f}"
            pct_before = f"{reb.get('btc_pct_before', 0.0) * 100:.1f}%"
            pct_after = f"{reb.get('btc_pct_after', 0.0) * 100:.1f}%"
            portfolio = f"${reb.get('portfolio_usdt', 0.0):,.2f}"
            
            signals = ", ".join(reb.get("signals", []))
            
            table.add_row(
                marker, num, ts, dir_str, price, qty, pct_before, pct_after, portfolio, signals,
                style=row_style
            )
            
    else:
        # Columns for standard trades
        table.add_column("Trade #", justify="center")
        table.add_column("Side", justify="center")
        table.add_column("Open Time", justify="center")
        table.add_column("Open Price", justify="right")
        table.add_column("Close Time", justify="center")
        table.add_column("Close Price", justify="right")
        table.add_column("PnL USDT", justify="right")
        table.add_column("PnL %", justify="right")
        table.add_column("Exit Reason", style="dim")
        table.add_column("R Mult", justify="right")
        
        end_idx = min(len(bt.raw_trades), scroll_offset + max_visible)
        for i in range(scroll_offset, end_idx):
            trade = bt.raw_trades[i]
            is_selected = (i == selected_idx)
            marker = ">" if is_selected else " "
            row_style = "bold yellow on green" if is_selected else ""
            
            num = str(trade.get("trade_num", i + 1))
            side = trade.get("side", "long").upper()
            side_str = f"[green]{side}[/green]" if side == "LONG" else f"[red]{side}[/red]"
            
            open_data = trade.get("open", {})
            close_data = trade.get("close", {})
            
            open_ts = format_datetime_to_dmy(open_data.get("timestamp", "Unknown"))
            open_price = f"${open_data.get('price', 0.0):,.2f}"
            
            close_ts = format_datetime_to_dmy(close_data.get("timestamp", "Unknown"))
            close_price = f"${close_data.get('price', 0.0):,.2f}"
            
            pnl_usdt = close_data.get("true_pnl_usdt") or close_data.get("pnl_usdt") or 0.0
            pnl_pct = close_data.get("true_pnl_pct") or close_data.get("pnl_pct") or 0.0
            
            pnl_usdt_str = f"[green]+${pnl_usdt:,.2f}[/green]" if pnl_usdt >= 0 else f"[red]-${abs(pnl_usdt):,.2f}[/red]"
            pnl_pct_str = f"[green]+{pnl_pct:.2f}%[/green]" if pnl_pct >= 0 else f"[red]{pnl_pct:.2f}%[/red]"
            
            reason = close_data.get("reason", "Unknown")
            r_mult = trade.get("close", {}).get("r_multiple")
            r_mult_str = f"{r_mult:+.2f}R" if r_mult is not None else "N/A"
            
            table.add_row(
                marker, num, side_str, open_ts, open_price, close_ts, close_price, pnl_usdt_str, pnl_pct_str, reason, r_mult_str,
                style=row_style
            )
            
    console.print(table)
    total = len(bt.raw_trades)
    console.print(f"[dim]Showing {scroll_offset + 1}-{end_idx} of {total} items | Press [bold yellow]Enter[/bold yellow] to view item details, [bold yellow]C[/bold yellow] to see Equity Chart, [bold yellow]Esc[/bold yellow] to go back.[/dim]")


def draw_trade_detail(console, bt: BacktestData, idx: int):
    """Draw full indicators, gates, and metadata details for a single selected trade."""
    item = bt.raw_trades[idx]
    
    if bt.is_swing:
        # Swing Rebalance Detail View
        title = f"Swing Rebalance #{item.get('num', idx + 1)} Details"
        draw_header(console, title)
        
        main_table = Table(box=SIMPLE, border_style="dim green")
        main_table.add_column("Metric", style="bold cyan")
        main_table.add_column("Value")
        
        main_table.add_row("Timestamp", format_datetime_to_dmy(item.get("timestamp", "Unknown")))
        main_table.add_row("Direction", item.get("direction", "Unknown"))
        main_table.add_row("Execution Price", f"${item.get('price', 0.0):,.2f}")
        main_table.add_row("Quantity Traded", f"{item.get('qty', 0.0):.6f}")
        main_table.add_row("BTC Pct Before", f"{item.get('btc_pct_before', 0.0) * 100:.2f}%")
        main_table.add_row("BTC Pct Target", f"{item.get('btc_pct_target', 0.0) * 100:.2f}%")
        main_table.add_row("BTC Pct After", f"{item.get('btc_pct_after', 0.0) * 100:.2f}%")
        main_table.add_row("Portfolio Value (USDT)", f"${item.get('portfolio_usdt', 0.0):,.2f}")
        
        signals_list = item.get("signals", [])
        signals_str = ", ".join(signals_list) if signals_list else "None"
        main_table.add_row("Signals Active", signals_str)
        
        panel = Panel(main_table, border_style="cyan", title="Rebalance metrics")
        console.print(panel)
        
    else:
        # Standard Trade Detail View
        num = item.get("trade_num", idx + 1)
        side = item.get("side", "long").upper()
        draw_header(console, f"Trade #{num} Details — {side}")
        
        open_data = item.get("open", {})
        close_data = item.get("close", {})
        
        # 1. Overview Table
        overview = Table(box=SIMPLE, border_style="dim green", expand=True)
        overview.add_column("Property", style="bold cyan")
        overview.add_column("Entry Details")
        overview.add_column("Exit Details")
        
        pnl_usdt = close_data.get("true_pnl_usdt") or close_data.get("pnl_usdt") or 0.0
        pnl_pct = close_data.get("true_pnl_pct") or close_data.get("pnl_pct") or 0.0
        pnl_usdt_str = f"[green]+${pnl_usdt:,.2f}[/green]" if pnl_usdt >= 0 else f"[red]-${abs(pnl_usdt):,.2f}[/red]"
        pnl_pct_str = f"[green]+{pnl_pct:.2f}%[/green]" if pnl_pct >= 0 else f"[red]{pnl_pct:.2f}%[/red]"
        
        overview.add_row("Timestamp", format_datetime_to_dmy(open_data.get("timestamp", "N/A")), format_datetime_to_dmy(close_data.get("timestamp", "N/A")))
        overview.add_row("Price", f"${open_data.get('price', 0.0):,.2f}", f"${close_data.get('price', 0.0):,.2f}")
        overview.add_row("Qty / Invested", f"{open_data.get('qty', 0.0):.6f} / ${open_data.get('invest_usdt', 0.0):,.2f}", "")
        overview.add_row("Stop Loss / TP", f"SL: ${open_data.get('stop_loss', 0.0):,.2f} | TP: ${open_data.get('take_profit', 0.0):,.2f}", "")
        overview.add_row("Balance (Before/After)", f"${open_data.get('balance_usdt_before', 0.0):,.2f}", f"${close_data.get('balance_usdt_after', 0.0):,.2f}")
        overview.add_row("PnL / Return", "", f"{pnl_usdt_str} ({pnl_pct_str})")
        overview.add_row("Holding Time / Exit Reason", "", f"{close_data.get('holding_hours', 0.0):.1f} hours | Reason: [yellow]{close_data.get('reason', 'N/A')}[/yellow]")
        overview.add_row("MAE% / MFE% / R-Mult", "", f"MAE: {close_data.get('mae_pct', 0.0):.2f}% | MFE: {close_data.get('mfe_pct', 0.0):.2f}% | {close_data.get('r_multiple', 0.0):+.2f}R")
        
        console.print(Panel(overview, border_style="cyan", title="Trade Summary"))
        
        # 2. Indicators & Sizing Columns
        open_ind = open_data.get("indicators", {})
        close_ind = close_data.get("indicators", {})
        
        ind_table = Table(box=SIMPLE, border_style="dim green", expand=True)
        ind_table.add_column("Indicator", style="bold magenta")
        ind_table.add_column("Value at Entry")
        ind_table.add_column("Value at Exit")
        
        for ind_key in ["close", "rsi", "adx", "atr", "mvrv", "vix_level", "halving_phase", "weekly_trend_up", "h4_trend_bullish"]:
            val_open = open_ind.get(ind_key)
            val_close = close_ind.get(ind_key)
            if val_open is not None or val_close is not None:
                ind_table.add_row(
                    ind_key.upper().replace("_", " "),
                    str(val_open) if val_open is not None else "—",
                    str(val_close) if val_close is not None else "—"
                )
                
        # Sizing details
        sizing_data = open_ind.get("sizing")
        if sizing_data:
            ind_table.add_section()
            ind_table.add_row("[bold cyan]SIZING METRIC[/bold cyan]", "[bold cyan]VALUE[/bold cyan]", "")
            for skey, sval in sizing_data.items():
                ind_table.add_row(f"Sizing: {skey.replace('_', ' ')}", str(sval), "")
                
        ind_panel = Panel(ind_table, border_style="magenta", title="Indicators & Sizing Details")
        
        # 3. Entry Gates Checklist (if present)
        gates = open_ind.get("entry_gates")
        gates_panel = None
        if gates:
            gates_table = Table(box=SIMPLE, border_style="dim green", expand=True)
            gates_table.add_column("Entry Gate Name", style="bold yellow")
            gates_table.add_column("Status", justify="center")
            
            for gate_name, val in gates.items():
                if gate_name.startswith("g_"):
                    status = "[green][OK][/green]" if val else "[red][X][/red]"
                    gates_table.add_row(gate_name.replace("g_", "").upper(), status)
            
            gates_panel = Panel(gates_table, border_style="yellow", title="Entry Gates Checklist")
            
        # Place Indicators & Gates side-by-side to optimize vertical space and avoid scrollbars
        if gates_panel:
            side_by_side = Table.grid(expand=True)
            side_by_side.add_column(ratio=1)
            side_by_side.add_column(width=2)  # spacer
            side_by_side.add_column(ratio=1)
            side_by_side.add_row(ind_panel, "", gates_panel)
            console.print(side_by_side)
        else:
            console.print(ind_panel)

    console.print("[dim]Press [bold yellow]Esc[/bold yellow] to go back to trades list.[/dim]")


def draw_sort_menu(console, selected_idx: int):
    """Draw sorting overlay options with navigation highlight."""
    menu_text = Text()
    menu_text.append("\nSelect Metric to Sort descending:\n\n", style="bold yellow")
    
    options = [
        "PnL %",
        "CAGR %",
        "Profit Factor",
        "Total Trades",
        "Win Rate %",
        "Max Drawdown %",
        "Date (Generated At)"
    ]
    
    for i, opt in enumerate(options):
        if i == selected_idx:
            menu_text.append(f" > [{i+1}] {opt}\n", style="bold yellow on blue")
        else:
            menu_text.append(f"   [{i+1}] {opt}\n", style="white")
            
    menu_text.append("\nUse [↑/↓] to navigate & [Enter] to select, or press [1-7] directly.\n", style="dim")
    menu_text.append("Press Esc to cancel.", style="dim")
    
    panel = Panel(
        Align.center(menu_text),
        box=ROUNDED,
        border_style="yellow",
        title="Sort Options",
        padding=(1, 5)
    )
    console.print(panel)


def draw_chart_on_canvas(canvas, width, height, points, title, strategy_info, selected_idx=None):
    """Draw a vector equity curve chart resembling a dark-themed trading chart."""
    canvas.delete("all")
    canvas.configure(bg="#111111", highlightthickness=0)
    
    if not points:
        canvas.create_text(width // 2, height // 2, text="No equity data available", fill="#ff5555", font=("Consolas", 12, "bold"))
        return
        
    x_values = [p[0] for p in points]
    y_values = [p[1] for p in points]
    
    min_x = min(x_values)
    max_x = max(x_values)
    min_y = min(y_values)
    max_y = max(y_values)
    
    # Add a safety padding margin above and below Y-axis
    y_range = max_y - min_y
    if y_range == 0:
        y_range = 1000.0
    
    # Pad top
    max_y += y_range * 0.05
    
    # Pad bottom (only if it doesn't cross below 0 when all points are positive)
    if all(p[1] >= 0 for p in points):
        min_y = max(0.0, min_y - y_range * 0.05)
    else:
        min_y -= y_range * 0.05
        
    y_range = max_y - min_y
    
    x_range = max_x - min_x
    if x_range == 0:
        x_range = 86400.0 # 1 day in seconds
        
    margin_left = 95
    margin_right = 20
    
    if strategy_info:
        margin_top = 80
        margin_bottom = 60
    else:
        margin_top = 20
        margin_bottom = 35
        
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    
    def scale_x(ts):
        return margin_left + ((ts - min_x) / x_range) * plot_width
        
    def scale_y(val):
        return margin_top + plot_height - ((val - min_y) / y_range) * plot_height
        
    # 1. Draw Grid Lines (Solid, faint gray) & Labels
    grid_ticks = 5
    for i in range(grid_ticks):
        val = min_y + (i / (grid_ticks - 1)) * y_range
        y_px = scale_y(val)
        canvas.create_line(margin_left, y_px, width - margin_right, y_px, fill="#1c1c1c")
        canvas.create_text(margin_left - 10, y_px, text=f"${val:,.0f}", fill="#7f7f7f", anchor="e", font=("Consolas", 9))
        
    if x_range > 0:
        x_ticks = 6
        for i in range(x_ticks):
            ts = min_x + (i / (x_ticks - 1)) * x_range
            x_px = scale_x(ts)
            canvas.create_line(x_px, margin_top, x_px, height - margin_bottom, fill="#1c1c1c")
            # Format datetime safely to DD-MM-YYYY
            try:
                date_str = datetime.fromtimestamp(ts).strftime("%d-%m-%Y")
            except Exception:
                date_str = ""
            canvas.create_text(x_px, height - margin_bottom + 15, text=date_str, fill="#7f7f7f", anchor="n", font=("Consolas", 9))
            
    # 2. Draw outer boundary box (same blue style as other panels in the app)
    canvas.create_rectangle(
        margin_left,
        margin_top,
        width - margin_right,
        height - margin_bottom,
        outline="#777777",
        width=1
    )
    
    # 3. Draw the Equity Line (Vibrant Green or Red)
    is_positive = (points[-1][1] >= points[0][1])
    line_color = "#0dbc79" if is_positive else "#cd3131"
    line_coords = []
    for ts, val, _ in points:
        line_coords.append((scale_x(ts), scale_y(val)))
        
    flat_line = [coord for pt in line_coords for coord in pt]
    if len(flat_line) >= 4:
        canvas.create_line(flat_line, fill=line_color, width=1.2)
        
    # Draw point markers if count is small (to feel interactive)
    if len(points) < 80:
        for ts, val, _ in points:
            cx = scale_x(ts)
            cy = scale_y(val)
            canvas.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill=line_color, outline="#111111")
            
    # Draw selected point marker (White Dot)
    if selected_idx is not None and 0 <= selected_idx < len(points):
        sel_point = points[selected_idx]
        cx = scale_x(sel_point[0])
        cy = scale_y(sel_point[1])
        canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="#ffffff", outline="#111111", width=1.5)
            
    # 4. Draw Header/Metadata Info
    if title:
        canvas.create_text(margin_left, 30, text=title, fill="#ffffff", anchor="w", font=("Consolas", 14, "bold"))
    if strategy_info:
        canvas.create_text(margin_left, 55, text=strategy_info, fill=line_color, anchor="w", font=("Consolas", 10, "bold"))
        
    # 5. Draw Footer Controls
    if strategy_info:
        canvas.create_text(width // 2, height - 25, text="Controls: [Esc] Return to backtest viewer", fill="#e5e510", anchor="center", font=("Consolas", 10, "bold"))


# Text tag parser to map ANSI codes to Tkinter text styles (re-uses preconfigured styles for speed)
def insert_ansi_to_text_widget(text_widget, ansi_text, append=False):
    text_widget.configure(state='normal')
    if not append:
        text_widget.delete('1.0', 'end')
    
    last_idx = 0
    current_tags = []
    
    # Parse text chunks
    for match in ansi_re.finditer(ansi_text):
        start, end = match.span()
        if start > last_idx:
            chunk = ansi_text[last_idx:start]
            text_widget.insert('end', chunk, tuple(current_tags))
            
        codes = match.group(1).split(';')
        for code in codes:
            if not code or code == '0':
                current_tags = []
            elif code == '1':
                current_tags.append('bold')
            elif code == '2':
                current_tags.append('dim')
            elif code == '22':
                current_tags = [t for t in current_tags if t != 'bold' and t != 'dim']
            elif code.startswith('3'):
                if code == '39':
                    current_tags = [t for t in current_tags if not t.startswith('fg_')]
                else:
                    current_tags = [t for t in current_tags if not t.startswith('fg_')]
                    current_tags.append(f'fg_{code}')
            elif code.startswith('9'):
                current_tags = [t for t in current_tags if not t.startswith('fg_')]
                current_tags.append(f'fg_{code}')
            elif code.startswith('4'):
                if code == '49':
                    current_tags = [t for t in current_tags if not t.startswith('bg_')]
                else:
                    current_tags = [t for t in current_tags if not t.startswith('bg_')]
                    current_tags.append(f'bg_{code}')
            elif code.startswith('10'):
                current_tags = [t for t in current_tags if not t.startswith('bg_')]
                current_tags.append(f'bg_{code}')
                
        last_idx = end
        
    if last_idx < len(ansi_text):
        text_widget.insert('end', ansi_text[last_idx:], tuple(current_tags))
        
    text_widget.configure(state='disabled')


class BacktestViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MatiTradingBot — Backtest Viewer Window")
        self.root.configure(bg="#111111")
        
        # Default window sizing
        self.root.geometry("1150x850")
        self.root.minsize(800, 500)
        
        # project directory mapping
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent
        self.backtests_dir = project_root / "backtests"
        
        # State variables
        self.state = "list"  # "list", "sort_menu", "trades", "trade_detail", "chart"
        self.previous_state = "list"
        self.backtests: list[BacktestData] = []
        self.sort_by = "date"
        
        # Offsets
        self.selected_backtest_idx = 0
        self.backtest_scroll_offset = 0
        self.selected_sort_idx = 0
        self.selected_trade_idx = 0
        self.trade_scroll_offset = 0
        self.selected_chart_idx = 0
        self.chart_points = []
        
        # Console dimension trackers
        self.last_width = 1150
        self.last_height = 850
        
        # Throttling/Debouncing variables for key-repeats
        self.last_render_time = 0.0
        self._render_job = None
        
        # Create single Text display area (no-wrap to prevent table layout wrapping errors)
        self.text_display = tk.Text(
            self.root,
            bg="#111111",
            fg="#e5e5e5",
            insertbackground="#ffffff",
            font=("Consolas", 10),
            bd=0,
            highlightthickness=0,
            padx=15,
            pady=15,
            wrap="none"
        )
        self.text_display.pack(fill="both", expand=True)
        
        # Disable default mousewheel scrolling so it is completely controlled and menus never shift out of view
        self.text_display.bind("<MouseWheel>", lambda e: "break")
        
        # Create Vector Chart Canvas (parented to root to avoid destruction on text deletion)
        self.chart_canvas = tk.Canvas(
            self.root,
            bg="#111111",
            highlightthickness=0
        )
        
        # Configure fonts and measure width/height for exact window fit
        self.main_font = tkfont.Font(family="Consolas", size=10)
        self.char_width = self.main_font.measure("A")
        self.line_height = self.main_font.metrics("linespace")
        
        # Calculate initial characters rows/columns to fit perfectly (added extra safe padding of 90px to protect footers)
        self.console_cols = max(80, (self.last_width - 30) // self.char_width)
        self.console_rows = max(10, (self.last_height - 90) // self.line_height)
        
        # Define and configure all ANSI tag configurations ONCE on startup (enormous lag reduction)
        self.preconfigure_tags()
        
        # Rich console to buffer ANSI output
        self.string_io = StringIO()
        self.rich_console = Console(
            file=self.string_io,
            color_system="standard",
            force_terminal=True,
            width=self.console_cols
        )
        
        # Bind keyboard events
        self.root.bind("<Up>", lambda e: self.handle_key("up"))
        self.root.bind("<Down>", lambda e: self.handle_key("down"))
        self.root.bind("<Left>", lambda e: self.handle_key("left"))
        self.root.bind("<Right>", lambda e: self.handle_key("right"))
        self.root.bind("<Return>", lambda e: self.handle_key("enter"))
        self.root.bind("<Escape>", lambda e: self.handle_key("esc"))
        self.root.bind("<Key>", self.handle_char_key)
        self.root.bind("<Configure>", self.on_window_resize)
        
        # Load the files
        self.load_journals()
        
    def preconfigure_tags(self):
        """Configure standard terminal colors once at startup to optimize rendering speed."""
        colors = {
            'fg_30': '#000000',  # black
            'fg_31': '#cd3131',  # red
            'fg_32': '#0dbc79',  # green
            'fg_33': '#e5e510',  # yellow
            'fg_34': '#2472c8',  # blue
            'fg_35': '#bc3fbc',  # magenta
            'fg_36': '#11a8cd',  # cyan
            'fg_37': '#e5e5e5',  # white
            
            # Bright fg colors
            'fg_90': '#7f7f7f',  # gray / dim
            'fg_91': '#f14c4c',
            'fg_92': '#23d18b',
            'fg_93': '#f5f543',
            'fg_94': '#3b8eea',
            'fg_95': '#d670d6',
            'fg_96': '#29b8db',
            'fg_97': '#ffffff',
            
            # Background highlights
            'bg_44': '#1e3a8a',   # Selection dark blue highlight
            'bg_104': '#2472c8',
        }
        
        for tag_name, color in colors.items():
            if tag_name.startswith('fg_'):
                self.text_display.tag_configure(tag_name, foreground=color)
            elif tag_name.startswith('bg_'):
                self.text_display.tag_configure(tag_name, background=color)
                
        # Fonts configurations
        self.text_display.tag_configure('bold', font=("Consolas", 10, "bold"))
        self.text_display.tag_configure('dim', foreground='#7f7f7f')
        
    def load_journals(self):
        """Scan and load all journals from backtests folder."""
        if not self.backtests_dir.exists():
            messagebox.showerror("Error", f"Backtests directory not found at {self.backtests_dir}")
            self.root.destroy()
            return
            
        json_files = list(self.backtests_dir.glob("journal_*.json"))
        if not json_files:
            messagebox.showinfo("No Data", f"No backtest journals (journal_*.json) found in {self.backtests_dir.name}")
            self.root.destroy()
            return
            
        for fp in json_files:
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "meta" in data:
                        self.backtests.append(BacktestData(fp, data))
            except Exception:
                pass
                
        if not self.backtests:
            messagebox.showerror("Error", "No valid backtest journals could be parsed.")
            self.root.destroy()
            return
            
        # Default sort by date descending
        self.backtests.sort(key=lambda x: x.generated_at or "", reverse=True)
        
        # Trigger initial draw
        self.re_render()
        
    def on_window_resize(self, event):
        """Recalculate characters lines/cols on window resize to wrap tables dynamically."""
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        
        # Only process if window is actual size (ignore initial layout artifacts)
        if width > 200 and height > 200:
            if abs(width - self.last_width) > 10 or abs(height - self.last_height) > 10:
                self.last_width = width
                self.last_height = height
                
                # Recalculate columns and rows exactly based on character font size
                # Added vertical height offset of 90px to prevent menus from going off screen
                self.console_cols = max(80, (width - 30) // self.char_width)
                self.console_rows = max(10, (height - 90) // self.line_height)
                
                self.rich_console.width = self.console_cols
                self.re_render()
            
    def handle_char_key(self, event):
        """Capture direct alphanumeric keys."""
        char = event.char.lower()
        if char == 's':
            self.handle_key('s')
        elif char == 'c':
            self.handle_key('c')
        elif char in ('1', '2', '3', '4', '5', '6', '7'):
            self.handle_key(char)
            
    def apply_sort(self, idx: int):
        """Execute selected sort descending."""
        if idx == 0:
            self.sort_by = "pnl"
            self.backtests.sort(key=lambda x: x.pnl_pct, reverse=True)
        elif idx == 1:
            self.sort_by = "cagr"
            self.backtests.sort(key=lambda x: x.cagr, reverse=True)
        elif idx == 2:
            self.sort_by = "pf"
            self.backtests.sort(key=lambda x: x.profit_factor, reverse=True)
        elif idx == 3:
            self.sort_by = "trades"
            self.backtests.sort(key=lambda x: x.total_trades, reverse=True)
        elif idx == 4:
            self.sort_by = "win_rate"
            self.backtests.sort(key=lambda x: x.win_rate, reverse=True)
        elif idx == 5:
            self.sort_by = "max_dd"
            self.backtests.sort(key=lambda x: x.max_dd, reverse=True)
        elif idx == 6:
            self.sort_by = "date"
            self.backtests.sort(key=lambda x: x.generated_at or "", reverse=True)
            
        self.selected_backtest_idx = 0
        self.backtest_scroll_offset = 0
        self.state = "list"
        
    def handle_key(self, key: str):
        """State machine navigation matching the CLI viewer."""
        rows = self.console_rows
        old_state = self.state
        old_idx = (self.selected_backtest_idx if self.state == "list"
                   else self.selected_trade_idx if self.state == "trades"
                   else self.selected_sort_idx if self.state == "sort_menu"
                   else self.selected_chart_idx if self.state == "chart"
                   else 0)
        
        if self.state == "list":
            if key == 'up':
                if self.selected_backtest_idx > 0:
                    self.selected_backtest_idx -= 1
                    max_visible = max(5, rows - 12)
                    if self.selected_backtest_idx < self.backtest_scroll_offset:
                        self.backtest_scroll_offset = self.selected_backtest_idx
            elif key == 'down':
                if self.selected_backtest_idx < len(self.backtests) - 1:
                    self.selected_backtest_idx += 1
                    max_visible = max(5, rows - 12)
                    if self.selected_backtest_idx >= self.backtest_scroll_offset + max_visible:
                        self.backtest_scroll_offset = self.selected_backtest_idx - max_visible + 1
            elif key == 'enter':
                bt = self.backtests[self.selected_backtest_idx]
                if bt.raw_trades:
                    self.state = "trades"
                    self.selected_trade_idx = 0
                    self.trade_scroll_offset = 0
            elif key == 's':
                self.state = "sort_menu"
                self.selected_sort_idx = 0
            elif key == 'c':
                self.previous_state = "list"
                self.state = "chart"
                self.selected_chart_idx = 0
                bt = self.backtests[self.selected_backtest_idx]
                self.chart_points = get_equity_curve(bt)
            elif key == 'esc':
                self.root.destroy()
                return
                
        elif self.state == "sort_menu":
            if key == 'esc':
                self.state = "list"
            elif key == 'up':
                if self.selected_sort_idx > 0:
                    self.selected_sort_idx -= 1
            elif key == 'down':
                if self.selected_sort_idx < 6:
                    self.selected_sort_idx += 1
            elif key == 'enter':
                self.apply_sort(self.selected_sort_idx)
            elif key in ('1', '2', '3', '4', '5', '6', '7'):
                self.apply_sort(int(key) - 1)
                
        elif self.state == "trades":
            bt = self.backtests[self.selected_backtest_idx]
            if key == 'up':
                if self.selected_trade_idx > 0:
                    self.selected_trade_idx -= 1
                    max_visible = max(5, rows - 12)
                    if self.selected_trade_idx < self.trade_scroll_offset:
                        self.trade_scroll_offset = self.selected_trade_idx
            elif key == 'down':
                if self.selected_trade_idx < len(bt.raw_trades) - 1:
                    self.selected_trade_idx += 1
                    max_visible = max(5, rows - 12)
                    if self.selected_trade_idx >= self.trade_scroll_offset + max_visible:
                        self.trade_scroll_offset = self.selected_trade_idx - max_visible + 1
            elif key == 'enter':
                self.state = "trade_detail"
            elif key == 'c':
                self.previous_state = "trades"
                self.state = "chart"
                self.selected_chart_idx = 0
                bt = self.backtests[self.selected_backtest_idx]
                self.chart_points = get_equity_curve(bt)
            elif key == 'esc':
                self.state = "list"
                
        elif self.state == "trade_detail":
            if key == 'esc':
                self.state = "trades"
                
        elif self.state == "chart":
            if key == 'esc':
                self.state = self.previous_state
            elif key == 'left':
                if self.chart_points and self.selected_chart_idx > 0:
                    self.selected_chart_idx -= 1
            elif key == 'right':
                if self.chart_points and self.selected_chart_idx < len(self.chart_points) - 1:
                    self.selected_chart_idx += 1
                    
        new_idx = (self.selected_backtest_idx if self.state == "list"
                   else self.selected_trade_idx if self.state == "trades"
                   else self.selected_sort_idx if self.state == "sort_menu"
                   else self.selected_chart_idx if self.state == "chart"
                   else 0)
                   
        if self.state != old_state or new_idx != old_idx:
            self.re_render()
        
    def re_render(self):
        """Schedule a render, throttling it to avoid keypress repeat congestion."""
        if self._render_job:
            return
            
        current_time = time.time()
        time_diff = current_time - self.last_render_time
        
        # Keep a steady 30ms throttle (~33 FPS) to ensure smooth input response
        delay_ms = max(1, int((0.03 - time_diff) * 1000))
        self._render_job = self.root.after(delay_ms, self._actual_render)
            
    def _actual_render(self):
        self._render_job = None
        self.last_render_time = time.time()
        
        # Ensure text display is packed
        if not self.text_display.winfo_manager():
            self.text_display.pack(fill="both", expand=True)
            
        # Clean up chart canvas when not in chart state
        if self.state != "chart":
            try:
                if hasattr(self, 'chart_canvas') and self.chart_canvas:
                    self.chart_canvas.destroy()
            except Exception:
                pass
        
        # Clear buffer
        self.string_io.seek(0)
        self.string_io.truncate(0)
        
        rows = self.console_rows
        
        if self.state == "chart":
            self.text_display.configure(state='normal')
            self.text_display.delete('1.0', 'end')
            
            # Destroy old canvas instance to ensure a fresh clean state
            try:
                if hasattr(self, 'chart_canvas') and self.chart_canvas:
                    self.chart_canvas.destroy()
            except Exception:
                pass
                
            self.chart_canvas = tk.Canvas(
                self.root,
                bg="#111111",
                highlightthickness=0
            )
            
            bt = self.backtests[self.selected_backtest_idx]
            
            # 1. Draw Header
            draw_header(
                self.rich_console, 
                f"Chart for {bt.strategy} ({bt.symbol} {bt.timeframe})", 
                f"Initial: ${bt.initial_balance:,.2f} -> Final: ${bt.final_balance:,.2f} ({bt.pnl_pct:+.2f}%) | Total: {bt.total_trades}"
            )
            ansi_header = self.string_io.getvalue()
            insert_ansi_to_text_widget(self.text_display, ansi_header, append=True)
            
            self.text_display.configure(state='normal')
            self.text_display.insert('end', '\n\n')
            
            # 2. Configure & Embed Canvas
            canvas_w = max(500, self.last_width - 60)
            canvas_h = max(200, (self.console_rows - 10) * self.line_height)
            self.chart_canvas.configure(width=canvas_w, height=canvas_h)
            self.text_display.window_create('end', window=self.chart_canvas)
            
            self.text_display.insert('end', '\n\n')
            
            # 3. Draw Footer (matching controls menu styling)
            self.string_io.seek(0)
            self.string_io.truncate(0)
            
            if not self.chart_points:
                self.chart_points = get_equity_curve(bt)
                
            if self.chart_points:
                if self.selected_chart_idx >= len(self.chart_points):
                    self.selected_chart_idx = len(self.chart_points) - 1
                if self.selected_chart_idx < 0:
                    self.selected_chart_idx = 0
                sel_pt = self.chart_points[self.selected_chart_idx]
                pt_ts, pt_bal, pt_date = sel_pt
            else:
                self.selected_chart_idx = 0
                pt_ts, pt_bal, pt_date = 0.0, bt.initial_balance, "Unknown"
            
            if self.selected_chart_idx == 0:
                trade_lbl = "Initial"
            else:
                trade_lbl = f"Trade {self.selected_chart_idx}"
                
            left_text = "Showing Equity Chart | Press Esc to go back"
            right_text = f"{trade_lbl} | {pt_date} | ${pt_bal:,.2f}"
            
            # Align right text to the far right of the console width
            available_width = max(80, self.console_cols)
            padding_len = available_width - len(left_text) - len(right_text) - 4
            if padding_len < 1:
                padding_len = 1
            padding = " " * padding_len
            combined_line = f"{left_text}{padding}{right_text}"
            
            back_lbl = "Back to Trades" if self.previous_state == "trades" else "Back to List"
            self.rich_console.print(f"[dim]{combined_line}[/dim]")
            self.rich_console.print(f"\n[bold yellow]Controls:[/bold yellow] [←/→] Navigate Trades | [Esc] {back_lbl}")
            ansi_footer = self.string_io.getvalue()
            insert_ansi_to_text_widget(self.text_display, ansi_footer, append=True)
            
            # 4. Render Vector lines on Canvas
            draw_chart_on_canvas(
                self.chart_canvas,
                canvas_w,
                canvas_h,
                self.chart_points,
                "", # No title on canvas
                "", # No metadata info on canvas
                self.selected_chart_idx
            )
            return
        
        if self.state == "list":
            draw_header(self.rich_console, "MATI TRADING BOT — BACKTEST JOURNAL VIEWER", f"Total Backtests: {len(self.backtests)} | Folder: {self.backtests_dir.name}")
            max_visible = max(5, rows - 12)
            draw_backtests_table(self.rich_console, self.backtests, self.selected_backtest_idx, self.backtest_scroll_offset, max_visible, self.sort_by)
            self.rich_console.print("\n[bold yellow]Controls:[/bold yellow] [↑/↓] Navigate | [Enter] View Trades | [S] Sort Menu | [C] Equity Chart | [Esc] Exit")
            
        elif self.state == "sort_menu":
            draw_header(self.rich_console, "SORT BACKTEST RUNS")
            draw_sort_menu(self.rich_console, self.selected_sort_idx)
            
        elif self.state == "trades":
            bt = self.backtests[self.selected_backtest_idx]
            max_visible = max(5, rows - 12)
            draw_trades_table(self.rich_console, bt, self.selected_trade_idx, self.trade_scroll_offset, max_visible)
            self.rich_console.print("\n[bold yellow]Controls:[/bold yellow] [↑/↓] Navigate | [Enter] Trade Details | [C] Equity Chart | [Esc] Back to List")
            
        elif self.state == "trade_detail":
            bt = self.backtests[self.selected_backtest_idx]
            draw_trade_detail(self.rich_console, bt, self.selected_trade_idx)
            
        # Get ANSI text
        ansi_text = self.string_io.getvalue()
        
        # Insert and format in Tkinter Text widget
        insert_ansi_to_text_widget(self.text_display, ansi_text)


def main():
    root = tk.Tk()
    app = BacktestViewerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
