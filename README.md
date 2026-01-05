# JMeter Distributed Testing Framework

A production-ready framework for running distributed Apache JMeter load tests using Docker containers and AWS EC2 instances.

## Features

- **Dual execution modes**: Run tests locally with Docker or at scale on AWS EC2
- **Spot instance support**: Up to 90% cost savings on worker nodes
- **Plugin management**: Drop JARs in `ext/` folder, automatically included in builds
- **Instance profiles**: Pre-configured small/medium/large cluster configurations
- **CI/CD ready**: Jenkins and GitHub Actions pipelines included
- **Results management**: Automatic collection, HTML report generation, S3 upload
- **Infrastructure as Code**: Automated provisioning and teardown

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.9+
- AWS CLI configured (for AWS mode)
- SSH key pair in AWS (for AWS mode)

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd jmeter-distributed-framework

# Install Python dependencies
pip install -r requirements.txt

# Build the Docker image
make build
```

### Run a Local Test (Docker)

```bash
# Start 2 workers and run a test
make run-local

# Or with a custom test plan
python scripts/orchestrator.py run \
    --mode docker \
    --test-plan test-plans/your-test.jmx \
    --workers 2
```

### Run on AWS EC2

```bash
# Using the medium instance profile (5 workers)
python scripts/orchestrator.py run \
    --mode aws \
    --test-plan test-plans/your-test.jmx \
    --profile medium

# With custom JMeter properties
python scripts/orchestrator.py run \
    --mode aws \
    --test-plan test-plans/your-test.jmx \
    --profile large \
    -J threads=500 \
    -J rampup=120 \
    -J duration=600
```

## Project Structure

```
jmeter-distributed-framework/
├── docker/                    # Docker configuration
│   ├── Dockerfile             # JMeter image with plugin support
│   ├── docker-compose.yml     # Local development compose
│   └── entrypoint.sh          # Controller/worker mode handler
├── ext/                       # Plugin JARs (copied to image)
├── test-plans/                # JMeter .jmx files
├── results/                   # Test results (gitignored)
├── scripts/                   # Python orchestration
│   ├── orchestrator.py        # Main CLI entry point
│   ├── aws_manager.py         # EC2 provisioning
│   ├── docker_manager.py      # Local Docker orchestration
│   ├── jmeter_runner.py       # JMeter execution
│   └── results_collector.py   # Results handling
├── config/
│   ├── framework.yaml         # Main configuration
│   └── instance-profiles/     # EC2 instance presets
├── jenkins/                   # Jenkins pipeline
└── .github/workflows/         # GitHub Actions
```

## Configuration

### Framework Configuration (`config/framework.yaml`)

Key settings:

```yaml
aws:
  region: "us-east-1"
  ec2:
    ami_id: "ami-0c7217cdde317cfec"  # Ubuntu 22.04
    key_pair_name: "jmeter-framework-key"
    controller:
      instance_type: "c5.xlarge"
      use_spot: false
    worker:
      instance_type: "c5.xlarge"
      use_spot: true
  s3:
    bucket_name: "your-bucket-name"

jmeter:
  version: "5.6.3"
  heap:
    controller: "-Xms2g -Xmx4g"
    worker: "-Xms2g -Xmx4g"
```

### Instance Profiles

| Profile | Workers | Instance Type | Max Users | Est. Cost/Hour |
|---------|---------|---------------|-----------|----------------|
| small   | 2       | t3.medium     | ~5,000    | ~$0.50         |
| medium  | 5       | c5.xlarge     | ~25,000   | ~$2.50         |
| large   | 10      | c5.2xlarge    | ~50,000   | ~$8.00         |

## CLI Reference

### Commands

```bash
# Run a test
python scripts/orchestrator.py run [options]

# Provision infrastructure only
python scripts/orchestrator.py provision [options]

# Tear down infrastructure
python scripts/orchestrator.py teardown [options]

# Show status
python scripts/orchestrator.py status

# Build Docker image
python scripts/orchestrator.py build [options]
```

### Run Options

| Option | Description | Default |
|--------|-------------|---------|
| `-m, --mode` | Execution mode (docker/aws) | docker |
| `-t, --test-plan` | Path to .jmx file | Required |
| `-w, --workers` | Number of workers | 2 |
| `-p, --profile` | Instance profile (AWS) | - |
| `-J PROP=VAL` | JMeter property | - |
| `--results-dir` | Results directory | results |
| `--no-html-report` | Skip HTML report | false |
| `--no-s3-upload` | Skip S3 upload | false |
| `--keep-infra` | Keep AWS instances | false |

### JMeter Properties

Pass JMeter properties using `-J`:

```bash
python scripts/orchestrator.py run \
    --mode docker \
    --test-plan test.jmx \
    -J threads=100 \
    -J rampup=60 \
    -J duration=300 \
    -J target_host=api.example.com
```

## Adding Plugins

1. Download plugin JAR files
2. Place them in the `ext/` directory
3. Rebuild the Docker image: `make build`

Plugins are automatically copied to `$JMETER_HOME/lib/ext/` during image build.

## AWS Setup

### Prerequisites

1. **AWS CLI configured** with appropriate credentials
2. **EC2 Key Pair** created and private key saved to `~/.ssh/<key-name>.pem`
3. **S3 Bucket** for results storage (optional)

### IAM Permissions

The AWS user/role needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:RunInstances",
        "ec2:TerminateInstances",
        "ec2:DescribeInstances",
        "ec2:CreateSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeKeyPairs",
        "ec2:CreateTags"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::your-bucket/*",
        "arn:aws:s3:::your-bucket"
      ]
    }
  ]
}
```

### First Run

```bash
# 1. Create EC2 key pair (if not exists)
aws ec2 create-key-pair --key-name jmeter-framework-key \
    --query 'KeyMaterial' --output text > ~/.ssh/jmeter-framework-key.pem
chmod 400 ~/.ssh/jmeter-framework-key.pem

# 2. Update config/framework.yaml with your settings

# 3. Run a test
python scripts/orchestrator.py run \
    --mode aws \
    --test-plan test-plans/sample-http-test.jmx \
    --profile small
```

## CI/CD Integration

### Jenkins

1. Create a new Pipeline job
2. Point to `jenkins/Jenkinsfile`
3. Configure AWS credentials in Jenkins
4. Run with parameters

### GitHub Actions

1. Add secrets to repository:
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
2. Trigger via workflow_dispatch or push to main

## Results

### Local Results

Results are saved to `results/<run-id>/`:
- `*.jtl` - Raw JMeter results
- `html-report/` - JMeter dashboard

### S3 Upload

Results are uploaded to:
```
s3://<bucket>/results/<run-id>/
```

### View Results

```bash
# Generate summary from JTL file
python -c "
from scripts.results_collector import ResultsCollector
from scripts.config_loader import ConfigLoader

config = ConfigLoader('config/framework.yaml').load()
collector = ResultsCollector(config)
collector.print_summary('results/run-id/test.jtl')
"
```

## Troubleshooting

### Docker Issues

```bash
# View container logs
make logs

# Check container status
docker-compose -f docker/docker-compose.yml ps

# Rebuild without cache
make build-no-cache
```

### AWS Issues

```bash
# Check running instances
python scripts/orchestrator.py status

# Force teardown
python scripts/orchestrator.py teardown --mode aws --force

# View AWS instances directly
aws ec2 describe-instances \
    --filters "Name=tag:ManagedBy,Values=jmeter-distributed-framework"
```

### JMeter Issues

- **RMI connection errors**: Check security group allows ports 1099, 50000, 50001
- **Out of memory**: Increase heap in config or profile YAML
- **Slow test start**: Workers need time to initialize; check logs

## Performance Tuning

### JMeter Settings

```yaml
jmeter:
  heap:
    controller: "-Xms4g -Xmx8g -XX:MaxMetaspaceSize=512m"
    worker: "-Xms4g -Xmx8g -XX:MaxMetaspaceSize=256m"
```

### Instance Selection Guide

| Concurrent Users | Recommended Profile | Instance Type |
|-----------------|---------------------|---------------|
| < 5,000         | small               | t3.medium     |
| 5,000 - 25,000  | medium              | c5.xlarge     |
| 25,000 - 50,000 | large               | c5.2xlarge    |
| > 50,000        | Custom              | c5.4xlarge+   |

### Network Optimization

For high throughput tests, consider:
- Placement groups for workers
- Enhanced networking instances
- Same-AZ deployment

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

## License

MIT License - see LICENSE file for details.
