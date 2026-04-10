# Multi-stage build for Java Maven applications
# Java version is configurable: 17 for data-harvester, 21 for nurix-tools
# Usage: docker build --build-arg JAVA_VERSION=17 ...
ARG JAVA_VERSION=21
FROM eclipse-temurin:${JAVA_VERSION}-jdk-alpine AS base
ARG BUILD_ENV=dev
ARG MAVEN_PROFILES=""
ARG MAVEN_ARGS="-T 4C -B --no-transfer-progress"
ARG PORT=8080
ARG PROJECT_TYPE=auto
ARG JAVA_VERSION

# Install Maven and dependencies
RUN apk add --no-cache curl maven

# Install dependencies only when needed
FROM base AS deps
WORKDIR /app

# Copy root pom.xml first
COPY pom.xml ./

# Copy entire build context to temp location to check for modules
COPY . /build-context/

# Detect project structure and copy module pom.xml files if needed
# For multi-module projects, Maven needs module directories to resolve dependencies
RUN \
  # Detect if this is a multi-module project
  if grep -q '<packaging>pom</packaging>' pom.xml 2>/dev/null && grep -q '<modules>' pom.xml 2>/dev/null; then \
    echo "IS_MULTI_MODULE=true" > /tmp/build-info && \
    echo "Detected multi-module Maven project" && \
    # Extract module names from pom.xml \
    grep -A 100 '<modules>' pom.xml | grep '<module>' | sed 's/.*<module>\(.*\)<\/module>.*/\1/' | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//' > /tmp/modules.txt && \
    echo "Found modules:" && cat /tmp/modules.txt && \
    # Copy each module directory (needed for Maven dependency resolution) \
    while IFS= read -r module_name; do \
      if [ -n "$module_name" ] && [ -d "/build-context/$module_name" ]; then \
        echo "Copying module $module_name for dependency resolution..." && \
        cp -r "/build-context/$module_name" "./$module_name"; \
      elif [ -n "$module_name" ]; then \
        echo "Warning: Module '$module_name' declared but directory not found"; \
      fi; \
    done < /tmp/modules.txt; \
  else \
    echo "IS_MULTI_MODULE=false" > /tmp/build-info && \
    echo "Detected single-module Maven project"; \
  fi && \
  # Clean up build context \
  rm -rf /build-context

# Setup Maven settings with GitHub token for private repositories
RUN --mount=type=secret,id=git_token \
    mkdir -p /root/.m2 && \
    if [ -f /run/secrets/git_token ]; then \
      GIT_TOKEN=$(cat /run/secrets/git_token) && \
      echo '<settings>' > /root/.m2/settings.xml && \
      echo '  <servers>' >> /root/.m2/settings.xml && \
      echo '    <server>' >> /root/.m2/settings.xml && \
      echo '      <id>github</id>' >> /root/.m2/settings.xml && \
      echo '      <username>github</username>' >> /root/.m2/settings.xml && \
      echo "      <password>${GIT_TOKEN}</password>" >> /root/.m2/settings.xml && \
      echo '    </server>' >> /root/.m2/settings.xml && \
      echo '  </servers>' >> /root/.m2/settings.xml && \
      echo '</settings>' >> /root/.m2/settings.xml; \
    else \
      echo '<settings>' > /root/.m2/settings.xml && \
      echo '</settings>' >> /root/.m2/settings.xml; \
    fi

# Download dependencies
RUN --mount=type=secret,id=git_token \
  echo "Checking for pom.xml..." && \
  ls -la && \
  if [ -f pom.xml ]; then \
    echo "Found pom.xml, downloading dependencies with Maven..." && \
    mkdir -p /root/.m2/repository && \
    mvn dependency:go-offline ${MAVEN_ARGS} || \
    mvn dependency:resolve ${MAVEN_ARGS} || true; \
  else \
    echo "No pom.xml found. Available files:" && \
    ls -la && \
    exit 1; \
  fi && \
  # Ensure repository directory exists even if no dependencies were downloaded
  mkdir -p /root/.m2/repository

# Build the source code only when needed
FROM base AS builder
WORKDIR /app

# Copy Maven repository from deps stage
RUN mkdir -p /root/.m2
COPY --from=deps /root/.m2 /root/.m2

# Copy root pom.xml first
COPY pom.xml ./

# Copy entire build context to temp location
# This COPY always succeeds (copying everything), then we selectively use what we need
COPY . /build-context/

# Dynamically extract module names from pom.xml and copy them
# If modules exist, copy them; otherwise copy root src/ for single-module projects
RUN \
  echo "Analyzing project structure from pom.xml..." && \
  # Check if this is a multi-module project \
  if grep -q '<packaging>pom</packaging>' pom.xml 2>/dev/null && grep -q '<modules>' pom.xml 2>/dev/null; then \
    echo "Multi-module project detected - extracting module names..." && \
    # Extract module names from <modules> section \
    grep -A 100 '<modules>' pom.xml | grep '<module>' | sed 's/.*<module>\(.*\)<\/module>.*/\1/' | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//' > /tmp/modules.txt && \
    echo "Found modules:" && cat /tmp/modules.txt && \
    # Copy each module directory if it exists \
    while IFS= read -r module_name; do \
      if [ -n "$module_name" ] && [ -d "/build-context/$module_name" ]; then \
        echo "Copying module: $module_name" && \
        cp -r "/build-context/$module_name" "./$module_name"; \
      elif [ -n "$module_name" ]; then \
        echo "Warning: Module '$module_name' declared in pom.xml but directory not found"; \
      fi; \
    done < /tmp/modules.txt; \
  else \
    echo "Single-module project detected - copying root src/ if it exists" && \
    # For single-module projects, copy root src/ \
    if [ -d "/build-context/src" ]; then \
      echo "Copying root src/ directory..." && \
      cp -r /build-context/src ./src; \
    else \
      echo "Error: Single-module project but src/ directory not found" && exit 1; \
    fi; \
  fi && \
  # Clean up build context \
  rm -rf /build-context /tmp/modules.txt

# Verify project structure
RUN \
  if grep -q '<packaging>pom</packaging>' pom.xml 2>/dev/null && grep -q '<modules>' pom.xml 2>/dev/null; then \
    echo "Multi-module project - verifying modules..." && \
    # Extract and verify each module \
    grep -A 100 '<modules>' pom.xml | grep '<module>' | sed 's/.*<module>\(.*\)<\/module>.*/\1/' | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//' | while IFS= read -r module_name; do \
      if [ -n "$module_name" ]; then \
        if [ -d "$module_name" ] && [ -f "$module_name/pom.xml" ]; then \
          echo "Verified module: $module_name"; \
        else \
          echo "Warning: Module '$module_name' missing or incomplete"; \
        fi; \
      fi; \
    done; \
  else \
    echo "Single-module project - verifying root src/ exists" && \
    if [ ! -d "src" ]; then \
      echo "Error: Single-module project but src/ directory not found" && exit 1; \
    else \
      echo "Verified: root src/ exists"; \
    fi; \
  fi

# Setup Maven settings with GitHub token
RUN --mount=type=secret,id=git_token \
    mkdir -p /root/.m2 && \
    if [ -f /run/secrets/git_token ]; then \
      GIT_TOKEN=$(cat /run/secrets/git_token) && \
      echo '<settings>' > /root/.m2/settings.xml && \
      echo '  <servers>' >> /root/.m2/settings.xml && \
      echo '    <server>' >> /root/.m2/settings.xml && \
      echo '      <id>github</id>' >> /root/.m2/settings.xml && \
      echo '      <username>github</username>' >> /root/.m2/settings.xml && \
      echo "      <password>${GIT_TOKEN}</password>" >> /root/.m2/settings.xml && \
      echo '    </server>' >> /root/.m2/settings.xml && \
      echo '  </servers>' >> /root/.m2/settings.xml && \
      echo '</settings>' >> /root/.m2/settings.xml; \
    else \
      echo '<settings>' > /root/.m2/settings.xml && \
      echo '</settings>' >> /root/.m2/settings.xml; \
    fi

# Build the application
RUN --mount=type=secret,id=git_token \
    echo "Building for environment: ${BUILD_ENV}" && \
    echo "Maven profiles: ${MAVEN_PROFILES}" && \
    if [ -n "${MAVEN_PROFILES}" ]; then \
      echo "Building with profiles: ${MAVEN_PROFILES}" && \
      mvn clean package -P${MAVEN_PROFILES} ${MAVEN_ARGS} -DskipTests; \
    else \
      echo "Building without profiles" && \
      mvn clean package ${MAVEN_ARGS} -DskipTests; \
    fi && \
    echo "Build completed. JAR files:" && \
    find . -name "*.jar" -type f

# Production image, copy the JAR and run the application
# Use same Java version as build stage
ARG JAVA_VERSION=21
FROM eclipse-temurin:${JAVA_VERSION}-jre-alpine AS runner
ARG JAVA_VERSION
ARG PORT=8080
WORKDIR /app

RUN apk add --no-cache curl ffmpeg

ENV JAVA_OPTS="-Xms512m -Xmx1g" \
    PORT=${PORT}

RUN addgroup --system --gid 1001 javauser && \
    adduser --system --uid 1001 javauser

# Copy target directories - handle both single-module (root target) and multi-module (module targets)
# For single-module: JAR is in /app/target
# For multi-module: JAR is in /app/<module>/target (e.g., /app/seeder/target)
# We'll copy the entire /app directory structure and search for JARs
COPY --from=builder --chown=javauser:javauser /app /tmp/app-source

# Find JAR in both root target and module target directories
# This works for both single-module (finds in /app/target) and multi-module (finds in /app/<module>/target)
RUN \
  echo "Searching for executable JAR files..." && \
  JAR_FILE=$(find /tmp/app-source -path "*/target/*.jar" \
    -not -name "*sources.jar" \
    -not -name "*javadoc.jar" \
    -type f \
    -exec sh -c 'unzip -p "$1" META-INF/MANIFEST.MF 2>/dev/null | grep -q "^Main-Class:" && echo "$1"' _ {} \; \
    | head -1) && \
  if [ -z "$JAR_FILE" ]; then \
    echo "Error: No executable JAR with Main-Class found" && \
    exit 1; \
  fi && \
  echo "Selected executable JAR: $JAR_FILE" && \
  mv "$JAR_FILE" /app/app.jar && \
  rm -rf /tmp/app-source && \ 
  echo "JAR file copied and renamed successfully"
  
# Create entrypoint script to find and run the JAR
RUN echo '#!/bin/sh' > /app/entrypoint.sh && \
    echo 'JAR_FILE=$(find /app -name "*.jar" -not -name "*sources.jar" -not -name "*javadoc.jar" -type f | head -1)' >> /app/entrypoint.sh && \
    echo 'if [ -z "$JAR_FILE" ]; then' >> /app/entrypoint.sh && \
    echo '  echo "Error: No JAR file found in /app"' >> /app/entrypoint.sh && \
    echo '  ls -la /app' >> /app/entrypoint.sh && \
    echo '  exit 1' >> /app/entrypoint.sh && \
    echo 'fi' >> /app/entrypoint.sh && \
    echo 'echo "Starting application with JAR: $(basename $JAR_FILE)"' >> /app/entrypoint.sh && \
    echo 'exec java $JAVA_OPTS -jar "$JAR_FILE" --server.port=${PORT:-8080}' >> /app/entrypoint.sh && \
    chmod +x /app/entrypoint.sh

# Create necessary directories and ensure proper ownership
RUN mkdir -p /app/logs /app/tmp && \
    chown -R javauser:javauser /app && \
    chmod 755 /app && \
    echo "Verifying permissions:" && \
    ls -la /app/

USER javauser

EXPOSE ${PORT}

# Run the Spring Boot application
ENTRYPOINT ["/app/entrypoint.sh"]