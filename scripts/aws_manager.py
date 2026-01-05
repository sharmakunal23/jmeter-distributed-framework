#!/usr/bin/env python3
"""
=============================================================================
AWS Manager
=============================================================================
Handles EC2 provisioning, configuration, and teardown for distributed JMeter.
Uses Boto3 for AWS API interactions.
"""

import boto3
import time
import logging
import base64
from pathlib import Path
from typing import Any, Dict, List, Optional
from botocore.exceptions import ClientError

from config_loader import ConfigLoader


class AWSManager:
    """Manage AWS EC2 infrastructure for JMeter distributed testing."""
    
    # Tag used to identify framework-managed resources
    FRAMEWORK_TAG = "jmeter-distributed-framework"
    
    def __init__(
        self,
        config: Dict[str, Any],
        profile_name: Optional[str] = None,
        logger: Optional[logging.Logger] = None
    ):
        self.logger = logger or logging.getLogger(__name__)
        self.config = config
        
        # Load profile if specified
        if profile_name:
            config_loader = ConfigLoader()
            config_loader._config = config
            self.config = config_loader.load_profile(profile_name)
        
        # AWS configuration
        self.region = self.config.get('aws', {}).get('region', 'us-east-1')
        self.ec2_config = self.config.get('aws', {}).get('ec2', {})
        self.s3_config = self.config.get('aws', {}).get('s3', {})
        
        # Initialize AWS clients
        self.ec2 = boto3.client('ec2', region_name=self.region)
        self.ec2_resource = boto3.resource('ec2', region_name=self.region)
        self.s3 = boto3.client('s3', region_name=self.region)
        
        # Cache for created resources
        self._resources: Dict[str, Any] = {}
    
    def provision(self, worker_count: int, run_id: str) -> Dict[str, Any]:
        """
        Provision EC2 infrastructure for a test run.
        
        Returns:
            dict: Infrastructure details including instance IDs and IPs
        """
        self.logger.info(f"Provisioning infrastructure for run: {run_id}")
        
        # 1. Ensure security group exists
        security_group_id = self._ensure_security_group()
        
        # 2. Get or create key pair
        key_pair_name = self.ec2_config.get('key_pair_name', 'jmeter-framework-key')
        self._ensure_key_pair(key_pair_name)
        
        # 3. Prepare user data script (cloud-init)
        user_data = self._generate_user_data()
        
        # 4. Launch controller instance (On-Demand)
        controller_config = self.ec2_config.get('controller', {})
        controller = self._launch_instance(
            name=f"jmeter-controller-{run_id}",
            instance_type=controller_config.get('instance_type', 'c5.xlarge'),
            security_group_id=security_group_id,
            key_pair_name=key_pair_name,
            user_data=user_data,
            role="controller",
            run_id=run_id,
            use_spot=controller_config.get('use_spot', False)
        )
        
        # 5. Launch worker instances (Spot or On-Demand)
        worker_config = self.ec2_config.get('worker', {})
        workers = []
        
        for i in range(worker_count):
            worker = self._launch_instance(
                name=f"jmeter-worker-{run_id}-{i+1}",
                instance_type=worker_config.get('instance_type', 'c5.xlarge'),
                security_group_id=security_group_id,
                key_pair_name=key_pair_name,
                user_data=user_data,
                role="worker",
                run_id=run_id,
                use_spot=worker_config.get('use_spot', True),
                spot_max_price=worker_config.get('spot_max_price')
            )
            workers.append(worker)
        
        # 6. Wait for all instances to be running
        all_instance_ids = [controller['instance_id']] + [w['instance_id'] for w in workers]
        self._wait_for_instances(all_instance_ids)
        
        # 7. Get public IPs
        controller = self._get_instance_details(controller['instance_id'])
        workers = [self._get_instance_details(w['instance_id']) for w in workers]
        
        # 8. Wait for instances to be SSH-ready
        self._wait_for_ssh(controller['public_ip'])
        for worker in workers:
            self._wait_for_ssh(worker['public_ip'])
        
        infra = {
            'run_id': run_id,
            'region': self.region,
            'security_group_id': security_group_id,
            'key_pair_name': key_pair_name,
            'controller': controller,
            'workers': workers
        }
        
        self._resources[run_id] = infra
        
        self.logger.info(f"Infrastructure provisioned successfully")
        self.logger.info(f"Controller: {controller['public_ip']}")
        for i, w in enumerate(workers):
            self.logger.info(f"Worker {i+1}: {w['public_ip']}")
        
        return infra
    
    def _ensure_security_group(self) -> str:
        """Create or get the JMeter security group."""
        sg_config = self.ec2_config.get('security_group', {})
        sg_name = sg_config.get('name', 'jmeter-distributed-sg')
        
        try:
            # Check if security group exists
            response = self.ec2.describe_security_groups(
                Filters=[
                    {'Name': 'group-name', 'Values': [sg_name]}
                ]
            )
            
            if response['SecurityGroups']:
                sg_id = response['SecurityGroups'][0]['GroupId']
                self.logger.info(f"Using existing security group: {sg_id}")
                return sg_id
                
        except ClientError:
            pass
        
        # Create new security group
        self.logger.info(f"Creating security group: {sg_name}")
        
        response = self.ec2.create_security_group(
            GroupName=sg_name,
            Description=sg_config.get('description', 'JMeter distributed testing security group'),
            TagSpecifications=[{
                'ResourceType': 'security-group',
                'Tags': [
                    {'Key': 'Name', 'Value': sg_name},
                    {'Key': 'ManagedBy', 'Value': self.FRAMEWORK_TAG}
                ]
            }]
        )
        
        sg_id = response['GroupId']
        
        # Add inbound rules
        jmeter_ports = self.config.get('jmeter', {}).get('ports', {})
        
        rules = [
            # SSH access
            {
                'IpProtocol': 'tcp',
                'FromPort': 22,
                'ToPort': 22,
                'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'SSH access'}]
            },
            # JMeter RMI registry
            {
                'IpProtocol': 'tcp',
                'FromPort': jmeter_ports.get('rmi_registry', 1099),
                'ToPort': jmeter_ports.get('rmi_registry', 1099),
                'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'JMeter RMI registry'}]
            },
            # JMeter server port
            {
                'IpProtocol': 'tcp',
                'FromPort': jmeter_ports.get('server', 50000),
                'ToPort': jmeter_ports.get('server', 50000),
                'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'JMeter server port'}]
            },
            # JMeter local port
            {
                'IpProtocol': 'tcp',
                'FromPort': jmeter_ports.get('local', 50001),
                'ToPort': jmeter_ports.get('local', 50001),
                'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'JMeter local port'}]
            },
            # Allow all traffic within security group (for internal communication)
            {
                'IpProtocol': '-1',
                'UserIdGroupPairs': [{'GroupId': sg_id, 'Description': 'Internal communication'}]
            }
        ]
        
        self.ec2.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=rules
        )
        
        self.logger.info(f"Security group created: {sg_id}")
        return sg_id
    
    def _ensure_key_pair(self, key_pair_name: str) -> None:
        """Verify key pair exists."""
        try:
            self.ec2.describe_key_pairs(KeyNames=[key_pair_name])
            self.logger.info(f"Using existing key pair: {key_pair_name}")
        except ClientError as e:
            if 'InvalidKeyPair.NotFound' in str(e):
                raise ValueError(
                    f"Key pair '{key_pair_name}' not found. "
                    f"Please create it in AWS Console or via: "
                    f"aws ec2 create-key-pair --key-name {key_pair_name}"
                )
            raise
    
    def _generate_user_data(self) -> str:
        """Generate cloud-init user data script."""
        docker_config = self.config.get('docker', {})
        image_name = docker_config.get('image_name', 'jmeter-distributed')
        image_tag = docker_config.get('image_tag', 'latest')
        registry = docker_config.get('registry', '')
        
        full_image = f"{registry}/{image_name}:{image_tag}" if registry else f"{image_name}:{image_tag}"
        
        script = f"""#!/bin/bash
set -e

# Log all output
exec > >(tee /var/log/user-data.log) 2>&1

echo "Starting JMeter instance setup..."

# Update system
apt-get update -y

# Install Docker
apt-get install -y docker.io
systemctl start docker
systemctl enable docker

# Install AWS CLI
apt-get install -y awscli

# Add ubuntu user to docker group
usermod -aG docker ubuntu

# Create JMeter directories
mkdir -p /opt/jmeter/{{test-plans,results,plugins}}
chown -R ubuntu:ubuntu /opt/jmeter

# Pull JMeter Docker image (if using ECR, login first)
if [[ "{registry}" == *"ecr"* ]]; then
    aws ecr get-login-password --region {self.region} | docker login --username AWS --password-stdin {registry}
fi

# For now, we'll build locally on first run or use pre-built image
# docker pull {full_image} || echo "Image not available, will build locally"

echo "JMeter instance setup complete"
echo "READY" > /tmp/instance-ready
"""
        return script
    
    def _launch_instance(
        self,
        name: str,
        instance_type: str,
        security_group_id: str,
        key_pair_name: str,
        user_data: str,
        role: str,
        run_id: str,
        use_spot: bool = False,
        spot_max_price: Optional[str] = None
    ) -> Dict[str, Any]:
        """Launch a single EC2 instance."""
        ami_id = self.ec2_config.get('ami_id')
        
        tags = [
            {'Key': 'Name', 'Value': name},
            {'Key': 'ManagedBy', 'Value': self.FRAMEWORK_TAG},
            {'Key': 'Role', 'Value': role},
            {'Key': 'RunId', 'Value': run_id}
        ]
        
        # Common launch parameters
        launch_params = {
            'ImageId': ami_id,
            'InstanceType': instance_type,
            'KeyName': key_pair_name,
            'SecurityGroupIds': [security_group_id],
            'UserData': user_data,
            'MinCount': 1,
            'MaxCount': 1,
            'TagSpecifications': [{
                'ResourceType': 'instance',
                'Tags': tags
            }],
            'BlockDeviceMappings': [{
                'DeviceName': '/dev/sda1',
                'Ebs': {
                    'VolumeSize': self.ec2_config.get(role, {}).get('volume_size_gb', 20),
                    'VolumeType': 'gp3',
                    'DeleteOnTermination': True
                }
            }]
        }
        
        if use_spot:
            # Use Spot instances
            launch_params['InstanceMarketOptions'] = {
                'MarketType': 'spot',
                'SpotOptions': {
                    'SpotInstanceType': 'one-time',
                    'InstanceInterruptionBehavior': 'terminate'
                }
            }
            if spot_max_price and spot_max_price != 'auto':
                launch_params['InstanceMarketOptions']['SpotOptions']['MaxPrice'] = spot_max_price
        
        self.logger.info(f"Launching {role} instance: {name} ({instance_type}, spot={use_spot})")
        
        response = self.ec2.run_instances(**launch_params)
        instance_id = response['Instances'][0]['InstanceId']
        
        self.logger.info(f"Launched instance: {instance_id}")
        
        return {
            'instance_id': instance_id,
            'role': role,
            'name': name
        }
    
    def _wait_for_instances(self, instance_ids: List[str], timeout: int = 300) -> None:
        """Wait for instances to be in 'running' state."""
        self.logger.info(f"Waiting for {len(instance_ids)} instances to be running...")
        
        waiter = self.ec2.get_waiter('instance_running')
        waiter.wait(
            InstanceIds=instance_ids,
            WaiterConfig={'Delay': 10, 'MaxAttempts': timeout // 10}
        )
        
        self.logger.info("All instances are running")
    
    def _get_instance_details(self, instance_id: str) -> Dict[str, Any]:
        """Get instance details including public IP."""
        response = self.ec2.describe_instances(InstanceIds=[instance_id])
        instance = response['Reservations'][0]['Instances'][0]
        
        # Get name from tags
        name = ''
        role = ''
        for tag in instance.get('Tags', []):
            if tag['Key'] == 'Name':
                name = tag['Value']
            elif tag['Key'] == 'Role':
                role = tag['Value']
        
        return {
            'instance_id': instance_id,
            'name': name,
            'role': role,
            'public_ip': instance.get('PublicIpAddress'),
            'private_ip': instance.get('PrivateIpAddress'),
            'state': instance['State']['Name']
        }
    
    def _wait_for_ssh(self, host: str, timeout: int = 120) -> None:
        """Wait for SSH to be available on host."""
        import socket
        
        self.logger.info(f"Waiting for SSH on {host}...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                result = sock.connect_ex((host, 22))
                sock.close()
                
                if result == 0:
                    self.logger.info(f"SSH available on {host}")
                    # Additional wait for cloud-init
                    time.sleep(10)
                    return
            except socket.error:
                pass
            
            time.sleep(5)
        
        raise TimeoutError(f"SSH not available on {host} after {timeout}s")
    
    def upload_test_plan(self, test_plan_path: str, infra: Dict[str, Any]) -> None:
        """Upload test plan to controller instance."""
        import subprocess
        
        controller_ip = infra['controller']['public_ip']
        key_pair_name = infra['key_pair_name']
        
        # Assuming key is at ~/.ssh/<key_name>.pem
        key_path = Path.home() / '.ssh' / f"{key_pair_name}.pem"
        
        if not key_path.exists():
            raise FileNotFoundError(f"SSH key not found at {key_path}")
        
        self.logger.info(f"Uploading test plan to controller: {controller_ip}")
        
        cmd = [
            'scp',
            '-i', str(key_path),
            '-o', 'StrictHostKeyChecking=no',
            test_plan_path,
            f'ubuntu@{controller_ip}:/opt/jmeter/test-plans/'
        ]
        
        subprocess.run(cmd, check=True)
        self.logger.info("Test plan uploaded")
    
    def teardown(self, infra: Dict[str, Any]) -> None:
        """Tear down infrastructure for a specific run."""
        run_id = infra.get('run_id', 'unknown')
        self.logger.info(f"Tearing down infrastructure for run: {run_id}")
        
        # Collect all instance IDs
        instance_ids = [infra['controller']['instance_id']]
        instance_ids.extend([w['instance_id'] for w in infra['workers']])
        
        # Terminate instances
        self.logger.info(f"Terminating {len(instance_ids)} instances...")
        self.ec2.terminate_instances(InstanceIds=instance_ids)
        
        # Wait for termination
        waiter = self.ec2.get_waiter('instance_terminated')
        waiter.wait(InstanceIds=instance_ids)
        
        self.logger.info("All instances terminated")
        
        # Remove from cache
        if run_id in self._resources:
            del self._resources[run_id]
    
    def teardown_all(self) -> None:
        """Tear down all framework-managed infrastructure."""
        self.logger.info("Finding all framework-managed instances...")
        
        response = self.ec2.describe_instances(
            Filters=[
                {'Name': 'tag:ManagedBy', 'Values': [self.FRAMEWORK_TAG]},
                {'Name': 'instance-state-name', 'Values': ['pending', 'running', 'stopping', 'stopped']}
            ]
        )
        
        instance_ids = []
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                instance_ids.append(instance['InstanceId'])
        
        if not instance_ids:
            self.logger.info("No framework-managed instances found")
            return
        
        self.logger.info(f"Terminating {len(instance_ids)} instances...")
        self.ec2.terminate_instances(InstanceIds=instance_ids)
        
        waiter = self.ec2.get_waiter('instance_terminated')
        waiter.wait(InstanceIds=instance_ids)
        
        self.logger.info("All instances terminated")
    
    def show_status(self) -> None:
        """Show status of framework-managed infrastructure."""
        response = self.ec2.describe_instances(
            Filters=[
                {'Name': 'tag:ManagedBy', 'Values': [self.FRAMEWORK_TAG]},
                {'Name': 'instance-state-name', 'Values': ['pending', 'running', 'stopping', 'stopped']}
            ]
        )
        
        instances = []
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                details = self._get_instance_details(instance['InstanceId'])
                instances.append(details)
        
        if not instances:
            print("No framework-managed instances found")
            return
        
        print(f"\n{'Name':<40} {'Instance ID':<20} {'Role':<12} {'State':<12} {'Public IP':<16}")
        print("-" * 100)
        
        for inst in instances:
            print(f"{inst['name']:<40} {inst['instance_id']:<20} {inst['role']:<12} {inst['state']:<12} {inst.get('public_ip', 'N/A'):<16}")
        
        print()
