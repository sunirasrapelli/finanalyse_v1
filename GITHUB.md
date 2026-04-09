# Hackathon Participant Guide

## Getting Started

> **Register your repo name (required):** After you create your team repository, add your **exact repo name** to the **Hack Apr 26 repo registration Google Sheet** at:
>
> [Update Repo Name Here](https://docs.google.com/spreadsheets/d/1iUSKACpAtg0Rp_u7uSilyek5q3WhlktxCI-RI6qaWcE/edit?gid=562580937#gid=562580937)
>
> Organizers use that list so **organization-level policies** apply to your repo. **If your repo is not on the sheet, you are likely to hit org-level restrictions** (for example blocked GitHub Actions, failed deploy workflows, or other enforcement).

### 1. Create your team repo

- Template reference: [nurixlabs/hack-apr-26-template-repo](https://github.com/nurixlabs/hack-apr-26-template-repo)
- Open **[Create repository from this template](https://github.com/new?owner=nurixlabs&template_name=hack-apr-26-template-repo&template_owner=nurixlabs)** (owner **nurixlabs** and template are pre-filled)
- Name your repo: `team-[your-team-name]`
- Set visibility: **Internal**
- Click **Create repository**
- Complete **repo registration** in the Google Sheet (see the callout above)

The `stage` branch is already set as the default. **Do not change this.**

### 2. Clone your repo

```bash
git clone https://github.com/nurixlabs/team-[your-team-name].git
cd team-[your-team-name]
```

You are already on `stage`. Start working directly.

---

## Repo Structure

```text
your-repo/
├── docs/
│   ├── PRD.md                        ← required — do not rename or move
│   └── LLD.md                        ← required — do not rename or move
│
├── service-one/                      ← example: Python (delete or rename)
│   ├── helm/                         ← per-service Helm chart + Dockerfiles
│   │   ├── nurix-service/            ← Helm chart for this service
│   │   ├── python-service.Dockerfile
│   │   ├── nextjs-service.Dockerfile
│   │   ├── java-service-maven.Dockerfile
│   │   └── java-service-gradle.Dockerfile
│   ├── config/
│   │   ├── deploy.yaml               ← required — Helm + Docker config
│   │   └── secrets.json              ← optional — maps env vars to GitHub secrets
│   └── src/                          ← your application source code
│
├── service-two/                      ← example: Next.js (delete or rename)
│   └── ...  (same helm/ structure)
│
├── service-three/                    ← example: Java Maven (delete or rename)
│   └── ...  (same helm/ structure)
│
├── .github/
│   └── workflows/
│       └── deploy.yml                ← trigger stub — do not edit
│
└── README.md                         ← short project description for reviewers
```

**Naming rules:**
- Your service folders **must** be named `service-<something>` — the pipeline only triggers for paths matching `service-*/**`.
- Each service folder contains its own `helm/` with the chart and Dockerfiles — do not delete it.
- Delete unused example service folders to keep your repo tidy. Push any change to `stage` after deleting.
- Do not rename or move `docs/`, `PRD.md`, or `LLD.md` — judges find your submission there.

---

## Deadlines

| Artifact | File | Deadline |
|---|---|---|
| PRD | docs/PRD.md | 9 Apr, 5:00 PM IST |
| LLD | docs/LLD.md | 10 Apr, 12:00 AM IST |
| Code | service-*/ | 13 Apr, 12:00 AM IST |

- **Judges review your work in your team repository** on the `stage` branch.
- There is no separate submission portal — push to `stage` and you're done.

---

## How to Submit

### PRD

```bash
git add docs/PRD.md
git commit -m "docs: add PRD"
git push origin stage
```

Due: **9 Apr, 5:00 PM IST**

### LLD

```bash
git add docs/LLD.md
git commit -m "docs: add LLD"
git push origin stage
```

Due: **10 Apr, 12:00 AM IST**

### Code

```bash
git add service-*/
git commit -m "feat: final submission"
git push origin stage
```

Due: **11 Apr, 12:00 AM IST**

---

## CI/CD Pipeline

Every push to `stage` that touches a `service-*` folder automatically builds and deploys that service to EKS. No manual steps required after the one-time setup below.

### How it works

```
push to stage
  └─ .github/workflows/deploy.yml (stub)
        └─ hack-central-apr-26 / deploy.yml
              └─ detect changed service-* folders
              └─ for each changed service (parallel):
                    └─ hack-central-apr-26 / build-deploy.yml
                          ├─ docker build → push to ECR
                          └─ helm upgrade --install → EKS (in-hack-eks-01)
```

The logic lives entirely in [nurixlabs/hack-central-apr-26](https://github.com/nurixlabs/hack-central-apr-26). Your repo only needs the 30-line stub in `.github/workflows/deploy.yml` — **do not edit it**.

### One-time setup per service

**1. Create `service-<name>/config/deploy.yaml`**

```yaml
helmReleaseName: my-service           # unique name for the Helm release
namespace: team-my-team               # your team repo name
helmChart: ./helm/nurix-service       # chart bundled with this service
dockerfilePath: ./helm/python-service.Dockerfile  # pick your stack (see below)

docker:
  buildArgs:
    PORT: "8000"
    POETRY_APP_MODULE: "myapp.main:app"   # Python example

image:
  tag: latest
```

**2. Pick a Dockerfile**

| Your stack | `dockerfilePath` |
|------------|-----------------|
| Python (FastAPI / Flask / Poetry) | `./helm/python-service.Dockerfile` |
| Next.js | `./helm/nextjs-service.Dockerfile` |
| Java Spring Boot (Maven) | `./helm/java-service-maven.Dockerfile` |
| Java worker (Gradle) | `./helm/java-service-gradle.Dockerfile` |
| Custom | `./Dockerfile` (place it in your service folder) |

**3. Add secrets (if needed)**

Create `service-<name>/config/secrets.json`:

```json
{
  "DATABASE_URL": "database_url",
  "JWT_SECRET":   "jwt_secret"
}
```

Keys = environment variable names in the pod.
Values = GitHub repo secret names. Create each secret:

```bash
gh secret set database_url --repo nurixlabs/team-[your-team] --body "mysql://..."
gh secret set jwt_secret   --repo nurixlabs/team-[your-team] --body "supersecret"
```

**Optional secrets** (set at repo level if your stack needs them):

| Secret | When needed |
|--------|-------------|
| `GIT_TOKEN` | Python or Maven Dockerfile — private Git/Maven dependencies |
| `ORG_YARNRC` | Next.js Dockerfile — private `@nurixlabs` npm packages |

**4. Push to `stage`**

```bash
git add service-my-service/
git commit -m "feat: add my-service"
git push origin stage
```

The pipeline picks it up automatically.

### Checking deployment status

**GitHub Actions tab** → latest **Deploy** run → expand the job for your service → click the **Summary** tab for a table with namespace, image URI, and run link.

**kubectl** (after `aws eks update-kubeconfig`):

```bash
kubectl get pods -n <namespace>
kubectl logs -l app.kubernetes.io/instance=<helmReleaseName> -n <namespace> --tail=50
```

### Manual deploy (specific service)

From the **Actions** tab → **Deploy** → **Run workflow** → enter the service folder name (e.g. `service-backend`).

Or via CLI:

```bash
gh workflow run deploy.yml \
  --repo nurixlabs/team-[your-team] \
  --ref stage \
  --field service_path=service-backend
```

### Rollback

```bash
helm rollback <helmReleaseName> -n <namespace>
```

### Example service folders

The template ships three ready-to-use examples. **Delete any you don't need** — the pipeline only deploys folders that have changed, so unused examples sitting unchanged will never trigger a deploy. But removing them keeps your repo clean.

| Folder | Stack | Delete if… |
|--------|-------|------------|
| `service-one/` | Python (FastAPI / Poetry) | You're not building a Python service |
| `service-two/` | Next.js | You're not building a frontend |
| `service-three/` | Java Spring Boot (Maven) | You're not using Java |

```bash
# Example: team only needs Python and Next.js
git rm -r service-three/
git commit -m "chore: remove unused service-three example"
git push origin stage
```

**To use an example:**
1. Rename the folder: `mv service-one service-my-backend`
2. Update `config/deploy.yaml`: set `helmReleaseName` to match your new name and update `namespace`
3. Update `docker.buildArgs` for your entrypoint / port / version
4. Replace `src/` with your application code

---

## Cloud resources

See **[CLOUD.md](./CLOUD.md)** for:
- AWS account access, EKS cluster, ECR registry, RDS, ElastiCache details
- Gemini / Vertex AI access via the **$300 Google Cloud free trial**

---

## Rules

- All work must be on the **`stage`** branch — do not use other long-lived branches for submissions
- Service folders must follow the `service-*` naming convention for the pipeline to detect them
- Follow the structure and deadlines above unless an organizer announces an exception
- Judges review `docs/PRD.md` and `docs/LLD.md` on `stage` — keep those paths and filenames
