# ===========================================================================================================
# 0. Builder stage 1
# ===========================================================================================================
# JAVA_VERSION: major version only (e.g. 17, 21). Passed from gsw-java-gradle-build workflow as build-arg.
ARG JAVA_VERSION=17
FROM eclipse-temurin:${JAVA_VERSION}-jdk AS builder
ARG BUILD_PATH
ARG SERVICE_NAME
ARG PORT

# Copy the project directly onto the image
COPY . /${BUILD_PATH}
WORKDIR /${BUILD_PATH}

# Build the server on run
RUN ./gradlew build -x test

# ===========================================================================================================
# 2. Bin stage
# ===========================================================================================================
FROM alpine:3.19
ARG JAVA_VERSION=17
ARG BUILD_PATH
ARG SERVICE_NAME
ARG PORT
ARG JAR_PATH
ARG JAR_NAME

RUN apk add --no-cache openjdk${JAVA_VERSION}-jre curl

# Make app folders
RUN mkdir -p /app/config /app/logs /app/libs

# Copy the compiled output to new image
COPY helm/server/bin /app
COPY helm/server/config /app/config
COPY --from=builder /${BUILD_PATH}/${JAR_PATH} /app/libs/${JAR_NAME}

# Copy the files for the server into the app folders
RUN chmod +x /app/startup.sh

HEALTHCHECK --interval=60s --timeout=30s --retries=10 CMD curl -I -XGET http://localhost:${PORT}/health || exit 1

CMD [ "/app/startup.sh" ]
ENTRYPOINT [ "/bin/sh"]
