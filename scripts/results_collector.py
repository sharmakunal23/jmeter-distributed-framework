#!/usr/bin/env python3
"""
=============================================================================
Results Collector
=============================================================================
Handles collecting results from distributed nodes and uploading to S3.
"""

import subprocess
import shutil
import logging
import boto3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class ResultsCollector:
    """Collect and manage JMeter test results."""
    
    def __init__(
        self,
        config: Dict[str, Any],
        logger: Optional[logging.Logger] = None
    ):
        self.logger = logger or logging.getLogger(__name__)
        self.config = config
        self.results_config = config.get('results', {})
        self.s3_config = config.get('aws', {}).get('s3', {})
        
        self.project_root = Path(__file__).parent.parent
    
    def collect_from_aws(
        self,
        infra: Dict[str, Any],
        local_dir: str,
        run_id: str
    ) -> Path:
        """
        Collect results from AWS EC2 controller.
        
        Args:
            infra: Infrastructure details from AWSManager
            local_dir: Local directory to save results
            run_id: Unique run identifier
        
        Returns:
            Path to local results directory
        """
        controller_ip = infra['controller']['public_ip']
        key_pair_name = infra['key_pair_name']
        key_path = Path.home() / '.ssh' / f"{key_pair_name}.pem"
        
        # Create local results directory
        results_path = self.project_root / local_dir / run_id
        results_path.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"Collecting results from controller: {controller_ip}")
        
        # SCP all results from controller
        cmd = [
            'scp', '-r',
            '-i', str(key_path),
            '-o', 'StrictHostKeyChecking=no',
            f'ubuntu@{controller_ip}:/opt/jmeter/results/*',
            str(results_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            self.logger.warning(f"SCP warning: {result.stderr}")
        
        # Also collect logs from workers for debugging
        self._collect_worker_logs(infra, results_path, key_path)
        
        self.logger.info(f"Results collected to: {results_path}")
        return results_path
    
    def _collect_worker_logs(
        self,
        infra: Dict[str, Any],
        results_path: Path,
        key_path: Path
    ) -> None:
        """Collect JMeter logs from worker nodes."""
        logs_dir = results_path / 'worker-logs'
        logs_dir.mkdir(exist_ok=True)
        
        for i, worker in enumerate(infra['workers']):
            ip = worker['public_ip']
            self.logger.debug(f"Collecting logs from worker {i+1}: {ip}")
            
            cmd = [
                'scp',
                '-i', str(key_path),
                '-o', 'StrictHostKeyChecking=no',
                f'ubuntu@{ip}:/opt/jmeter/jmeter-server.log',
                str(logs_dir / f'worker-{i+1}.log')
            ]
            
            subprocess.run(cmd, capture_output=True)
    
    def generate_html_report(
        self,
        results_file: str,
        run_id: str
    ) -> Path:
        """
        Generate JMeter HTML dashboard report.
        
        Args:
            results_file: Path to .jtl results file
            run_id: Unique run identifier
        
        Returns:
            Path to HTML report directory
        """
        results_path = Path(results_file).parent
        report_dir = results_path / 'html-report'
        
        # Remove existing report directory if it exists
        if report_dir.exists():
            shutil.rmtree(report_dir)
        
        report_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"Generating HTML report from: {results_file}")
        
        cmd = [
            'jmeter',
            '-g', results_file,
            '-o', str(report_dir)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            self.logger.error(f"Report generation failed: {result.stderr}")
            # Don't raise - report generation failure shouldn't fail the whole run
            return None
        
        self.logger.info(f"HTML report generated: {report_dir}")
        return report_dir
    
    def upload_to_s3(
        self,
        local_dir: str,
        run_id: str,
        bucket_name: Optional[str] = None
    ) -> str:
        """
        Upload results to S3.
        
        Args:
            local_dir: Local results directory
            run_id: Unique run identifier
            bucket_name: S3 bucket name (uses config if not provided)
        
        Returns:
            S3 URI of uploaded results
        """
        bucket = bucket_name or self.s3_config.get('bucket_name')
        
        if not bucket:
            self.logger.warning("No S3 bucket configured, skipping upload")
            return None
        
        prefix = self.s3_config.get('results_prefix', 'results/')
        s3_path = f"{prefix}{run_id}/"
        
        self.logger.info(f"Uploading results to s3://{bucket}/{s3_path}")
        
        local_path = self.project_root / local_dir / run_id
        
        if not local_path.exists():
            self.logger.error(f"Local results not found: {local_path}")
            return None
        
        s3 = boto3.client('s3', region_name=self.config.get('aws', {}).get('region', 'us-east-1'))
        
        # Upload all files recursively
        upload_count = 0
        for file_path in local_path.rglob('*'):
            if file_path.is_file():
                relative_path = file_path.relative_to(local_path)
                s3_key = f"{s3_path}{relative_path}"
                
                self.logger.debug(f"Uploading: {relative_path}")
                
                s3.upload_file(
                    str(file_path),
                    bucket,
                    s3_key
                )
                upload_count += 1
        
        s3_uri = f"s3://{bucket}/{s3_path}"
        self.logger.info(f"Uploaded {upload_count} files to {s3_uri}")
        
        # Optionally remove local files after upload
        if not self.results_config.get('keep_local_after_upload', True):
            self.logger.info("Removing local results after S3 upload")
            shutil.rmtree(local_path)
        
        return s3_uri
    
    def download_from_s3(
        self,
        run_id: str,
        local_dir: str,
        bucket_name: Optional[str] = None
    ) -> Path:
        """
        Download results from S3.
        
        Args:
            run_id: Unique run identifier
            local_dir: Local directory to save results
            bucket_name: S3 bucket name
        
        Returns:
            Path to downloaded results
        """
        bucket = bucket_name or self.s3_config.get('bucket_name')
        prefix = self.s3_config.get('results_prefix', 'results/')
        s3_path = f"{prefix}{run_id}/"
        
        local_path = self.project_root / local_dir / run_id
        local_path.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"Downloading from s3://{bucket}/{s3_path}")
        
        s3 = boto3.client('s3', region_name=self.config.get('aws', {}).get('region', 'us-east-1'))
        
        # List and download all objects
        paginator = s3.get_paginator('list_objects_v2')
        
        download_count = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=s3_path):
            for obj in page.get('Contents', []):
                key = obj['Key']
                relative_path = key[len(s3_path):]
                
                if not relative_path:
                    continue
                
                local_file = local_path / relative_path
                local_file.parent.mkdir(parents=True, exist_ok=True)
                
                self.logger.debug(f"Downloading: {relative_path}")
                s3.download_file(bucket, key, str(local_file))
                download_count += 1
        
        self.logger.info(f"Downloaded {download_count} files to {local_path}")
        return local_path
    
    def list_runs(self, bucket_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List available test runs in S3.
        
        Returns:
            List of run metadata
        """
        bucket = bucket_name or self.s3_config.get('bucket_name')
        prefix = self.s3_config.get('results_prefix', 'results/')
        
        s3 = boto3.client('s3', region_name=self.config.get('aws', {}).get('region', 'us-east-1'))
        
        # List "directories" under results prefix
        response = s3.list_objects_v2(
            Bucket=bucket,
            Prefix=prefix,
            Delimiter='/'
        )
        
        runs = []
        for prefix_obj in response.get('CommonPrefixes', []):
            run_prefix = prefix_obj['Prefix']
            run_id = run_prefix.rstrip('/').split('/')[-1]
            
            runs.append({
                'run_id': run_id,
                's3_uri': f"s3://{bucket}/{run_prefix}"
            })
        
        return runs
    
    def generate_summary(self, results_file: str) -> Dict[str, Any]:
        """
        Generate a summary of test results.
        
        Args:
            results_file: Path to .jtl results file
        
        Returns:
            Dictionary with summary statistics
        """
        import csv
        
        results_path = Path(results_file)
        
        if not results_path.exists():
            return {'error': 'Results file not found'}
        
        # Parse JTL file
        samples = []
        errors = 0
        
        with open(results_path, 'r') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                elapsed = int(row.get('elapsed', 0))
                success = row.get('success', 'true').lower() == 'true'
                
                samples.append(elapsed)
                if not success:
                    errors += 1
        
        if not samples:
            return {'error': 'No samples found in results'}
        
        # Calculate statistics
        samples.sort()
        total = len(samples)
        
        summary = {
            'total_samples': total,
            'errors': errors,
            'error_rate': round(errors / total * 100, 2),
            'min_response_time': min(samples),
            'max_response_time': max(samples),
            'avg_response_time': round(sum(samples) / total, 2),
            'median_response_time': samples[total // 2],
            'p90_response_time': samples[int(total * 0.9)],
            'p95_response_time': samples[int(total * 0.95)],
            'p99_response_time': samples[int(total * 0.99)],
        }
        
        return summary
    
    def print_summary(self, results_file: str) -> None:
        """Print a formatted summary of results."""
        summary = self.generate_summary(results_file)
        
        if 'error' in summary:
            print(f"Error: {summary['error']}")
            return
        
        print("\n" + "=" * 60)
        print("TEST RESULTS SUMMARY")
        print("=" * 60)
        print(f"Total Samples:      {summary['total_samples']:,}")
        print(f"Errors:             {summary['errors']:,} ({summary['error_rate']}%)")
        print("-" * 60)
        print("Response Times (ms)")
        print("-" * 60)
        print(f"  Min:              {summary['min_response_time']:,}")
        print(f"  Max:              {summary['max_response_time']:,}")
        print(f"  Average:          {summary['avg_response_time']:,.2f}")
        print(f"  Median:           {summary['median_response_time']:,}")
        print(f"  90th Percentile:  {summary['p90_response_time']:,}")
        print(f"  95th Percentile:  {summary['p95_response_time']:,}")
        print(f"  99th Percentile:  {summary['p99_response_time']:,}")
        print("=" * 60 + "\n")
