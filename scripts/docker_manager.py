#!/usr/bin/env python3
"""
=============================================================================
Docker Manager
=============================================================================
Handles local Docker container orchestration for JMeter distributed testing.
"""

import subprocess
import time
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional


class DockerManager:
    """Manage Docker containers for local JMeter distributed testing."""
    
    def __init__(
        self,
        config: Dict[str, Any],
        logger: Optional[logging.Logger] = None
    ):
        self.logger = logger or logging.getLogger(__name__)
        self.config = config
        self.docker_config = config.get('docker', {})
        
        self.image_name = self.docker_config.get('image_name', 'jmeter-distributed')
        self.image_tag = self.docker_config.get('image_tag', 'latest')
        self.full_image = f"{self.image_name}:{self.image_tag}"
        
        # Project paths
        self.project_root = Path(__file__).parent.parent
        self.docker_dir = self.project_root / 'docker'
        self.compose_file = self.docker_dir / 'docker-compose.yml'
        
        # Track running containers
        self._containers: List[str] = []
    
    def build_image(self, no_cache: bool = False) -> None:
        """Build the JMeter Docker image."""
        self.logger.info(f"Building Docker image: {self.full_image}")
        
        cmd = [
            'docker', 'build',
            '-t', self.full_image,
            '-f', str(self.docker_dir / 'Dockerfile'),
            str(self.project_root)
        ]
        
        if no_cache:
            cmd.insert(2, '--no-cache')
        
        self.logger.debug(f"Running: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            self.logger.error(f"Build failed: {result.stderr}")
            raise RuntimeError(f"Docker build failed: {result.stderr}")
        
        self.logger.info("Docker image built successfully")
    
    def push_image(self) -> None:
        """Push the Docker image to registry."""
        registry = self.docker_config.get('registry')
        
        if not registry:
            self.logger.warning("No registry configured, skipping push")
            return
        
        remote_image = f"{registry}/{self.full_image}"
        
        # Tag for remote
        self.logger.info(f"Tagging image for registry: {remote_image}")
        subprocess.run(['docker', 'tag', self.full_image, remote_image], check=True)
        
        # Push
        self.logger.info(f"Pushing image: {remote_image}")
        subprocess.run(['docker', 'push', remote_image], check=True)
        
        self.logger.info("Image pushed successfully")
    
    def start_workers(self, count: int) -> List[str]:
        """
        Start worker containers using docker-compose.
        
        Returns:
            List of worker hostnames (e.g., ['worker1:50000', 'worker2:50000'])
        """
        self.logger.info(f"Starting {count} worker containers...")
        
        # Determine which workers to start
        worker_services = [f"worker{i}" for i in range(1, count + 1)]
        
        # Build the compose command
        cmd = [
            'docker-compose',
            '-f', str(self.compose_file),
            'up', '-d'
        ]
        
        # Add profile flag if using more than 2 workers
        if count > 2:
            cmd.extend(['--profile', 'scale'])
        
        cmd.extend(worker_services)
        
        self.logger.debug(f"Running: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            cwd=str(self.docker_dir),
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            self.logger.error(f"Failed to start workers: {result.stderr}")
            raise RuntimeError(f"Failed to start workers: {result.stderr}")
        
        # Wait for workers to be healthy
        self._wait_for_workers(worker_services)
        
        # Return worker hosts for JMeter
        jmeter_ports = self.config.get('jmeter', {}).get('ports', {})
        server_port = jmeter_ports.get('server', 50000)
        
        worker_hosts = [f"{service}:{server_port}" for service in worker_services]
        self._containers.extend(worker_services)
        
        self.logger.info(f"Workers started: {', '.join(worker_hosts)}")
        return worker_hosts
    
    def _wait_for_workers(self, worker_services: List[str], timeout: int = 120) -> None:
        """Wait for worker containers to be healthy."""
        self.logger.info("Waiting for workers to be healthy...")
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            all_healthy = True
            
            for service in worker_services:
                result = subprocess.run(
                    ['docker-compose', '-f', str(self.compose_file), 'ps', '-q', service],
                    cwd=str(self.docker_dir),
                    capture_output=True,
                    text=True
                )
                
                container_id = result.stdout.strip()
                
                if not container_id:
                    all_healthy = False
                    continue
                
                # Check container health
                health_result = subprocess.run(
                    ['docker', 'inspect', '--format', '{{.State.Health.Status}}', container_id],
                    capture_output=True,
                    text=True
                )
                
                status = health_result.stdout.strip()
                
                if status != 'healthy':
                    all_healthy = False
                    self.logger.debug(f"{service} status: {status}")
            
            if all_healthy:
                self.logger.info("All workers are healthy")
                return
            
            time.sleep(5)
        
        raise TimeoutError(f"Workers not healthy after {timeout}s")
    
    def run_controller(
        self,
        test_plan: str,
        worker_hosts: List[str],
        results_file: str,
        jmeter_props: Optional[Dict[str, str]] = None
    ) -> int:
        """
        Run the controller container to execute a test.
        
        Returns:
            Exit code from JMeter
        """
        self.logger.info(f"Running controller with test plan: {test_plan}")
        
        # Build JMeter command arguments
        jmeter_args = [
            '-n',  # Non-GUI mode
            '-t', f'/jmeter/test-plans/{Path(test_plan).name}',
            '-l', f'/jmeter/results/{results_file}',
            '-Dserver.rmi.ssl.disable=true'
        ]
        
        # Add remote hosts
        remote_hosts = ','.join(worker_hosts)
        jmeter_args.extend(['-R', remote_hosts])
        
        # Add custom properties
        if jmeter_props:
            for key, value in jmeter_props.items():
                jmeter_args.extend(['-J', f'{key}={value}'])
        
        # Build docker-compose run command
        cmd = [
            'docker-compose',
            '-f', str(self.compose_file),
            'run', '--rm',
            '-e', f'REMOTE_HOSTS={remote_hosts}',
            'controller'
        ] + jmeter_args
        
        self.logger.debug(f"Running: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            cwd=str(self.docker_dir)
        )
        
        return result.returncode
    
    def teardown(self) -> None:
        """Stop and remove all containers."""
        self.logger.info("Tearing down Docker containers...")
        
        cmd = [
            'docker-compose',
            '-f', str(self.compose_file),
            '--profile', 'scale',
            '--profile', 'monitoring',
            'down', '-v'
        ]
        
        subprocess.run(
            cmd,
            cwd=str(self.docker_dir),
            capture_output=True
        )
        
        self._containers.clear()
        self.logger.info("Docker containers removed")
    
    def show_status(self) -> None:
        """Show status of Docker containers."""
        result = subprocess.run(
            ['docker-compose', '-f', str(self.compose_file), 'ps'],
            cwd=str(self.docker_dir),
            capture_output=True,
            text=True
        )
        
        print("\nDocker Compose Status:")
        print(result.stdout)
        
        if result.stderr:
            print(f"Warnings: {result.stderr}")
    
    def get_logs(self, service: str = None, tail: int = 100) -> str:
        """Get logs from containers."""
        cmd = [
            'docker-compose',
            '-f', str(self.compose_file),
            'logs', '--tail', str(tail)
        ]
        
        if service:
            cmd.append(service)
        
        result = subprocess.run(
            cmd,
            cwd=str(self.docker_dir),
            capture_output=True,
            text=True
        )
        
        return result.stdout
    
    def exec_command(self, service: str, command: List[str]) -> subprocess.CompletedProcess:
        """Execute a command in a running container."""
        cmd = [
            'docker-compose',
            '-f', str(self.compose_file),
            'exec', '-T', service
        ] + command
        
        return subprocess.run(
            cmd,
            cwd=str(self.docker_dir),
            capture_output=True,
            text=True
        )
