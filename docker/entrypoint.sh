#!/bin/bash
# =============================================================================
# JMeter Entrypoint Script
# =============================================================================
# Handles both controller and worker modes for distributed testing
# Environment variables control behavior:
#   JMETER_MODE: "controller" or "worker" (default: worker)
#   REMOTE_HOSTS: comma-separated list of worker hosts (controller mode only)
#   SERVER_PORT: JMeter server port (default: 50000)
#   RMI_HOST: hostname/IP for RMI (auto-detected if not set)
# =============================================================================

set -e

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
JMETER_MODE="${JMETER_MODE:-worker}"
SERVER_PORT="${SERVER_PORT:-50000}"
LOCAL_PORT="${LOCAL_PORT:-50001}"
RMI_PORT="${RMI_PORT:-1099}"

# Auto-detect hostname if not provided
if [ -z "$RMI_HOST" ]; then
    # Try to get the container's IP address
    RMI_HOST=$(hostname -i 2>/dev/null | awk '{print $1}' || hostname -f)
fi

# JVM heap settings
HEAP="${HEAP:--Xms1g -Xmx1g -XX:MaxMetaspaceSize=256m}"

# -----------------------------------------------------------------------------
# Functions
# -----------------------------------------------------------------------------

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

wait_for_workers() {
    # Wait for worker nodes to be ready (controller mode)
    local workers="$1"
    local timeout="${2:-120}"
    local start_time=$(date +%s)
    
    log "Waiting for workers to be ready: $workers"
    
    IFS=',' read -ra WORKER_ARRAY <<< "$workers"
    for worker in "${WORKER_ARRAY[@]}"; do
        # Extract host and port
        local host=$(echo "$worker" | cut -d: -f1)
        local port=$(echo "$worker" | cut -d: -f2)
        port="${port:-$SERVER_PORT}"
        
        log "Checking worker: $host:$port"
        
        while ! nc -z "$host" "$port" 2>/dev/null; do
            local elapsed=$(($(date +%s) - start_time))
            if [ $elapsed -ge $timeout ]; then
                log "ERROR: Timeout waiting for worker $host:$port"
                return 1
            fi
            log "Worker $host:$port not ready, retrying in 5s..."
            sleep 5
        done
        
        log "Worker $host:$port is ready"
    done
    
    log "All workers ready"
    return 0
}

start_worker() {
    log "Starting JMeter in WORKER mode"
    log "RMI Host: $RMI_HOST"
    log "Server Port: $SERVER_PORT"
    log "Local Port: $LOCAL_PORT"
    
    # Set JVM options
    export JVM_ARGS="$HEAP -Djava.rmi.server.hostname=$RMI_HOST"
    
    # Start JMeter server (worker mode)
    exec jmeter-server \
        -Dserver.rmi.ssl.disable=true \
        -Dserver_port="$SERVER_PORT" \
        -Dserver.rmi.localport="$LOCAL_PORT" \
        -Djava.rmi.server.hostname="$RMI_HOST"
}

run_controller() {
    log "Starting JMeter in CONTROLLER mode"
    
    # Validate required parameters
    if [ -z "$REMOTE_HOSTS" ]; then
        log "WARNING: REMOTE_HOSTS not set. Running in local mode."
    fi
    
    # Build the JMeter command
    local jmeter_cmd="jmeter"
    local jmeter_args=()
    
    # Add remote hosts if specified
    if [ -n "$REMOTE_HOSTS" ]; then
        log "Remote hosts: $REMOTE_HOSTS"
        jmeter_args+=("-R" "$REMOTE_HOSTS")
        
        # Wait for workers to be ready
        if ! wait_for_workers "$REMOTE_HOSTS"; then
            log "ERROR: Workers not available. Aborting."
            exit 1
        fi
    fi
    
    # Set JVM options
    export JVM_ARGS="$HEAP -Djava.rmi.server.hostname=$RMI_HOST"
    
    # Add SSL disable flag for distributed mode
    jmeter_args+=("-Dserver.rmi.ssl.disable=true")
    
    # Pass through all remaining arguments
    jmeter_args+=("$@")
    
    log "Executing: $jmeter_cmd ${jmeter_args[*]}"
    
    # Run JMeter
    exec "$jmeter_cmd" "${jmeter_args[@]}"
}

show_help() {
    cat << EOF
JMeter Distributed Testing Container

MODES:
  worker      - Start as a JMeter worker (server mode)
  controller  - Run as controller, execute test plans

ENVIRONMENT VARIABLES:
  JMETER_MODE     Mode to run in (worker|controller). Default: worker
  REMOTE_HOSTS    Comma-separated worker hosts (controller mode)
  RMI_HOST        Hostname/IP for RMI. Auto-detected if not set.
  SERVER_PORT     JMeter server port. Default: 50000
  LOCAL_PORT      Local RMI port. Default: 50001
  HEAP            JVM heap settings. Default: -Xms1g -Xmx1g

EXAMPLES:
  # Start as worker
  docker run -e JMETER_MODE=worker jmeter-distributed

  # Run test with remote workers
  docker run -e JMETER_MODE=controller \\
             -e REMOTE_HOSTS=worker1:50000,worker2:50000 \\
             -v ./test.jmx:/jmeter/test.jmx \\
             jmeter-distributed -n -t /jmeter/test.jmx -l /jmeter/results.jtl

  # Run JMeter commands directly
  docker run jmeter-distributed jmeter -v

For more information, see the project README.
EOF
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

case "$1" in
    --help|-h)
        show_help
        exit 0
        ;;
    worker)
        start_worker
        ;;
    controller)
        shift  # Remove 'controller' from args
        run_controller "$@"
        ;;
    jmeter|jmeter-server)
        # Direct JMeter execution
        exec "$@"
        ;;
    *)
        # Check JMETER_MODE environment variable
        case "$JMETER_MODE" in
            worker)
                start_worker
                ;;
            controller)
                run_controller "$@"
                ;;
            *)
                # Default: pass through to JMeter
                if [ $# -eq 0 ]; then
                    show_help
                else
                    exec jmeter "$@"
                fi
                ;;
        esac
        ;;
esac
