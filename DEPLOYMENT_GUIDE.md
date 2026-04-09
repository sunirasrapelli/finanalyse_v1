# Deployment Guide

This guide explains how to build and deploy services in this monorepo to Kubernetes (EKS) using the automated GitHub Actions pipeline.

---

## Table of Contents

1. [How it works](#how-it-works)
2. [Adding a new service](#adding-a-new-service)
3. [Customizing config/deploy.yaml](#customizing-configdeployyaml)
4. [Managing secrets with secrets.json](#managing-secrets-with-secretsjson)
5. [Choosing and customizing your Dockerfile](#choosing-and-customizing-your-dockerfile)
6. [Customizing the Helm chart](#customizing-the-helm-chart)
7. [Triggering a deployment](#triggering-a-deployment)
8. [Checking deployment status](#checking-deployment-status)
9. [Rolling back a deployment](#rolling-back-a-deployment)
10. [Troubleshooting](#troubleshooting)

---

## How it works

```
Push to `stage` branch  (team repo)
       │
       ▼
.github/workflows/deploy.yml          ← lives in YOUR team repo
  └─ detect-changes job
       └─ Diffs HEAD~1..HEAD
       └─ Finds changed service-* folders
       └─ Outputs JSON matrix of services
       │
       ▼
  └─ deploy job (parallel matrix)
       └─ calls ──────────────────────────────────────────────────────────┐
                                                                          ▼
                          nurixlabs/hack-central-apr-26                   │
                          .github/workflows/build-deploy.yml@main  ◄──────┘
                            (central reusable workflow)
                            └─ Reads config/deploy.yaml
                            └─ Reads config/secrets.json
                            └─ Authenticates to AWS via OIDC
                            └─ Builds Docker image (BuildKit)
                            └─ Pushes to ECR
                            └─ Helm upgrade --install
                            └─ Waits for rollout
                            └─ Posts summary
```

### Repository roles

| Repo | What lives here | Who edits it |
|------|-----------------|--------------|
| `nurixlabs/hack-central-apr-26` | `build-deploy.yml` — the engine that does the actual build and deploy | Org admins only |
| `nurixlabs/hack-apr-26-template-repo` | `deploy.yml` (trigger), Dockerfiles, Helm starters | Template maintainers |
| `nurixlabs/<your-team-repo>` | Your services, `config/deploy.yaml`, `config/secrets.json` | Your team |

**Teams never touch `build-deploy.yml`.** Any fix or improvement to the central workflow automatically applies to all team repos on the next push.

---

## Adding a new service

### Option A — Start from an example (recommended)

The template ships three example folders. Pick the one closest to your stack, rename it, and replace the source code:

| Folder | Stack | When to use |
|--------|-------|-------------|
| `service-one/` | Python (FastAPI / Poetry) | REST APIs, ML inference, background tasks |
| `service-two/` | Next.js | Web frontends, full-stack apps |
| `service-three/` | Java Spring Boot (Maven) | Java REST APIs, microservices |

```bash
# Example: rename service-one to service-backend
mv service-one service-backend
```

Then update `service-backend/config/deploy.yaml`:
- `helmReleaseName: service-backend`
- `namespace: <your-team-repo-name>`
- `POETRY_APP_MODULE` (Python) or equivalent `docker.buildArgs`

**Deleting unused examples** — delete any example you don't need:

```bash
git rm -r service-two/ service-three/
git commit -m "chore: remove unused example services"
git push origin stage
```

### Option B — Create from scratch

Create a new folder named `service-<your-name>/`:

```
service-myapp/
├── config/
│   ├── deploy.yaml         ← required
│   └── secrets.json        ← optional
└── src/
    └── ...
```

| File | Required | Purpose |
|------|----------|---------|
| `config/deploy.yaml` | Yes — pipeline fails without it | Helm + image + Dockerfile config |
| `config/secrets.json` | No | Maps env var names to GitHub secret names |

Minimum `config/deploy.yaml`:

```yaml
helmReleaseName: my-service
namespace: team-my-team
helmChart: ./helm/nurix-service
dockerfilePath: ./helm/python-service.Dockerfile  # choose your stack

docker:
  buildArgs:
    PORT: "8000"
    POETRY_APP_MODULE: "myapp.main:app"

image:
  tag: latest
```

Once you push any file inside `service-myapp/` to `stage`, the pipeline deploys it automatically.

---

## Customizing config/deploy.yaml

This file has two roles:

1. **Consumed by the workflow** to know how to build and deploy your service.
2. **Passed directly to Helm** as `-f config/deploy.yaml`, so any extra keys you add become Helm values.

### Required fields (read by the workflow)

```yaml
helmReleaseName: my-service            # Helm release name — unique per namespace
namespace: my-team                     # Kubernetes namespace
helmChart: ./helm/nurix-service        # Path to Helm chart, relative to service folder
dockerfilePath: ./helm/python-service.Dockerfile  # Path to Dockerfile, relative to service folder

image:
  tag: latest                     # Docker image tag
```

### Common optional fields (forwarded to Helm)

```yaml
replicas: 2

resources:
  requests:
    cpu: "250m"
    memory: "256Mi"
  limits:
    cpu: "500m"
    memory: "512Mi"

service:
  type: ClusterIP
  port: 8080

ingress:
  enabled: false

env:
  LOG_LEVEL: info
  APP_ENV: staging
```

### Notes

- `helmReleaseName` must be a valid [Helm release name](https://helm.sh/docs/chart_best_practices/conventions/#chart-names) (lowercase, alphanumeric, hyphens).
- `namespace` is created automatically before deploy if it doesn't exist.
- `image.tag` can be `latest` or a semantic version like `v1.2.3`. All images are also tagged with `:latest` regardless.

---

## Managing secrets with secrets.json

`config/secrets.json` maps environment variable names (injected into the pod) to GitHub repo secret names (where the actual values live).

### Format

```json
{
  "DATABASE_URL": "database_url",
  "API_KEY": "api_key",
  "JWT_SECRET": "jwt_secret"
}
```

- **Key** (`DATABASE_URL`) — the environment variable name inside the container.
- **Value** (`database_url`) — the name of the GitHub repo secret that holds the actual value.

### How to add a new secret

**Step 1.** Add the entry to `secrets.json`:

```json
{
  "NEW_SECRET": "new_secret_github_name"
}
```

**Step 2.** Create the GitHub repo secret with the actual value:

```bash
gh secret set new_secret_github_name \
  --repo nurixlabs/your-team-repo \
  --body "actual-secret-value-here"
```

**Step 3.** In your Helm chart, reference the injected env var:

```yaml
# helm/templates/deployment.yaml
env:
  {{- range $key, $val := .Values.envVars }}
  - name: {{ $key }}
    value: {{ $val | quote }}
  {{- end }}
```

### Notes

- If `secrets.json` is missing, the workflow continues without injecting any secrets (no error).
- Secret names in the JSON values are case-sensitive and must exactly match the GitHub secret names.
- Never put actual secret values in `secrets.json` — only names. The file is safe to commit.

---

## Choosing and customizing your Dockerfile

Ready-made Dockerfiles live in each service's `helm/` folder. Point to the right one in your `config/deploy.yaml` using `dockerfilePath`.

### Available template Dockerfiles

| File | Language / Framework | Notes |
|------|---------------------|-------|
| `helm/python-service.Dockerfile` | Python — Poetry | Multi-stage. Supports private Git deps via `GIT_TOKEN` BuildKit secret. |
| `helm/nextjs-service.Dockerfile` | Next.js (Node 22) | Multi-stage standalone output. Supports private npm via `ORG_YARNRC`. |
| `helm/java-service-maven.Dockerfile` | Java — Maven | Multi-stage. Auto-detects single vs multi-module projects. Supports private Maven repos via `GIT_TOKEN`. |
| `helm/java-service-gradle.Dockerfile` | Java — Gradle | Simple two-stage build. Copies startup scripts from `helm/server/`. |

---

### Python (Poetry) — `helm/python-service.Dockerfile`

```yaml
# config/deploy.yaml
dockerfilePath: ./helm/python-service.Dockerfile

docker:
  buildArgs:
    PYTHON_VERSION: "3.12"
    BUILD_ENV: staging
    PORT: "8000"
    POETRY_APP_MODULE: "myapp.main:app"   # e.g. uvicorn entrypoint
    # POETRY_SCRIPT: "myapp"              # alternative: console_scripts entry
```

- `POETRY_APP_MODULE` → runs `python -m <module>` (e.g. `uvicorn myapp.main:app --host 0.0.0.0 --port $PORT`)
- `POETRY_SCRIPT` → runs a script defined in `[tool.poetry.scripts]`
- For private Git dependencies: create a `GIT_TOKEN` repo secret — it is passed as a BuildKit secret (never baked into the image).

---

### Next.js — `helm/nextjs-service.Dockerfile`

```yaml
# config/deploy.yaml
dockerfilePath: ./helm/nextjs-service.Dockerfile

docker:
  buildArgs:
    BUILD_ENV: staging   # loads .env.staging if present

service:
  port: 3000   # Next.js always runs on 3000
```

- Requires `output: "standalone"` in your `next.config.js` (the Dockerfile copies `/.next/standalone`).
- For private `@nurixlabs` npm packages: create an `ORG_YARNRC` repo secret (GitHub token with `read:packages`). It is passed as `--build-arg ORG_YARNRC` automatically.
- Auto-detects `yarn.lock` / `package-lock.json` / `pnpm-lock.yaml`.

---

### Java Maven — `helm/java-service-maven.Dockerfile`

```yaml
# config/deploy.yaml
dockerfilePath: ./helm/java-service-maven.Dockerfile

docker:
  buildArgs:
    JAVA_VERSION: "21"
    BUILD_ENV: staging
    PORT: "8080"
    MAVEN_PROFILES: ""   # e.g. "prod" to activate a Maven profile
```

- Auto-detects single-module vs multi-module Maven projects from `pom.xml`.
- For private Maven repositories (GitHub Packages): create a `GIT_TOKEN` repo secret.
- Searches for the executable JAR (one with `Main-Class` in `MANIFEST.MF`) across all `target/` directories.

---

### Java Gradle — `helm/java-service-gradle.Dockerfile`

```yaml
# config/deploy.yaml
dockerfilePath: ./helm/java-service-gradle.Dockerfile

docker:
  buildArgs:
    JAVA_VERSION: "17"
    BUILD_PATH: "."          # path inside the container where source is copied
    SERVICE_NAME: "my-svc"
    PORT: "8080"
    JAR_PATH: "build/libs"
    JAR_NAME: "app.jar"
```

> **Note:** The Gradle Dockerfile copies from `helm/server/bin` and `helm/server/config` for startup scripts. Add those directories under your service's `helm/server/` if you use this Dockerfile.

---

### General tips

- Set `service.port` in `config/deploy.yaml` to match the `EXPOSE`d port in the Dockerfile.
- All template Dockerfiles run as a **non-root user** for security.
- Multi-stage builds keep production images lean — only the final stage is pushed to ECR.
- To write your own Dockerfile, place it inside your service folder (e.g. `./Dockerfile`) and set `dockerfilePath: ./Dockerfile`.

---

## Customizing the Helm chart

Your chart lives in `service-*/helm/nurix-service/`. The workflow runs:

```bash
helm upgrade --install <helmReleaseName> ./helm/nurix-service \
  --namespace <namespace> \
  -f config/deploy.yaml \
  --set application.image.registry=<ecr-registry> \
  --set application.image.repository=<ecr-repo-path> \
  --set application.image.tag=<tag> \
  --set-string application.env.<KEY>=<value> ...
```

### values.yaml defaults

```yaml
replicaCount: 1

image:
  repository: ""     # set by workflow
  tag: latest        # set by workflow
  pullPolicy: IfNotPresent

service:
  type: ClusterIP
  port: 8080

resources: {}

envVars: {}          # populated from secrets.json by workflow
```

### deployment.yaml pattern for envVars

```yaml
containers:
  - name: {{ .Chart.Name }}
    image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
    ports:
      - containerPort: {{ .Values.service.port }}
    env:
      {{- range $key, $val := .Values.envVars }}
      - name: {{ $key }}
        value: {{ $val | quote }}
      {{- end }}
    resources:
      {{- toYaml .Values.resources | nindent 12 }}
```

### Adding a ConfigMap

Add a `configmap.yaml` template and reference it in `deployment.yaml` via `envFrom`:

```yaml
# helm/templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "mychart.fullname" . }}-config
data:
  APP_ENV: {{ .Values.env.APP_ENV | default "staging" | quote }}
```

```yaml
# deployment.yaml — inside containers
envFrom:
  - configMapRef:
      name: {{ include "mychart.fullname" . }}-config
```

---

## Triggering a deployment

### Automatic (recommended)

Push any change inside a `service-*/` folder to the `stage` branch:

```bash
git add service-myapp/src/app.py
git commit -m "feat: add new endpoint"
git push origin stage
```

The pipeline detects which service folders changed and deploys only those.

### Manual (via GitHub UI)

1. Go to your repo on GitHub.
2. Click **Actions** → **Deploy Changed Services**.
3. Click **Run workflow**.
4. (Optional) Enter a specific service folder name to force-deploy it.
5. Click **Run workflow**.

### Manual (via CLI)

```bash
# Deploy a specific service manually
gh workflow run deploy.yml \
  --repo nurixlabs/your-team-repo \
  --ref stage \
  --field service_path=service-myapp
```

---

## Checking deployment status

### GitHub Actions tab

1. Go to your repo → **Actions**.
2. Click the latest **Deploy Changed Services** run.
3. Expand the **Deploy service-myapp** job to see logs.
4. Click the **Summary** tab for a deployment summary table.

### kubectl

```bash
# List all pods in your namespace
kubectl get pods -n your-namespace

# Watch rollout status
kubectl rollout status deployment/your-helm-release-name -n your-namespace

# View pod logs
kubectl logs -l app=your-helm-release-name -n your-namespace --tail=100

# Describe a pod for events and errors
kubectl describe pod <pod-name> -n your-namespace
```

### Helm

```bash
# List releases
helm list -n your-namespace

# Show release status
helm status your-helm-release-name -n your-namespace

# View rendered Helm templates (dry run)
helm template your-helm-release-name ./helm -f config/deploy.yaml
```

---

## Rolling back a deployment

### Via Helm (recommended)

```bash
# View release history
helm history your-helm-release-name -n your-namespace

# Roll back to the previous revision
helm rollback your-helm-release-name -n your-namespace

# Roll back to a specific revision number
helm rollback your-helm-release-name 3 -n your-namespace
```

### Via kubectl

```bash
# Roll back the Kubernetes deployment (not Helm-aware)
kubectl rollout undo deployment/your-helm-release-name -n your-namespace

# View rollout history
kubectl rollout history deployment/your-helm-release-name -n your-namespace
```

> Prefer `helm rollback` over `kubectl rollout undo` so Helm's state stays in sync.

---

## Troubleshooting

### Workflow not triggering

**Symptom:** Push to `stage` but no Actions run starts.

**Checks:**
- Confirm you pushed to `stage` (not `main` or another branch).
- Verify the changed files are inside a `service-*/` folder — the `paths` filter in `deploy.yml` only matches those.
- Check the **Actions** tab for any workflow syntax errors (yellow warning icon on the workflow name).

---

### `config/deploy.yaml not found` error

**Symptom:** Workflow fails at the "Read deploy.yaml" step with a `::error::` message.

**Fix:** Every service folder must have `config/deploy.yaml`. Create it using `service-example/config/deploy.yaml` as a template.

---

### `Dockerfile not found` error

**Symptom:** Workflow fails at the "Read deploy.yaml" step checking Dockerfile existence.

**Fix:** Ensure a `Dockerfile` exists at the path specified in `dockerfilePath` (relative to the service folder). Default is `./Dockerfile`.

---

### ECR push fails: `no basic auth credentials`

**Symptom:** `docker push` step fails with authentication error.

**Fix:** The ECR login step runs before the push — check the "Login to Amazon ECR" step logs. Usually caused by the IAM role missing `ecr:GetAuthorizationToken`. See [secrets-setup.md](./secrets-setup.md) for the correct permissions.

---

### EKS `Unauthorized` or `Forbidden`

**Symptom:** `kubectl` commands fail with `Error from server (Forbidden)` or `Unauthorized`.

**Fix:** The IAM role (`github-actions-hackathon`) must be added to the `aws-auth` ConfigMap in the cluster. See [secrets-setup.md § 2d](./secrets-setup.md#2d-grant-the-role-access-to-the-eks-cluster).

---

### Helm deploy fails: `rendered manifests contain a resource that already exists`

**Symptom:** Helm errors about existing resources not owned by the release.

**Fix:**
```bash
# Adopt the existing resource into the Helm release
helm upgrade --install your-release ./helm \
  --namespace your-namespace \
  --force
```

Or delete the conflicting resource first:
```bash
kubectl delete deployment conflicting-name -n your-namespace
```

---

### Pod stuck in `CrashLoopBackOff` or `ImagePullBackOff`

**CrashLoopBackOff — application is crashing:**
```bash
kubectl logs <pod-name> -n your-namespace --previous
kubectl describe pod <pod-name> -n your-namespace
```

Look for missing environment variables, wrong startup command, or application errors.

**ImagePullBackOff — image cannot be pulled:**
```bash
kubectl describe pod <pod-name> -n your-namespace | grep -A5 "Events:"
```

Common causes:
- Wrong image tag (check `image.tag` in `deploy.yaml`).
- ECR repo doesn't exist or push failed — re-run the workflow.
- The node's IAM role lacks ECR pull permissions.

---

### Rollout times out after 5 minutes

**Symptom:** `kubectl rollout status` step times out.

**Checks:**
```bash
kubectl get pods -n your-namespace
kubectl describe deployment your-helm-release-name -n your-namespace
```

Common causes:
- Insufficient CPU/memory — increase `resources.requests` and/or cluster node capacity.
- Failing liveness/readiness probes — check probe paths and ports in your Helm chart.
- The new pod is crashing — check `CrashLoopBackOff` section above.

---

### Secret not injected into pod

**Symptom:** App crashes with missing environment variable that should come from `secrets.json`.

**Fix:**
1. Confirm the GitHub repo secret exists with the exact name from `secrets.json`:
   ```bash
   gh secret list --repo nurixlabs/your-team-repo
   ```
2. Confirm the secret name in `secrets.json` value matches exactly (case-sensitive).
3. Confirm your Helm `deployment.yaml` iterates `envVars` — see the [Helm chart section](#customizing-the-helm-chart).

---

### `helm upgrade` fails with `values.yaml` parse error

**Symptom:** Helm errors on `-f config/deploy.yaml` with YAML parsing issues.

**Fix:** Validate your YAML locally:
```bash
python3 -c "import yaml; yaml.safe_load(open('service-myapp/config/deploy.yaml'))"
```

Or with `yq`:
```bash
yq eval . service-myapp/config/deploy.yaml
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Trigger deploy manually | `gh workflow run deploy.yml --ref stage --field service_path=service-xyz` |
| Check pod status | `kubectl get pods -n <namespace>` |
| View pod logs | `kubectl logs -l app=<release> -n <namespace> --tail=100` |
| Helm rollback | `helm rollback <release> -n <namespace>` |
| List Helm releases | `helm list -n <namespace>` |
| View Helm history | `helm history <release> -n <namespace>` |
| Dry-run Helm render | `helm template <release> ./helm -f config/deploy.yaml` |
| Update kubeconfig | `aws eks update-kubeconfig --name <cluster> --region ap-south-1` |
