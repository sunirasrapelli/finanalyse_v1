# Secrets Setup Guide

This document walks through all the one-time secrets and IAM configuration needed before teams can deploy from their repos.

## Repository Layout

| Repo | Role |
|------|------|
| `nurixlabs/hack-central-apr-26` | Owns the central reusable workflow (`build-deploy.yml`). All team repos call into this. |
| `nurixlabs/hack-apr-26-template-repo` | Template teams clone from. Ships `deploy.yml`, Dockerfiles, and Helm chart starters. |
| `nurixlabs/<team-repo>` | One repo per team. Contains their services. Calls the central workflow on push to `stage`. |

---

---

## Prerequisites

- [GitHub CLI (`gh`)](https://cli.github.com/) installed and authenticated: `gh auth login`
- AWS CLI installed and configured with admin credentials
- Access to the `nurixlabs` GitHub org (org admin for org-level secrets)

---

## 1. Create GitHub Org-Level Secrets

These secrets are available to all repos in the `nurixlabs` org and are used by the central workflow.

```bash
# Replace placeholders with actual values before running

# Your AWS account ID (12-digit number)
gh secret set AWS_ACCOUNT_ID \
  --org nurixlabs \
  --visibility all \
  --body "123456789012"

# AWS region where EKS and ECR live
gh secret set AWS_REGION \
  --org nurixlabs \
  --visibility all \
  --body "ap-south-1"

# Name of your EKS cluster
gh secret set EKS_CLUSTER_NAME \
  --org nurixlabs \
  --visibility all \
  --body "your-eks-cluster-name"

# ECR registry URL (constructed from account ID and region)
gh secret set ECR_REGISTRY \
  --org nurixlabs \
  --visibility all \
  --body "123456789012.dkr.ecr.ap-south-1.amazonaws.com"
```

> **Note:** If you set `--visibility all`, the secrets are accessible to all org repos. For tighter control, use `--visibility selected` and specify repos with `--repos`.

---

## 2. Create the IAM Role for GitHub Actions OIDC

The deployment workflow authenticates to AWS via OIDC (no long-lived credentials stored in GitHub).

### 2a. Add GitHub as an OIDC Identity Provider in AWS (one-time)

Run in AWS CLI or do this in the IAM console:

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

> Skip this step if the provider already exists. Check with:
> `aws iam list-open-id-connect-providers`

### 2b. Create the IAM Role

> **Note:** If the `github-actions-role` IAM role already exists in the `hack-apr-26` account (created by platform IaC), skip role creation and go directly to step 2d to verify the `aws-auth` binding.

The trust policy must allow **all nurixlabs repos** to assume the role (since `build-deploy.yml` runs in the context of each team repo, not the central repo).

Save the following as `trust-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:nurixlabs/*:ref:refs/heads/stage"
        },
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        }
      }
    }
  ]
}
```

> The `StringLike` condition allows any repo in `nurixlabs` org to assume this role when pushing to the `stage` branch. Narrow the condition (e.g. `repo:nurixlabs/specific-repo:*`) for tighter security.

Create the role:

```bash
aws iam create-role \
  --role-name github-actions-role \
  --assume-role-policy-document file://trust-policy.json \
  --description "Assumed by GitHub Actions OIDC for hackathon deployments"
```

### 2c. Attach Required Permissions Policy

Save the following as `permissions-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ECRAuth",
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ECRPushPull",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:GetRepositoryPolicy",
        "ecr:DescribeRepositories",
        "ecr:ListImages",
        "ecr:DescribeImages",
        "ecr:BatchGetImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage",
        "ecr:CreateRepository",
        "ecr:TagResource"
      ],
      "Resource": "arn:aws:ecr:ap-south-1:123456789012:repository/*"
    },
    {
      "Sid": "EKSDescribe",
      "Effect": "Allow",
      "Action": [
        "eks:DescribeCluster"
      ],
      "Resource": "arn:aws:eks:ap-south-1:123456789012:cluster/*"
    }
  ]
}
```

```bash
# Create the inline policy and attach it
aws iam put-role-policy \
  --role-name github-actions-role \
  --policy-name github-actions-role-policy \
  --policy-document file://permissions-policy.json
```

### 2d. Grant the Role Access to the EKS Cluster

The IAM role also needs a Kubernetes RBAC binding inside the cluster. Add it to the `aws-auth` ConfigMap:

```bash
# Get current aws-auth configmap
kubectl get configmap aws-auth -n kube-system -o yaml > aws-auth-patch.yaml
```

Add the following under `mapRoles` in `aws-auth-patch.yaml`:

```yaml
- rolearn: arn:aws:iam::632421564644:role/github-actions-role
  username: github-actions-role
  groups:
    - system:masters
```

> For production, use a more restrictive group than `system:masters` (e.g., a custom ClusterRole scoped to specific namespaces).

Apply the patch:

```bash
kubectl apply -f aws-auth-patch.yaml
```

---

## 3. Team Repo Secrets Setup

Each team repo needs secrets for the values referenced in their `service-*/config/secrets.json`.

The `secrets.json` maps environment variable names to GitHub secret names. For example:

```json
{
  "DATABASE_URL": "database_url",
  "API_KEY": "api_key"
}
```

This means the repo must have secrets named `database_url` and `api_key`.

Create them like this:

```bash
# Replace [TEAM_REPO] with the actual repo name, e.g. team-alpha-repo

gh secret set database_url \
  --repo nurixlabs/[TEAM_REPO] \
  --body "postgres://user:password@host:5432/dbname"

gh secret set api_key \
  --repo nurixlabs/[TEAM_REPO] \
  --body "your-actual-api-key-value"

gh secret set jwt_secret \
  --repo nurixlabs/[TEAM_REPO] \
  --body "your-jwt-secret-value"

gh secret set redis_password \
  --repo nurixlabs/[TEAM_REPO] \
  --body "your-redis-password"
```

> Secret names in `secrets.json` values are case-sensitive and must exactly match the GitHub secret names you create.

### Bulk setup using a .env file (optional)

If you have a `.env` file with secret values, you can set them all at once:

```bash
# Load from .env and create GitHub secrets
while IFS='=' read -r name value; do
  [[ "$name" =~ ^#.*$ ]] && continue   # skip comments
  [ -z "$name" ] && continue           # skip empty lines
  gh secret set "$name" \
    --repo nurixlabs/[TEAM_REPO] \
    --body "$value"
done < team-secrets.env
```

---

## 4. Verification Checklist

After setup, verify everything is in place:

```bash
# Check org secrets exist
gh secret list --org nurixlabs

# Check team repo secrets exist
gh secret list --repo nurixlabs/[TEAM_REPO]

# Verify IAM role exists
aws iam get-role --role-name github-actions-hackathon

# Verify OIDC provider exists
aws iam list-open-id-connect-providers

# Verify EKS cluster is accessible
aws eks describe-cluster --name your-eks-cluster-name --region ap-south-1
```

---

## Summary

| Step | What | Who |
|------|------|-----|
| 1 | Create org-level GitHub secrets | Org admin |
| 2a | Register GitHub OIDC provider in AWS | AWS admin |
| 2b | Create `github-actions-hackathon` IAM role | AWS admin |
| 2c | Attach ECR + EKS permissions to the role | AWS admin |
| 2d | Grant role access to EKS via `aws-auth` | AWS/K8s admin |
| 3 | Create per-service secrets in team repo | Team lead |
