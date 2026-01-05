# =============================================================================
# JMeter Distributed Testing - Docker Image
# =============================================================================
# Multi-stage build for optimized image size
# Supports both controller and worker modes via entrypoint
# =============================================================================

ARG JMETER_VERSION=5.6.3
ARG JAVA_VERSION=17

# -----------------------------------------------------------------------------
# Stage 1: Download and prepare JMeter
# -----------------------------------------------------------------------------
FROM amazoncorretto:${JAVA_VERSION} AS builder

ARG JMETER_VERSION

# Install curl for downloading
RUN yum update -y && yum install -y \
    curl \
    tar \
    gzip \
    && yum clean all && rm -rf /var/cache/yum

# Download and extract JMeter
WORKDIR /tmp
RUN curl -fsSL https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-${JMETER_VERSION}.tgz \
    | tar -xzf - -C /opt && \
    mv /opt/apache-jmeter-${JMETER_VERSION} /opt/jmeter

# Remove unnecessary files to reduce image size
RUN rm -rf /opt/jmeter/docs /opt/jmeter/printable_docs

# -----------------------------------------------------------------------------
# Stage 2: Final runtime image
# -----------------------------------------------------------------------------
FROM amazoncorretto:${JAVA_VERSION}

LABEL maintainer="Performance Engineering Team"
LABEL description="JMeter distributed testing image with plugin support"

# Environment variables
ENV JMETER_HOME=/opt/jmeter
ENV PATH="${JMETER_HOME}/bin:${PATH}"
ENV JMETER_MODE="worker"
ENV HEAP="-Xms1g -Xmx1g -XX:MaxMetaspaceSize=256m"

# JMeter distributed testing ports
# 1099: RMI registry port
# 50000: Server port (for receiving test from controller)
# 50001: Local port (for sending results back)
ENV RMI_PORT=1099
ENV SERVER_PORT=50000
ENV LOCAL_PORT=50001

# Install runtime dependencies
RUN yum update -y && yum install -y \
    curl \
    nc \
    bind-utils \
    procps-ng \
    && yum clean all && rm -rf /var/cache/yum

# Copy JMeter from builder stage
COPY --from=builder /opt/jmeter ${JMETER_HOME}

# Create directories for test artifacts
RUN mkdir -p /jmeter/test-plans /jmeter/results /jmeter/plugins

# Copy plugins from build context (ext/ folder)
# These are copied at build time, ensuring consistent plugin versions
# COPY ext/*.jar ${JMETER_HOME}/lib/ext/

# Copy custom properties if provided
# COPY docker/jmeter.properties ${JMETER_HOME}/bin/jmeter.properties
# COPY docker/user.properties ${JMETER_HOME}/bin/user.properties

# Copy entrypoint script
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Configure JMeter for distributed testing
RUN echo "" >> ${JMETER_HOME}/bin/jmeter.properties && \
    echo "# Distributed testing configuration" >> ${JMETER_HOME}/bin/jmeter.properties && \
    echo "server.rmi.ssl.disable=true" >> ${JMETER_HOME}/bin/jmeter.properties && \
    echo "server.rmi.localport=${LOCAL_PORT}" >> ${JMETER_HOME}/bin/jmeter.properties && \
    echo "server_port=${SERVER_PORT}" >> ${JMETER_HOME}/bin/jmeter.properties && \
    echo "client.rmi.localport=0" >> ${JMETER_HOME}/bin/jmeter.properties

# Health check - verify JMeter is accessible
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD jmeter --version || exit 1

# Expose ports for distributed testing
EXPOSE ${RMI_PORT} ${SERVER_PORT} ${LOCAL_PORT}

# Working directory for test execution
WORKDIR /jmeter

# Default entrypoint
ENTRYPOINT ["/entrypoint.sh"]

# No default command - let JMETER_MODE environment variable control behavior
CMD []