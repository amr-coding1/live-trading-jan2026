#!/usr/bin/env python3
"""CLI entry point for live trading track record infrastructure.

Commands:
    pull        Pull today's executions from IBKR
    snapshot    Save current portfolio state
    annotate    Add/update trade annotation
    report      Generate monthly PDF report
    stats       Print performance summary
    slippage    Print slippage analysis
    signal      Run momentum signal, print ranked sectors
    rebalance   Compare current portfolio to signal, print trades
    dashboard   Start web dashboard on localhost:5000
    scheduler   Start background scheduler for automated tasks
"""

import argparse
import sys
from pathlib import Path

import yaml


def load_config() -> dict:
    """Load configuration from YAML file."""
    config_path = Path("config/config.yaml")

    if not config_path.exists():
        print("Error: config/config.yaml not found.")
        print("Copy config/config.example.yaml to config/config.yaml and update settings.")
        sys.exit(1)

    with open(config_path) as f:
        return yaml.safe_load(f)


def cmd_pull(args: argparse.Namespace) -> None:
    """Pull executions from IBKR."""
    from src.execution_logger import pull_executions_only, load_config, setup_logging

    config = load_config()
    setup_logging(config)

    print("Pulling executions from IBKR...")

    try:
        path = pull_executions_only(config)
        print(f"Executions saved to: {path}")
    except ConnectionError as e:
        print(f"Connection failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_snapshot(args: argparse.Namespace) -> None:
    """Save portfolio snapshot."""
    from src.execution_logger import save_snapshot_only, load_config, setup_logging

    config = load_config()
    setup_logging(config)

    print("Saving portfolio snapshot...")

    try:
        path = save_snapshot_only(config)
        print(f"Snapshot saved to: {path}")
    except ConnectionError as e:
        print(f"Connection failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_annotate(args: argparse.Namespace) -> None:
    """Add or update trade annotation."""
    from src.annotations import interactive_annotate, list_annotations, format_annotation_list

    config = load_config()
    annotations_dir = config["paths"]["annotations"]

    if args.list:
        annotations = list_annotations(annotations_dir)
        print(format_annotation_list(annotations))
        return

    trade_id = args.trade_id if args.trade_id != "new" else None

    interactive_annotate(
        annotations_dir=annotations_dir,
        trade_id=trade_id,
        pre_trade=args.pre or (not args.post),
        post_trade=args.post,
    )


def cmd_report(args: argparse.Namespace) -> None:
    """Generate monthly PDF report."""
    from src.export import generate_monthly_report

    config = load_config()

    print(f"Generating report for {args.month}...")

    try:
        path = generate_monthly_report(
            year_month=args.month,
            snapshots_dir=config["paths"]["snapshots"],
            executions_dir=config["paths"]["executions"],
            annotations_dir=config["paths"]["annotations"],
            output_dir=config["paths"]["reports"],
        )
        print(f"Report saved to: {path}")
    except Exception as e:
        print(f"Error generating report: {e}")
        sys.exit(1)


def cmd_weekly_report(args: argparse.Namespace) -> None:
    """Generate weekly PDF report."""
    from src.export import generate_weekly_report, get_current_week

    config = load_config()

    week = args.week if args.week else get_current_week()
    print(f"Generating weekly report for {week}...")

    try:
        path = generate_weekly_report(
            year_week=week,
            snapshots_dir=config["paths"]["snapshots"],
            executions_dir=config["paths"]["executions"],
            annotations_dir=config["paths"]["annotations"],
            output_dir=config["paths"]["reports"],
        )
        print(f"Report saved to: {path}")
    except Exception as e:
        print(f"Error generating report: {e}")
        sys.exit(1)


def cmd_run_job(args: argparse.Namespace) -> None:
    """Run a scheduler job immediately."""
    from src.scheduler import run_job_now

    config = load_config()

    print(f"Running job: {args.job}...")

    try:
        run_job_now(config, args.job)
    except Exception as e:
        print(f"Error running job: {e}")
        sys.exit(1)


def cmd_stats(args: argparse.Namespace) -> None:
    """Print performance statistics."""
    from src.performance import compute_all_metrics, format_performance_report

    config = load_config()

    try:
        metrics = compute_all_metrics(
            snapshots_dir=config["paths"]["snapshots"],
            executions_dir=config["paths"]["executions"],
            start_date=args.start,
            end_date=args.end,
        )

        print(format_performance_report(metrics))
    except Exception as e:
        print(f"Error computing statistics: {e}")
        sys.exit(1)


def cmd_slippage(args: argparse.Namespace) -> None:
    """Print slippage analysis."""
    from src.slippage_analyzer import analyze_slippage, format_slippage_report

    config = load_config()

    try:
        analysis = analyze_slippage(
            executions_dir=config["paths"]["executions"],
            start_date=args.start,
            end_date=args.end,
            outlier_threshold_bps=args.threshold,
        )

        print(format_slippage_report(analysis, outlier_threshold_bps=args.threshold))
    except Exception as e:
        print(f"Error analyzing slippage: {e}")
        sys.exit(1)


def cmd_signal(args: argparse.Namespace) -> None:
    """Run momentum signal and print ranked sectors."""
    from src.signals.momentum import generate_momentum_signal, format_signal_report
    from src.signals.rebalance import load_latest_snapshot

    config = load_config()

    print("Generating momentum signal...")

    try:
        signal = generate_momentum_signal(top_n=args.top_n)

        cash = 0.0
        snapshot = load_latest_snapshot(config["paths"]["snapshots"])
        if snapshot:
            cash = snapshot.get("cash", 0)

        print(format_signal_report(signal, cash=cash))

    except Exception as e:
        print(f"Error generating signal: {e}")
        sys.exit(1)


def cmd_rebalance(args: argparse.Namespace) -> None:
    """Compare current portfolio to signal and print required trades."""
    from src.signals.rebalance import generate_rebalance_trades, format_rebalance_report

    config = load_config()

    print("Generating rebalance trades...")
    print()

    try:
        rebalance = generate_rebalance_trades(
            snapshots_dir=config["paths"]["snapshots"],
            top_n=args.top_n,
            min_threshold=args.threshold,
        )

        print(format_rebalance_report(rebalance))

    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error generating rebalance: {e}")
        sys.exit(1)


def cmd_dashboard(args: argparse.Namespace) -> None:
    """Start web dashboard."""
    from src.dashboard import run_dashboard

    config = load_config()

    run_dashboard(
        config=config,
        host=args.host,
        port=args.port,
    )


def cmd_scheduler(args: argparse.Namespace) -> None:
    """Start background scheduler."""
    from src.scheduler import run_scheduler

    config = load_config()

    # Get health port from args or config
    health_port = args.health_port
    if health_port is None:
        health_port = config.get("scheduler", {}).get("health_port", 8080)

    run_scheduler(config, health_port=health_port)


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Live trading track record infrastructure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py pull                     Pull today's executions from IBKR
  python main.py snapshot                 Save current portfolio state
  python main.py annotate new --pre       Create new pre-trade annotation
  python main.py annotate <id> --post     Add post-trade annotation
  python main.py report 2026-01           Generate January 2026 report
  python main.py stats 2026-01-01 2026-01-31
  python main.py slippage --threshold 5
  python main.py signal                   Run momentum signal
  python main.py signal --top-n 5         Select top 5 sectors
  python main.py rebalance                Generate rebalance trades
  python main.py dashboard                Start web dashboard
  python main.py scheduler                Start background scheduler
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    pull_parser = subparsers.add_parser("pull", help="Pull today's executions from IBKR")
    pull_parser.set_defaults(func=cmd_pull)

    snapshot_parser = subparsers.add_parser("snapshot", help="Save current portfolio state")
    snapshot_parser.set_defaults(func=cmd_snapshot)

    annotate_parser = subparsers.add_parser("annotate", help="Add/update trade annotation")
    annotate_parser.add_argument(
        "trade_id",
        nargs="?",
        default="new",
        help="Trade ID to annotate, or 'new' for new annotation",
    )
    annotate_parser.add_argument(
        "--pre",
        action="store_true",
        help="Add pre-trade annotation",
    )
    annotate_parser.add_argument(
        "--post",
        action="store_true",
        help="Add post-trade annotation",
    )
    annotate_parser.add_argument(
        "--list",
        action="store_true",
        help="List all annotations",
    )
    annotate_parser.set_defaults(func=cmd_annotate)

    report_parser = subparsers.add_parser("report", help="Generate monthly PDF report")
    report_parser.add_argument(
        "month",
        help="Month in YYYY-MM format (e.g., 2026-01)",
    )
    report_parser.set_defaults(func=cmd_report)

    # Weekly report command
    weekly_report_parser = subparsers.add_parser(
        "weekly-report",
        help="Generate weekly PDF report",
    )
    weekly_report_parser.add_argument(
        "week",
        nargs="?",
        help="Week in YYYY-Www format (e.g., 2026-W05). Defaults to current week.",
    )
    weekly_report_parser.set_defaults(func=cmd_weekly_report)

    # Run job command (for manual scheduler job execution)
    run_job_parser = subparsers.add_parser(
        "run-job",
        help="Run a scheduler job immediately",
    )
    run_job_parser.add_argument(
        "job",
        choices=["snapshot", "signal", "rebalance", "report"],
        help="Job to run: snapshot, signal, rebalance, or report",
    )
    run_job_parser.set_defaults(func=cmd_run_job)

    stats_parser = subparsers.add_parser("stats", help="Print performance summary")
    stats_parser.add_argument(
        "start",
        nargs="?",
        help="Start date (YYYY-MM-DD)",
    )
    stats_parser.add_argument(
        "end",
        nargs="?",
        help="End date (YYYY-MM-DD)",
    )
    stats_parser.set_defaults(func=cmd_stats)

    slippage_parser = subparsers.add_parser("slippage", help="Print slippage analysis")
    slippage_parser.add_argument(
        "--start",
        help="Start date (YYYY-MM-DD)",
    )
    slippage_parser.add_argument(
        "--end",
        help="End date (YYYY-MM-DD)",
    )
    slippage_parser.add_argument(
        "--threshold",
        type=float,
        default=10.0,
        help="Outlier threshold in bps (default: 10)",
    )
    slippage_parser.set_defaults(func=cmd_slippage)

    # Signal command
    signal_parser = subparsers.add_parser(
        "signal",
        help="Run momentum signal, print ranked sectors and target weights",
    )
    signal_parser.add_argument(
        "--top-n",
        type=int,
        default=3,
        dest="top_n",
        help="Number of top sectors to select (default: 3)",
    )
    signal_parser.set_defaults(func=cmd_signal)

    # Rebalance command
    rebalance_parser = subparsers.add_parser(
        "rebalance",
        help="Compare current portfolio to signal, print required trades",
    )
    rebalance_parser.add_argument(
        "--top-n",
        type=int,
        default=3,
        dest="top_n",
        help="Number of top sectors to select (default: 3)",
    )
    rebalance_parser.add_argument(
        "--threshold",
        type=float,
        default=0.02,
        help="Minimum weight difference to trigger trade (default: 0.02 = 2%%)",
    )
    rebalance_parser.set_defaults(func=cmd_rebalance)

    # Dashboard command
    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Start web dashboard on localhost:5000",
    )
    dashboard_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    dashboard_parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port to listen on (default: 5000)",
    )
    dashboard_parser.set_defaults(func=cmd_dashboard)

    # Scheduler command
    scheduler_parser = subparsers.add_parser(
        "scheduler",
        help="Start background scheduler for automated tasks",
    )
    scheduler_parser.add_argument(
        "--health-port",
        type=int,
        default=None,
        dest="health_port",
        help="Port for health check HTTP server (default: 8080)",
    )
    scheduler_parser.set_defaults(func=cmd_scheduler)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
