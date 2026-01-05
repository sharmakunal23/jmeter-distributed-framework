#!/usr/bin/env python3
"""
=============================================================================
JMeter Distributed Framework - Main Orchestrator
=============================================================================
CLI entry point for managing distributed JMeter tests.

Usage:
    python orchestrator.py run --test-plan test.jmx --workers 5 --profile medium
    python orchestrator.py provision --profile large
    python orchestrator.py teardown
    python orchestrator.py status

Author: Performance Engineering Team
=============================================================================
"""

import argparse
import logging
import sys
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config_loader import ConfigLoader
from aws_manager import AWSManager
from docker_manager import DockerManager
from jmeter_runner import JMeterRunner
from results_collector import ResultsCollector


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> logging.Logger:
    """Configure logging for the framework."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        log_dir = Path(log_file).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers
    )
    
    return logging.getLogger("jmeter-framework")


def create_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="JMeter Distributed Testing Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run a test locally with Docker
  %(prog)s run --mode docker --test-plan ./test-plans/test.jmx --workers 2

  # Run a test on AWS EC2
  %(prog)s run --mode aws --test-plan ./test-plans/test.jmx --profile medium

  # Provision AWS infrastructure only (for debugging)
  %(prog)s provision --profile large

  # Check status of running infrastructure
  %(prog)s status

  # Tear down all infrastructure
  %(prog)s teardown --mode aws

  # Pass JMeter properties
  %(prog)s run --mode aws --test-plan test.jmx -J threads=100 -J rampup=60
        """
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging"
    )
    
    parser.add_argument(
        "-c", "--config",
        type=str,
        default="config/framework.yaml",
        help="Path to framework configuration file"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # -------------------------------------------------------------------------
    # RUN command
    # -------------------------------------------------------------------------
    run_parser = subparsers.add_parser(
        "run",
        help="Execute a JMeter test",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    run_parser.add_argument(
        "-m", "--mode",
        type=str,
        choices=["docker", "aws"],
        default="docker",
        help="Execution mode: docker (local) or aws (EC2)"
    )
    
    run_parser.add_argument(
        "-t", "--test-plan",
        type=str,
        required=True,
        help="Path to JMeter test plan (.jmx file)"
    )
    
    run_parser.add_argument(
        "-l", "--log-file",
        type=str,
        help="Path to JMeter log file (results .jtl)"
    )
    
    run_parser.add_argument(
        "-w", "--workers",
        type=int,
        default=2,
        help="Number of worker nodes (default: 2)"
    )
    
    run_parser.add_argument(
        "-p", "--profile",
        type=str,
        help="Instance profile name (small, medium, large) - AWS mode only"
    )
    
    run_parser.add_argument(
        "-J",
        action="append",
        dest="jmeter_properties",
        metavar="PROP=VALUE",
        help="JMeter property (can be specified multiple times)"
    )
    
    run_parser.add_argument(
        "-n", "--non-gui",
        action="store_true",
        default=True,
        help="Run in non-GUI mode (default: True)"
    )
    
    run_parser.add_argument(
        "--plugins-dir",
        type=str,
        default="ext",
        help="Directory containing plugin JARs (default: ext)"
    )
    
    run_parser.add_argument(
        "--results-dir",
        type=str,
        default="results",
        help="Directory for test results (default: results)"
    )
    
    run_parser.add_argument(
        "--no-html-report",
        action="store_true",
        help="Skip HTML report generation"
    )
    
    run_parser.add_argument(
        "--no-s3-upload",
        action="store_true",
        help="Skip uploading results to S3 (AWS mode)"
    )
    
    run_parser.add_argument(
        "--keep-infra",
        action="store_true",
        help="Keep infrastructure after test (don't auto-teardown)"
    )
    
    run_parser.add_argument(
        "--run-id",
        type=str,
        help="Custom run ID (auto-generated if not provided)"
    )
    
    # -------------------------------------------------------------------------
    # PROVISION command
    # -------------------------------------------------------------------------
    provision_parser = subparsers.add_parser(
        "provision",
        help="Provision infrastructure without running a test"
    )
    
    provision_parser.add_argument(
        "-m", "--mode",
        type=str,
        choices=["docker", "aws"],
        default="aws",
        help="Execution mode"
    )
    
    provision_parser.add_argument(
        "-w", "--workers",
        type=int,
        default=2,
        help="Number of worker nodes"
    )
    
    provision_parser.add_argument(
        "-p", "--profile",
        type=str,
        help="Instance profile name (AWS mode)"
    )
    
    # -------------------------------------------------------------------------
    # TEARDOWN command
    # -------------------------------------------------------------------------
    teardown_parser = subparsers.add_parser(
        "teardown",
        help="Tear down all infrastructure"
    )
    
    teardown_parser.add_argument(
        "-m", "--mode",
        type=str,
        choices=["docker", "aws", "all"],
        default="all",
        help="What to tear down"
    )
    
    teardown_parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Force teardown without confirmation"
    )
    
    # -------------------------------------------------------------------------
    # STATUS command
    # -------------------------------------------------------------------------
    status_parser = subparsers.add_parser(
        "status",
        help="Show status of infrastructure"
    )
    
    status_parser.add_argument(
        "-m", "--mode",
        type=str,
        choices=["docker", "aws", "all"],
        default="all",
        help="What to check status of"
    )
    
    # -------------------------------------------------------------------------
    # BUILD command
    # -------------------------------------------------------------------------
    build_parser = subparsers.add_parser(
        "build",
        help="Build the JMeter Docker image"
    )
    
    build_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Build without using cache"
    )
    
    build_parser.add_argument(
        "--push",
        action="store_true",
        help="Push image to registry after build"
    )
    
    return parser


def generate_run_id() -> str:
    """Generate a unique run ID."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    short_uuid = str(uuid.uuid4())[:8]
    return f"{timestamp}-{short_uuid}"


def cmd_run(args, config: dict, logger: logging.Logger) -> int:
    """Execute the 'run' command."""
    run_id = args.run_id or generate_run_id()
    logger.info(f"Starting test run: {run_id}")
    logger.info(f"Mode: {args.mode}")
    logger.info(f"Test plan: {args.test_plan}")
    logger.info(f"Workers: {args.workers}")
    
    # Validate test plan exists
    test_plan_path = Path(args.test_plan)
    if not test_plan_path.exists():
        logger.error(f"Test plan not found: {args.test_plan}")
        return 1
    
    # Parse JMeter properties
    jmeter_props = {}
    if args.jmeter_properties:
        for prop in args.jmeter_properties:
            if "=" in prop:
                key, value = prop.split("=", 1)
                jmeter_props[key] = value
    
    try:
        if args.mode == "docker":
            # Local Docker execution
            manager = DockerManager(config, logger)
            
            # Build image if needed
            manager.build_image()
            
            # Start workers
            worker_hosts = manager.start_workers(args.workers)
            
            # Run test
            runner = JMeterRunner(config, logger)
            results_file = runner.run_distributed_test(
                test_plan=str(test_plan_path),
                worker_hosts=worker_hosts,
                properties=jmeter_props,
                results_dir=args.results_dir,
                run_id=run_id
            )
            
        else:
            # AWS EC2 execution
            aws_manager = AWSManager(config, args.profile, logger)
            
            # Provision infrastructure
            logger.info("Provisioning AWS infrastructure...")
            infra = aws_manager.provision(
                worker_count=args.workers,
                run_id=run_id
            )
            
            try:
                # Upload test plan to instances
                aws_manager.upload_test_plan(str(test_plan_path), infra)
                
                # Run test
                runner = JMeterRunner(config, logger)
                results_file = runner.run_distributed_test_aws(
                    infra=infra,
                    test_plan=test_plan_path.name,
                    properties=jmeter_props,
                    run_id=run_id
                )
                
                # Collect results
                collector = ResultsCollector(config, logger)
                collector.collect_from_aws(infra, args.results_dir, run_id)
                
                # Generate HTML report
                if not args.no_html_report:
                    collector.generate_html_report(results_file, run_id)
                
                # Upload to S3
                if not args.no_s3_upload:
                    collector.upload_to_s3(args.results_dir, run_id)
                    
            finally:
                # Teardown unless --keep-infra
                if not args.keep_infra:
                    logger.info("Tearing down infrastructure...")
                    aws_manager.teardown(infra)
                else:
                    logger.info("Keeping infrastructure (--keep-infra specified)")
                    logger.info(f"Remember to run 'teardown' when done!")
        
        logger.info(f"Test run {run_id} completed successfully")
        return 0
        
    except Exception as e:
        logger.error(f"Test run failed: {e}", exc_info=True)
        return 1


def cmd_provision(args, config: dict, logger: logging.Logger) -> int:
    """Execute the 'provision' command."""
    logger.info(f"Provisioning infrastructure in {args.mode} mode")
    
    try:
        if args.mode == "docker":
            manager = DockerManager(config, logger)
            manager.build_image()
            worker_hosts = manager.start_workers(args.workers)
            logger.info(f"Workers started: {worker_hosts}")
            
        else:
            aws_manager = AWSManager(config, args.profile, logger)
            run_id = generate_run_id()
            infra = aws_manager.provision(worker_count=args.workers, run_id=run_id)
            
            logger.info("Infrastructure provisioned:")
            logger.info(f"  Controller: {infra['controller']['public_ip']}")
            for i, worker in enumerate(infra['workers']):
                logger.info(f"  Worker {i+1}: {worker['public_ip']}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Provisioning failed: {e}", exc_info=True)
        return 1


def cmd_teardown(args, config: dict, logger: logging.Logger) -> int:
    """Execute the 'teardown' command."""
    if not args.force:
        response = input("Are you sure you want to tear down infrastructure? [y/N] ")
        if response.lower() != 'y':
            logger.info("Teardown cancelled")
            return 0
    
    try:
        if args.mode in ["docker", "all"]:
            logger.info("Tearing down Docker containers...")
            manager = DockerManager(config, logger)
            manager.teardown()
        
        if args.mode in ["aws", "all"]:
            logger.info("Tearing down AWS infrastructure...")
            aws_manager = AWSManager(config, None, logger)
            aws_manager.teardown_all()
        
        logger.info("Teardown complete")
        return 0
        
    except Exception as e:
        logger.error(f"Teardown failed: {e}", exc_info=True)
        return 1


def cmd_status(args, config: dict, logger: logging.Logger) -> int:
    """Execute the 'status' command."""
    try:
        if args.mode in ["docker", "all"]:
            logger.info("Docker status:")
            manager = DockerManager(config, logger)
            manager.show_status()
        
        if args.mode in ["aws", "all"]:
            logger.info("AWS status:")
            aws_manager = AWSManager(config, None, logger)
            aws_manager.show_status()
        
        return 0
        
    except Exception as e:
        logger.error(f"Status check failed: {e}", exc_info=True)
        return 1


def cmd_build(args, config: dict, logger: logging.Logger) -> int:
    """Execute the 'build' command."""
    try:
        manager = DockerManager(config, logger)
        manager.build_image(no_cache=args.no_cache)
        
        if args.push:
            manager.push_image()
        
        return 0
        
    except Exception as e:
        logger.error(f"Build failed: {e}", exc_info=True)
        return 1


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Setup logging
    log_level = "DEBUG" if args.verbose else "INFO"
    logger = setup_logging(log_level)
    
    # Load configuration
    try:
        config_loader = ConfigLoader(args.config)
        config = config_loader.load()
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        return 1
    
    # Dispatch to command handler
    commands = {
        "run": cmd_run,
        "provision": cmd_provision,
        "teardown": cmd_teardown,
        "status": cmd_status,
        "build": cmd_build,
    }
    
    handler = commands.get(args.command)
    if handler:
        return handler(args, config, logger)
    else:
        logger.error(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
