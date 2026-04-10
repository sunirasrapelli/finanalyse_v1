# Python Service Helm Chart

A flexible Helm chart for deploying Python microservices on Kubernetes.

## Overview

This chart provides a comprehensive solution for deploying Python applications with the following features:

- **Flexible Configuration**: Supports different deployment types (worker, api, service)
- **Environment-specific Values**: Separate values files for different environments
- **Auto-scaling**: Built-in HPA support
- **KEDA Integration**: Event-driven autoscaling with support for CPU, memory, SQS, and cron triggers
- **Health Checks**: Configurable liveness and readiness probes
- **Security**: Service accounts, security contexts, and RBAC
- **Monitoring**: Labels and annotations for observability
- **Prometheus Integration**: Optional `ServiceMonitor` resource for kube-prometheus-stack
- **tmpfs (in-memory volumes)**: Optional RAM-backed volumes for scratch/temp data

## Chart Structure

```
python-service/
├── Chart.yaml                 # Chart metadata
├── values.yaml               # Default values
├── values-stage.yaml         # Stage environment values
├── values-prod.yaml          # Production environment values
├── templates/
│   ├── deployment.yaml       # Application deployment
│   ├── service.yaml          # Kubernetes service
│   ├── ingress.yaml          # Ingress configuration
│   ├── hpa.yaml             # Horizontal Pod Autoscaler
│   ├── configmap.yaml       # Configuration data
│   ├── serviceaccount.yaml  # Service account
│   └── _helpers.tpl         # Template helpers
└── README.md                # This file
```

## Installation

### Prerequisites

- Kubernetes 1.19+
- Helm 3.0+

### Install Chart

```bash
# Add the base-helm-charts repository
helm repo add base-helm-charts https://your-org.github.io/base-helm-charts

# Update repository
helm repo update

# Install with default values
helm install voicex-worker base-helm-charts/python-service

# Install with environment-specific values
helm install voicex-worker base-helm-charts/python-service -f values-stage.yaml

# Install with custom values
helm install voicex-worker base-helm-charts/python-service \
  --set application.image.tag=stage-abc123 \
  --set application.image.registry=123456789.dkr.ecr.ap-south-1.amazonaws.com
```

## Configuration

### Required Values

The following values must be set during deployment:

```yaml
application:
  image:
    registry: "123456789.dkr.ecr.ap-south-1.amazonaws.com"
    tag: "stage-abc123"

global:
  aws:
    accountId: "123456789"
```

### Chart Versioning Strategy

The chart version aligns with your application versioning:

- **Main branch**: `1.{BUILD_NUMBER}.0` (e.g., `1.123.0`)
- **Stage branch**: `0.{BUILD_NUMBER}.0-rc` (e.g., `0.123.0-rc`)
- **Feature branches**: `0.0.{BUILD_NUMBER}-{BRANCH}` (e.g., `0.0.123-feature-auth`)

### Application Types

Configure different application types using the `application.type` value:

```yaml
application:
  type: worker    # worker, api, service
```

Each type has different default configurations:

- **worker**: Background processing, no ingress, HPA enabled
- **api**: HTTP API, ingress enabled, service exposed
- **service**: Internal service, ClusterIP service, moderate scaling

## Environment-Specific Configurations

### Stage Environment (`values-stage.yaml`)

- Lower resource limits
- Smaller HPA ranges
- Debug logging enabled
- Development-friendly settings

### Production Environment (`values-prod.yaml`)

- Higher resource limits
- Larger HPA ranges
- Production logging levels
- Security hardened
- Pod Disruption Budgets enabled

## Values Reference

### Global Settings

| Parameter | Description | Default |
|-----------|-------------|---------|
| `global.environment` | Environment name | `stage` |
| `global.aws.region` | AWS region | `ap-south-1` |
| `global.aws.accountId` | AWS account ID | `""` |

### Application Settings

| Parameter | Description | Default |
|-----------|-------------|---------|
| `application.name` | Application name | `voicex-worker` |
| `application.type` | Application type (worker/api/service) | `worker` |
| `application.image.repository` | Image repository | `voicex-worker` |
| `application.image.tag` | Image tag | `""` |
| `application.image.registry` | Image registry | `""` |

### Resources

| Parameter | Description | Default |
|-----------|-------------|---------|
| `application.resources.requests.memory` | Memory requests | `2Gi` |
| `application.resources.requests.cpu` | CPU requests | `1000m` |
| `application.resources.limits.memory` | Memory limits | `4Gi` |
| `application.resources.limits.cpu` | CPU limits | `2000m` |

### tmpfs (in-memory volumes)

Optional RAM-backed volumes for scratch or temporary data. Uses Kubernetes `emptyDir` with `medium: Memory` (tmpfs). Data is stored in node RAM, not disk, and is cleared when the pod is removed.

| Parameter | Description | Default |
|-----------|-------------|---------|
| `tmpfs.enabled` | Enable tmpfs volumes | `false` |
| `tmpfs.volumes` | List of tmpfs volume definitions | `[]` |

Each entry in `tmpfs.volumes` supports:

| Field | Description | Required |
|-------|-------------|----------|
| `name` | Volume name | Yes |
| `mountPath` | Path in the container (e.g. `/tmp`, `/app/cache`) | Yes |
| `sizeLimit` | Memory limit for the volume (e.g. `1Gi`, `512Mi`) | No |

Example:

```yaml
tmpfs:
  enabled: true
  volumes:
    - name: tmp
      mountPath: /tmp
      sizeLimit: 1Gi
    - name: cache
      mountPath: /app/cache
      sizeLimit: 512Mi
```

**Note:** tmpfs usage counts toward the pod's memory. Ensure container memory limits account for tmpfs size limits if set.

### Auto-scaling

| Parameter | Description | Default |
|-----------|-------------|---------|
| `hpa.enabled` | Enable HPA | `true` |
| `hpa.minReplicas` | Minimum replicas | `1` |
| `hpa.maxReplicas` | Maximum replicas | `10` |
| `hpa.targetCPUUtilizationPercentage` | CPU target | `80` |

### KEDA Configuration

KEDA (Kubernetes Event-Driven Autoscaling) provides advanced autoscaling capabilities beyond traditional HPA, supporting event-driven scaling based on various trigger types. The chart uses a flexible configuration approach that allows you to configure any KEDA trigger type without template restrictions.

#### Basic KEDA Setup

```yaml
keda:
  enabled: true
  minReplicas: 1  # Required: Minimum number of replicas
  maxReplicas: 10  # Required: Maximum number of replicas
  triggers: []
```

**Note:** `minReplicas` and `maxReplicas` are required when `keda.enabled` is `true`. These values must be explicitly set in your values file.

#### Trigger Configuration

The `triggers` array accepts any valid KEDA trigger configuration. You can configure multiple triggers of different types. The chart passes triggers directly to the KEDA ScaledObject, giving you full flexibility.

**Available Trigger Types:**
- CPU/Memory metrics
- AWS SQS, SNS, Kinesis
- Cron schedules
- Prometheus, Datadog, New Relic
- Kafka, RabbitMQ, Redis
- And many more (see [KEDA Scalers Documentation](https://keda.sh/docs/scalers/))

#### Example: CPU and Memory-Based Scaling

```yaml
keda:
  enabled: true
  minReplicas: 1
  maxReplicas: 10
  
  triggers:
    # CPU-based scaling trigger
    - type: cpu
      metricType: Utilization
      metadata:
        value: "70"  # Scale when CPU usage exceeds 70%
    
    # Memory-based scaling trigger
    - type: memory
      metricType: Utilization
      metadata:
        value: "80"  # Scale when memory usage exceeds 80%
```

#### Example: SQS Queue-Based Scaling

```yaml
keda:
  enabled: true
  minReplicas: 1
  maxReplicas: 10
  
  triggers:
    # SQS queue depth-based scaling trigger
    - type: aws-sqs-queue
      metadata:
        awsRegion: "ap-south-1"
        identityOwner: "operator"  # or "pod"
        queueURL: "https://sqs.ap-south-1.amazonaws.com/533266975263/my-queue-name"
        queueLength: "5"  # Scale when queue has 5+ messages per pod
        scaleOnInFlight: "true"   # Include in-flight messages
        scaleOnDelayed: "false"   # Include delayed messages
```

**Note:** For AWS-based scalers:
- `awsRegion` and `identityOwner` are set in the trigger metadata (not at spec level)
- `identityOwner` specifies the authentication identity: `operator` (KEDA operator) or `pod` (pod identity)

#### Example: Time-Based Scaling (Cron Trigger)

```yaml
keda:
  enabled: true
  minReplicas: 1
  maxReplicas: 10
  
  triggers:
    # Time-based scaling (Cron trigger)
    - type: cron
      metadata:
        timezone: "Asia/Kolkata"
        start: "30 8 * * *"   # Start time: 8:30 AM every day
        end: "0 22 * * *"     # End time: 10:00 PM every day
        desiredReplicas: "3"  # Minimum replicas during active window
```

#### Example: Multiple Triggers Combined

```yaml
keda:
  enabled: true
  minReplicas: 1
  maxReplicas: 10
  
  triggers:
    # CPU-based scaling
    - type: cpu
      metricType: Utilization
      metadata:
        value: "70"
    
    # Memory-based scaling
    - type: memory
      metricType: Utilization
      metadata:
        value: "80"
    
 
    
    # Time-based scaling
    - type: cron
      metadata:
        timezone: "Asia/Kolkata"
        start: "30 8 * * *"
        end: "0 22 * * *"
        desiredReplicas: "3"
```

#### Advanced HPA Behavior Configuration

The `advanced` section is passed directly to the KEDA ScaledObject, allowing you to configure any advanced options supported by KEDA without template restrictions. Common options include:

- `horizontalPodAutoscalerConfig`: HPA behavior and scaling policies
- `restoreToOriginalReplicaCount`: Restore replicas when ScaledObject is deleted
- `fallback`: Fallback configuration for metric failures

Example with advanced scaling behavior:

```yaml
keda:
  enabled: true
  minReplicas: 1
  maxReplicas: 10
  
  triggers:
    - type: cpu
      metricType: Utilization
      metadata:
        value: "70"
  
  # Advanced HPA configuration - passed directly to ScaledObject
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          policies:
          - periodSeconds: 60
            type: Pods
            value: 1
          - periodSeconds: 60
            type: Percent
            value: 25
          selectPolicy: Max
          stabilizationWindowSeconds: 300
        scaleUp:
          policies:
          - periodSeconds: 15
            type: Pods
            value: 2
          - periodSeconds: 15
            type: Percent
            value: 100
          selectPolicy: Max
          stabilizationWindowSeconds: 0
    restoreToOriginalReplicaCount: false
    fallback:
      failureThreshold: 3
      replicas: 1
```

Refer to the [KEDA ScaledObject Advanced Configuration](https://keda.sh/docs/concepts/scaling-deployments/#advanced-settings) documentation for all available advanced options.

#### Complete KEDA Configuration Example

```yaml
keda:
  enabled: true
  
  # Replica configuration
  minReplicas: 1
  maxReplicas: 10
  
  # Triggers - supports any KEDA trigger type
  triggers:
    # CPU-based scaling trigger
    - type: cpu
      metricType: Utilization
      metadata:
        value: "70"  # Scale when CPU usage exceeds 70%
    
    # Memory-based scaling trigger
    - type: memory
      metricType: Utilization
      metadata:
        value: "80"  # Scale when memory usage exceeds 80%
    
    # SQS queue depth-based scaling trigger
    - type: aws-sqs-queue
      metadata:
        awsRegion: "ap-south-1"
        identityOwner: "operator"
        queueURL: "https://sqs.ap-south-1.amazonaws.com/533266975263/my-queue-name"
        queueLength: "5"  # Scale when queue has 5+ messages per pod
        scaleOnInFlight: "true"   # Include in-flight messages (default: true)
        scaleOnDelayed: "false"   # Include delayed messages (default: false)
    
    # Time-based scaling (Cron trigger)
    - type: cron
      metadata:
        timezone: "Asia/Kolkata"  # Timezone for cron expressions
        start: "30 8 * * *"   # Start time: 8:30 AM every day
        end: "0 22 * * *"     # End time: 10:00 PM every day
        desiredReplicas: "3"  # Minimum replicas during active window
  
  # Advanced HPA configuration - any KEDA advanced options can be configured here
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          policies:
          - periodSeconds: 60
            type: Pods
            value: 1
          - periodSeconds: 60
            type: Percent
            value: 25
          selectPolicy: Max
          stabilizationWindowSeconds: 300
        scaleUp:
          policies:
          - periodSeconds: 15
            type: Pods
            value: 2
          - periodSeconds: 15
            type: Percent
            value: 100
          selectPolicy: Max
          stabilizationWindowSeconds: 0
    restoreToOriginalReplicaCount: false
    fallback:
      failureThreshold: 3
      replicas: 1
```

#### KEDA Parameters Reference

| Parameter | Description | Default | Required |
|-----------|-------------|---------|----------|
| `keda.enabled` | Enable KEDA autoscaling | `false` | No |
| `keda.minReplicas` | Minimum number of replicas | - | Yes (when enabled) |
| `keda.maxReplicas` | Maximum number of replicas | - | Yes (when enabled) |
| `keda.triggers` | Array of KEDA trigger configurations | `[]` | No |
| `keda.advanced` | Advanced HPA configuration (passed directly to ScaledObject) | `{}` | No |

**Required Values:**
When `keda.enabled` is `true`, you must explicitly set `minReplicas` and `maxReplicas` in your values file. These values are not optional and have no template defaults.

**Trigger Configuration:**
Each trigger in the `triggers` array follows the KEDA ScaledObject trigger specification. Refer to the [KEDA Scalers Documentation](https://keda.sh/docs/scalers/) for trigger-specific parameters.

**Advanced Configuration:**
The `advanced` section accepts any configuration supported by KEDA ScaledObject's advanced settings. Common options include:
- `horizontalPodAutoscalerConfig`: HPA behavior and scaling policies
- `restoreToOriginalReplicaCount`: Boolean to restore replicas on deletion
- `fallback`: Fallback configuration for metric failures

Refer to the [KEDA ScaledObject Advanced Configuration](https://keda.sh/docs/concepts/scaling-deployments/#advanced-settings) documentation for complete details.

#### KEDA vs HPA

- **HPA**: Traditional resource-based scaling (CPU, memory, custom metrics)
- **KEDA**: Event-driven scaling with support for:
  - External metrics (SQS, Kafka, Redis, etc.)
  - Time-based scaling (cron schedules)
  - Advanced scaling behaviors
  - Multiple concurrent triggers
  - Any trigger type supported by KEDA

When both HPA and KEDA are enabled, KEDA takes precedence for autoscaling decisions.

### Ingress Configuration
### Prometheus ServiceMonitor

Enable the optional `ServiceMonitor` resource to integrate with Prometheus operators such as kube-prometheus-stack:

```yaml
serviceMonitor:
  enabled: true
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
  endpoints:
    - port: http
      interval: 30s
      path: /metrics
      scheme: http
      honorLabels: false
      metricRelabelings:
        - targetLabel: cluster
          replacement: in-dev-eks
```

By default, the monitor selects the Helm-managed Service labels and the namespace where the chart is deployed. Override `serviceMonitor.namespaceSelector` or `serviceMonitor.selector` for advanced scraping scenarios.


| Parameter | Description | Default |
|-----------|-------------|---------|
| `ingress.enabled` | Enable ingress | `true` |
| `ingress.ingressClassName` | Ingress class name | `"alb"` |
| `ingress.healthcheckIntervalSeconds` | Health check frequency | `"30"` |
| `ingress.healthcheckPath` | Health check endpoint | `"/"` |
| `ingress.healthcheckTimeoutSeconds` | Health check timeout | `"5"` |
| `ingress.healthyThresholdCount` | Success count to mark healthy | `"2"` |
| `ingress.unhealthyThresholdCount` | Failure count to mark unhealthy | `"3"` |
| `ingress.listenPorts` | ALB listening ports | `[{"HTTP": 80}]` |
| `ingress.scheme` | `internet-facing` or `internal` | `"internal"` |
| `ingress.targetType` | `ip` or `instance` | `"ip"` |
| `ingress.additionalAnnotations` | Custom ALB annotations | `{}` |

### Monitoring

| Parameter | Description | Default |
|-----------|-------------|---------|
| `serviceMonitor.enabled` | Create a Prometheus `ServiceMonitor` | `false` |
| `serviceMonitor.namespace` | Namespace to deploy the `ServiceMonitor` (defaults to release namespace) | `""` |
| `serviceMonitor.labels` | Extra labels added to the resource | `{}` |
| `serviceMonitor.annotations` | Extra annotations added to the resource | `{}` |
| `serviceMonitor.endpoints` | List of scrape endpoint definitions | `[{ port: http, interval: 30s, path: /metrics, scheme: http, honorLabels: false, metricRelabelings: [] }]` |

## Deployment Examples

### Deploy to Stage

```bash
helm upgrade --install voicex-worker base-helm-charts/python-service \
  --values values-stage.yaml \
  --set application.image.registry=123456789.dkr.ecr.ap-south-1.amazonaws.com \
  --set application.image.tag=stage-abc123 \
  --set global.aws.accountId=123456789 \
  --namespace voicex
```

### Ingress Configuration Examples

#### Basic ALB Setup
```yaml
ingress:
  enabled: true
  ingressClassName: "alb"
  scheme: "internet-facing"
  listen-ports: '[{"HTTP": 80}, {"HTTPS": 443}]'
  hosts:
    - host: "api.example.com"
      paths:
        - path: /
          pathType: Prefix
```

#### Production ALB with Custom Annotations
```yaml
ingress:
  enabled: true
  ingressClassName: "alb"
  scheme: "internet-facing"
  listenPorts: '[{"HTTP": 80}, {"HTTPS": 443}]'
  healthcheckPath: "/health"
  additionalAnnotations:
    alb.ingress.kubernetes.io/group.order: "1"
    alb.ingress.kubernetes.io/certificate-arn: "arn:aws:acm:us-west-2:123456789012:certificate/abcd1234"
    alb.ingress.kubernetes.io/ssl-policy: "ELBSecurityPolicy-TLS-1-2-2017-01"
  hosts:
    - host: "api.production.com"
      paths:
        - path: /
          pathType: Prefix
```

#### Internal ALB for Microservices
```yaml
ingress:
  enabled: true
  ingressClassName: "alb"
  scheme: "internal"
  listenPorts: '[{"HTTP": 80}]'
  healthcheckPath: "/health"
  additionalAnnotations:
    alb.ingress.kubernetes.io/group.order: "5"
  hosts:
    - host: "internal-api.example.com"
      paths:
        - path: /
          pathType: Prefix
```

### Deploy to Production

```bash
helm upgrade --install voicex-worker base-helm-charts/python-service \
  --values values-prod.yaml \
  --set application.image.registry=123456789.dkr.ecr.ap-south-1.amazonaws.com \
  --set application.image.tag=v20241201-abc123 \
  --set global.aws.accountId=123456789 \
  --namespace voicex
```

## Ingress Configuration

The chart supports ingress configuration for exposing your Python service externally.

### Basic Ingress Setup

```yaml
# Enable ingress
ingress:
  enabled: true
  ingressClassName: "nginx"
  
  # Host configuration
  hosts:
    - host: "api.example.com"
      paths:
        - path: /
          pathType: Prefix
```

### TLS Configuration

```yaml
ingress:
  enabled: true
  ingressClassName: "nginx"
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
  
  hosts:
    - host: "api.example.com"
      paths:
        - path: /
          pathType: Prefix
  
  tls:
    - secretName: "python-service-tls"
      hosts:
        - "api.example.com"
```

### AWS ALB Ingress Controller

The chart provides a simplified ALB configuration with fixed annotations and customizable options:

```yaml
ingress:
  enabled: true
  ingressClassName: "alb"
  
  # Fixed ALB configuration (automatically applied)
  healthcheckIntervalSeconds: "30"
  healthcheckPath: "/"
  healthcheckTimeoutSeconds: "5"
  healthyThresholdCount: "2"
  listenPorts: '[{"HTTP": 80}, {"HTTPS": 443}]'
  scheme: "internet-facing"
  targetType: "ip"
  unhealthyThresholdCount: "3"
  
  # Additional customizable annotations
  additionalAnnotations:
    alb.ingress.kubernetes.io/group.order: "2"
    alb.ingress.kubernetes.io/certificate-arn: "arn:aws:acm:region:account:certificate/cert-id"
    alb.ingress.kubernetes.io/ssl-policy: "ELBSecurityPolicy-TLS-1-2-2017-01"
  
  hosts:
    - host: "api.example.com"
      paths:
        - path: /
          pathType: Prefix
```

#### ALB Configuration Reference

| Parameter | Description | Default | Type |
|-----------|-------------|---------|------|
| `healthcheckIntervalSeconds` | Health check frequency | `"30"` | Fixed |
| `healthcheckPath` | Health check endpoint | `"/"` | Fixed |
| `healthcheckTimeoutSeconds` | Health check timeout | `"5"` | Fixed |
| `healthyThresholdCount` | Success count to mark healthy | `"2"` | Fixed |
| `unhealthyThresholdCount` | Failure count to mark unhealthy | `"3"` | Fixed |
| `listenPorts` | ALB listening ports | `[{"HTTP": 80}]` | Fixed |
| `scheme` | `internet-facing` or `internal` | `"internal"` | Fixed |
| `targetType` | `ip` (pod IPs) or `instance` (node IPs) | `"ip"` | Fixed |
| `additionalAnnotations` | Custom ALB annotations | `{}` | Customizable |

#### Automatic Annotations

The following annotations are automatically applied based on your configuration:

- `kubernetes.io/ingress.class: "alb"`
- `alb.ingress.kubernetes.io/group.name: "{environment}-cluster"`
- `alb.ingress.kubernetes.io/load-balancer-name: "{environment}-cluster"`
- All health check and ALB configuration parameters

### Service Type Considerations

When using ingress, consider changing the service type:

```yaml
service:
  type: ClusterIP  # Use ClusterIP instead of LoadBalancer when using ingress
  port: 80
  targetPort: 8000
```

### Ingress Configuration Approach

The chart uses a simplified approach for ingress configuration:

#### Fixed Configuration
Common ALB settings are configured as direct values:
```yaml
ingress:
  healthcheckIntervalSeconds: "30"
  healthcheckPath: "/"
  scheme: "internet-facing"
  targetType: "ip"
```

#### Customizable Annotations
Additional annotations can be added via `additionalAnnotations`:
```yaml
ingress:
  additionalAnnotations:
    alb.ingress.kubernetes.io/group.order: "2"
    alb.ingress.kubernetes.io/certificate-arn: "arn:aws:acm:..."
    alb.ingress.kubernetes.io/ssl-policy: "ELBSecurityPolicy-TLS-1-2-2017-01"
```

#### Environment-Based Naming
The chart automatically uses environment-based naming:
- Group name: `{environment}-cluster`
- Load balancer name: `{environment}-cluster`
- Environment is taken from `global.environment`

## Development

### Testing Charts Locally

```bash
# Validate chart
helm lint ./python-service

# Render templates
helm template voicex-worker ./python-service \
  --values values-stage.yaml

# Dry run
helm install voicex-worker ./python-service \
  --values values-stage.yaml \
  --dry-run --debug
```

### Chart Updates

When updating the chart:

1. Update `Chart.yaml` version
2. Update `appVersion` to match application version
3. Test with different value files
4. Validate with `helm lint`

## Migration from Direct YAML

To migrate from direct Kubernetes YAML to this Helm chart:

1. **Identify Current Configuration**: Extract current deployment settings
2. **Map to Values**: Map current settings to chart values
3. **Test**: Deploy to staging environment first
4. **Validate**: Ensure all functionality works
5. **Deploy**: Roll out to production

## Troubleshooting

### Common Issues

1. **Image Pull Errors**: Ensure registry and tag are correct
2. **Resource Limits**: Check if cluster has sufficient resources
3. **Health Check Failures**: Verify health check endpoints
4. **Config Issues**: Validate ConfigMap data

### Debug Commands

```bash
# Check deployment status
kubectl get deployment voicex-worker -n voicex

# Check pod logs
kubectl logs -f deployment/voicex-worker -n voicex

# Describe resources
kubectl describe deployment voicex-worker -n voicex

# Check HPA status
kubectl get hpa -n voicex
```

## Contributing

1. Make changes to chart templates
2. Update version in `Chart.yaml`
3. Test with `helm lint` and `helm template`
4. Submit pull request with changes
5. Chart will be automatically packaged on merge

## Repository Information

This chart is part of the [base-helm-charts](https://github.com/your-org/base-helm-charts) repository, which contains reusable Helm charts for common application patterns.

## License

This chart is licensed under the Apache 2.0 license.
