# Cloud Resources (hack-apr-26)

This page covers cloud resources available during the hackathon — AWS for infrastructure and deployment, and Google Cloud / Gemini for AI workloads.

---

## AWS

### Access

If you have **registered for the hackathon**, you should receive **PowerUserAccess** in the **hack-apr-26** AWS account (subject to organizer provisioning).

#### Sign in (browser)

1. Open the **Nurix AWS access portal**: [AWS access portal — Accounts](https://nurixlabs.awsapps.com/start/#/?tab=accounts)
2. Sign in with **Google** when prompted.
3. Choose the **hack-apr-26** account and the role you were granted (e.g. PowerUser).

#### CLI and SSO

To use the AWS CLI with SSO (profiles, `aws sso login`, etc.), follow:

- [Developer guide: Using AWS SSO login](https://nurix.atlassian.net/wiki/spaces/DevOps/pages/153747745/Developer+Guide+Using+AWS+SSO+Login)

#### SSM (EC2, databases, bastion-style access)

For connecting to resources over **Systems Manager Session Manager** (for example EC2-backed databases):

- [Developer guide: Connect to EC2 DB via SSM](https://nurix.atlassian.net/wiki/spaces/DevOps/pages/287440910/Developer+Guide+Connect+to+EC2+DB+via+SSM)

### Environment at a glance

| Item | Value |
|------|--------|
| **AWS account** | **hack-apr-26** (`632421564644`) |
| **Primary region** | **ap-south-1** (Asia Pacific — Mumbai) |
| **ECR registry** | `632421564644.dkr.ecr.ap-south-1.amazonaws.com` |
| **EKS cluster** | `in-hack-eks-01` |

Use these when picking the account in the [AWS access portal](https://nurixlabs.awsapps.com/start/#/?tab=accounts) or configuring CLI profiles.

---

### Provisioned resources (platform)

The following exists in **hack-apr-26** for the hack environment. It is managed by **platform IaC** (Terragrunt in `core-infra`); treat it as shared infrastructure unless organizers say otherwise.

#### Network

- **VPC** for the hack footprint (**`172.19.0.0/16`**) with **public**, **internal**, and **private** subnets across **ap-south-1** AZs. Workloads such as EKS nodes and managed data stores use **private** subnets.

#### Amazon EKS (Kubernetes)

- **Cluster name:** **`in-hack-eks-01`**
- **Purpose:** Run services you deploy from your **team repo** via the Helm-based GitHub Actions pipeline.

Configure `kubectl` after SSO login:

```bash
aws eks update-kubeconfig --region ap-south-1 --name in-hack-eks-01 --profile <your-sso-profile>
```

#### Amazon ECR

Each service in your repo gets its own ECR repository, created automatically on the first deploy:

```
632421564644.dkr.ecr.ap-south-1.amazonaws.com/<team-repo-name>/<service-folder>/
```

For example, for a repo called `team-alpha` with a folder `service-backend`:
```
632421564644.dkr.ecr.ap-south-1.amazonaws.com/team-alpha/service-backend
```

#### Data stores

| Service | Identifier / name | Notes |
|--------|-------------------|--------|
| **Amazon RDS** (MySQL **8.0**) | **`in-hack-mysql`** | Single-AZ dev-style instance in **private** subnets. **Credentials and endpoint** via Secrets Manager / organizer instructions. |
| **Amazon ElastiCache** (Valkey) | **`in-hack-cache-01`** | Valkey **8.1**, multi-AZ–capable cache in **private** subnets. |

#### CI/CD (GitHub → AWS)

- **OIDC provider** for GitHub Actions and IAM role **`github-actions-role`** — allows eligible **`nurixlabs/*`** repositories to assume a role for ECR push, EKS deploy, Secrets Manager read, etc.
- Your repo must be **registered** in the org policy sheet so pipelines are not blocked — see [GITHUB.md](./GITHUB.md).

#### Remote state (for awareness)

Platform Terraform state uses a dedicated **S3** bucket and **DynamoDB** table for locks in **ap-south-1** (operators only; you do not need this).

---

### Deploying your service (developer checklist)

The pipeline is fully automated. Do these steps once per service, then **every push to `stage` deploys automatically**.

#### 1. Create your service folder

Copy one of the sample folders from the template and rename it `service-<name>`:

```
service-one/    ← Python FastAPI example
service-two/    ← Next.js example
service-three/  ← Java Spring Boot (Maven) example
```

#### 2. Edit `config/deploy.yaml`

This is the only required config file. Set at minimum:

```yaml
helmReleaseName: <your-service-name>     # unique within the namespace
namespace: <your-team-repo-name>         # e.g. team-alpha
helmChart: ./helm/nurix-service
dockerfilePath: ./helm/python-service.Dockerfile   # pick your stack
docker:
  buildArgs:
    PORT: "8000"
    POETRY_APP_MODULE: "myapp.main:app"  # adjust per stack
```

See [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) for the full list of options.

#### 3. Edit `config/secrets.json` (if needed)

Map environment variable names to GitHub repo secret names:

```json
{
  "DATABASE_URL": "database_url",
  "JWT_SECRET":   "jwt_secret"
}
```

Then create each secret in your repo:

```bash
gh secret set database_url --repo nurixlabs/<team-repo> --body "mysql://..."
gh secret set jwt_secret   --repo nurixlabs/<team-repo> --body "supersecret"
```

#### 4. Push to `stage`

```bash
git add service-backend/
git commit -m "feat: add backend service"
git push origin stage
```

The pipeline detects the changed `service-backend/` folder and:
1. Builds a Docker image (using the Dockerfile you chose)
2. Pushes it to ECR (creates the repository if it doesn't exist)
3. Deploys with `helm upgrade --install` using the per-service `nurix-service` chart
4. Waits for the rollout and posts a summary in the Actions tab

#### 5. Check the deployment

```bash
# Follow the Actions run
gh run watch --repo nurixlabs/<team-repo>

# Or check pods directly
aws eks update-kubeconfig --region ap-south-1 --name in-hack-eks-01
kubectl get pods -n <namespace>
kubectl logs -l app.kubernetes.io/instance=<helmReleaseName> -n <namespace> --tail=50
```

#### Rollback

```bash
helm rollback <helmReleaseName> -n <namespace>
```

---

## Google Cloud — Gemini & Vertex AI

> **For using Vertex AI or Gemini, please create a personal Google Cloud account to avail the $300 free credit that Google provides for new accounts.** This is the quickest way to get API access during the hackathon without any shared quota limitations.

### Getting started

1. Go to [https://cloud.google.com](https://cloud.google.com) and sign up with a **personal Google account** (not your Nurix work account).
2. Activate the **$300 free trial credit** — no charges until you explicitly upgrade.
3. Enable the **Vertex AI API** or the **Generative Language API** from the [Google Cloud Console](https://console.cloud.google.com/apis/library).
4. Create a **service account** or use **API keys** depending on how you access the models.

### Gemini via API key (quickest)

```bash
# Install the Google AI Python SDK
pip install google-generativeai

# Set your API key (from https://aistudio.google.com/app/apikey)
export GOOGLE_API_KEY="your-api-key"
```

```python
import google.generativeai as genai

genai.configure(api_key="your-api-key")
model = genai.GenerativeModel("gemini-2.0-flash")
response = model.generate_content("Hello!")
print(response.text)
```

### Vertex AI (more control, production-grade)

```bash
# Install the Vertex AI SDK
pip install google-cloud-aiplatform

# Authenticate with your personal account
gcloud auth application-default login
```

```python
import vertexai
from vertexai.generative_models import GenerativeModel

vertexai.init(project="your-project-id", location="us-central1")
model = GenerativeModel("gemini-2.0-flash")
response = model.generate_content("Hello!")
print(response.text)
```

### Useful links

| Resource | URL |
|----------|-----|
| Google AI Studio (API keys + playground) | [aistudio.google.com](https://aistudio.google.com) |
| Vertex AI console | [console.cloud.google.com/vertex-ai](https://console.cloud.google.com/vertex-ai) |
| Gemini API docs | [ai.google.dev/docs](https://ai.google.dev/docs) |
| Vertex AI pricing | [cloud.google.com/vertex-ai/pricing](https://cloud.google.com/vertex-ai/pricing) |
| Free trial details | [cloud.google.com/free](https://cloud.google.com/free) |

> Keep your API keys out of source code — use GitHub repo secrets and inject them via `config/secrets.json`. See [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md#managing-secrets-with-secretsjson).

---

_Questions about AWS account access or permissions: ask hackathon organizers / DevOps._
