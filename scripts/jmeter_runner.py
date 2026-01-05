#!/usr/bin/env python3
"""
=============================================================================
JMeter Runner
=============================================================================
Handles JMeter command construction and test execution.
"""

import subprocess
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class JMeterRunner:
    """Construct and execute JMeter commands."""
    
    def __init__(
        self,
        config: Dict[str, Any],
        logger: Optional[logging.Logger] = None
    ):
        self.logger = logger or logging.getLogger(__name__)
        self.config = config
        self.jmeter_config = config.get('jmeter', {})
        
        self.project_root = Path(__file__).parent.parent
    
    def build_command(
        self,
        test_plan: str,
        results_file: str,
        worker_hosts: Optional[List[str]] = None,
        properties: Optional[Dict[str, str]] = None,
        non_gui: bool = True
    ) -> List[str]:
        """
        Build JMeter command line arguments.
        
        Args:
            test_plan: Path to .jmx test plan
            results_file: Path for results .jtl file
            worker_hosts: List of worker hosts for distributed mode
            properties: Dictionary of JMeter properties (-J flags)
            non_gui: Run in non-GUI mode
        
        Returns:
            List of command arguments
        """
        cmd = ['jmeter']
        
        if non_gui:
            cmd.append('-n')
        
        # Test plan
        cmd.extend(['-t', test_plan])
        
        # Results file
        cmd.extend(['-l', results_file])
        
        # Distributed mode
        if worker_hosts:
            remote_hosts = ','.join(worker_hosts)
            cmd.extend(['-R', remote_hosts])
            cmd.append('-Dserver.rmi.ssl.disable=true')
        
        # Custom properties
        if properties:
            for key, value in properties.items():
                cmd.extend(['-J', f'{key}={value}'])
        
        # Default properties from config
        defaults = self.jmeter_config.get('defaults', {})
        for key, value in defaults.items():
            if properties and key in properties:
                continue  # Skip if overridden
            cmd.extend(['-J', f'{key}={value}'])
        
        return cmd
    
    def run_distributed_test(
        self,
        test_plan: str,
        worker_hosts: List[str],
        properties: Optional[Dict[str, str]] = None,
        results_dir: str = 'results',
        run_id: Optional[str] = None
    ) -> str:
        """
        Run a distributed JMeter test locally (Docker mode).
        
        Returns:
            Path to results file
        """
        from docker_manager import DockerManager
        
        # Generate results filename
        if not run_id:
            run_id = datetime.now().strftime('%Y%m%d-%H%M%S')
        
        test_name = Path(test_plan).stem
        results_file = f"{test_name}_{run_id}.jtl"
        
        self.logger.info(f"Starting distributed test: {test_name}")
        self.logger.info(f"Workers: {', '.join(worker_hosts)}")
        self.logger.info(f"Results file: {results_file}")
        
        # Use DockerManager to run the controller
        docker_mgr = DockerManager(self.config, self.logger)
        
        exit_code = docker_mgr.run_controller(
            test_plan=test_plan,
            worker_hosts=worker_hosts,
            results_file=results_file,
            jmeter_props=properties
        )
        
        if exit_code != 0:
            self.logger.warning(f"JMeter exited with code: {exit_code}")
        
        return str(self.project_root / results_dir / results_file)
    
    def run_distributed_test_aws(
        self,
        infra: Dict[str, Any],
        test_plan: str,
        properties: Optional[Dict[str, str]] = None,
        run_id: Optional[str] = None
    ) -> str:
        """
        Run a distributed JMeter test on AWS EC2.
        
        Args:
            infra: Infrastructure details from AWSManager
            test_plan: Name of test plan (already uploaded to controller)
            properties: JMeter properties
            run_id: Unique run identifier
        
        Returns:
            Path to results file on controller
        """
        import paramiko
        
        controller_ip = infra['controller']['public_ip']
        key_pair_name = infra['key_pair_name']
        key_path = Path.home() / '.ssh' / f"{key_pair_name}.pem"
        
        # Generate results filename
        if not run_id:
            run_id = datetime.now().strftime('%Y%m%d-%H%M%S')
        
        test_name = Path(test_plan).stem
        results_file = f"{test_name}_{run_id}.jtl"
        
        # Build worker hosts string (using private IPs for internal communication)
        jmeter_ports = self.config.get('jmeter', {}).get('ports', {})
        server_port = jmeter_ports.get('server', 50000)
        
        worker_hosts = [
            f"{w['private_ip']}:{server_port}"
            for w in infra['workers']
        ]
        
        self.logger.info(f"Starting distributed test on AWS: {test_name}")
        self.logger.info(f"Controller: {controller_ip}")
        self.logger.info(f"Workers: {', '.join(worker_hosts)}")
        
        # Build JMeter command
        cmd = self.build_command(
            test_plan=f'/opt/jmeter/test-plans/{test_plan}',
            results_file=f'/opt/jmeter/results/{results_file}',
            worker_hosts=worker_hosts,
            properties=properties
        )
        
        # First, start JMeter server on all workers
        self._start_workers_aws(infra, key_path)
        
        # Run test on controller
        self.logger.info("Executing test on controller...")
        
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            ssh.connect(
                hostname=controller_ip,
                username='ubuntu',
                key_filename=str(key_path),
                timeout=30
            )
            
            # Heap settings
            heap = self.jmeter_config.get('heap', {}).get('controller', '-Xms2g -Xmx4g')
            
            # Build full command
            jmeter_cmd = ' '.join(cmd)
            full_cmd = f'export JVM_ARGS="{heap}" && {jmeter_cmd}'
            
            self.logger.debug(f"Executing: {full_cmd}")
            
            stdin, stdout, stderr = ssh.exec_command(full_cmd, timeout=7200)
            
            # Stream output
            for line in iter(stdout.readline, ''):
                self.logger.info(line.strip())
            
            exit_status = stdout.channel.recv_exit_status()
            
            if exit_status != 0:
                error = stderr.read().decode()
                self.logger.error(f"JMeter failed: {error}")
                raise RuntimeError(f"JMeter exited with code {exit_status}")
            
            self.logger.info("Test completed successfully")
            
        finally:
            ssh.close()
        
        return f'/opt/jmeter/results/{results_file}'
    
    def _start_workers_aws(self, infra: Dict[str, Any], key_path: Path) -> None:
        """Start JMeter server on all worker instances."""
        import paramiko
        import threading
        
        jmeter_ports = self.config.get('jmeter', {}).get('ports', {})
        server_port = jmeter_ports.get('server', 50000)
        local_port = jmeter_ports.get('local', 50001)
        
        heap = self.jmeter_config.get('heap', {}).get('worker', '-Xms2g -Xmx4g')
        
        def start_worker(worker: Dict[str, Any]):
            ip = worker['public_ip']
            private_ip = worker['private_ip']
            
            self.logger.info(f"Starting JMeter server on worker: {ip}")
            
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            try:
                ssh.connect(
                    hostname=ip,
                    username='ubuntu',
                    key_filename=str(key_path),
                    timeout=30
                )
                
                # Start JMeter server in background
                cmd = (
                    f'export JVM_ARGS="{heap}" && '
                    f'nohup jmeter-server '
                    f'-Dserver.rmi.ssl.disable=true '
                    f'-Dserver_port={server_port} '
                    f'-Dserver.rmi.localport={local_port} '
                    f'-Djava.rmi.server.hostname={private_ip} '
                    f'> /opt/jmeter/jmeter-server.log 2>&1 &'
                )
                
                ssh.exec_command(cmd)
                
                # Wait a bit for server to start
                import time
                time.sleep(5)
                
                self.logger.info(f"JMeter server started on {ip}")
                
            finally:
                ssh.close()
        
        # Start all workers in parallel
        threads = []
        for worker in infra['workers']:
            t = threading.Thread(target=start_worker, args=(worker,))
            t.start()
            threads.append(t)
        
        # Wait for all to complete
        for t in threads:
            t.join()
        
        self.logger.info("All workers started")
    
    def generate_html_report(
        self,
        results_file: str,
        output_dir: str
    ) -> str:
        """
        Generate JMeter HTML report from results.
        
        Returns:
            Path to HTML report directory
        """
        report_dir = Path(output_dir) / 'html-report'
        report_dir.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            'jmeter',
            '-g', results_file,
            '-o', str(report_dir)
        ]
        
        self.logger.info(f"Generating HTML report: {report_dir}")
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            self.logger.error(f"Report generation failed: {result.stderr}")
            raise RuntimeError(f"Failed to generate HTML report: {result.stderr}")
        
        self.logger.info("HTML report generated successfully")
        return str(report_dir)
