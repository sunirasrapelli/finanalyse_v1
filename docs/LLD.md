# Low-Level Design (LLD)

**Team:** _[team name]_  
**Related PRD:** [PRD.md](./PRD.md)  
**Last updated:** _[date]_

---

## 1. Context

_How this system sits next to existing services (one paragraph + optional diagram below)._

```text
[ User / client ]  --->  [ Your service ]  --->  [ External APIs / DB / queue ]
```

---

## 2. Architecture

### 2.1 Components

| Component | Responsibility | Tech / location in repo |
|-----------|----------------|-------------------------|
| _e.g. API_ | | `src/...` |
| _e.g. worker_ | | |

### 2.2 Boundaries

- **Owns:** _
- **Calls / reads:** _
- **Does not own:** _

---

## 3. Interfaces

### 3.1 APIs (if applicable)

| Method | Path / event | Request | Response | Errors |
|--------|----------------|---------|----------|--------|
| | | | | |

### 3.2 Events / queues (if applicable)

| Producer | Consumer | Payload summary |
|----------|----------|-----------------|
| | | |

---

## 4. Data

### 4.1 Models / schema

_Key entities or message shapes (tables, JSON shapes, or “stateless”)._

### 4.2 Storage

| Data | Store | Notes |
|------|-------|--------|
| | | |

---

## 5. Configuration & secrets

- **Env vars / config files:** _
- **Secrets (never commit):** _where they are injected (K8s secret, AppConfig, etc.)_

---

## 6. Deployment & operations

- **How it runs:** _e.g. container entrypoint, `helm/values.yaml` highlights_
- **Health:** _liveness / readiness paths_
- **Scaling:** _single replica vs HPA — match what you configured_

---

## 7. Failure modes & mitigations

| Failure | Impact | Mitigation |
|---------|--------|------------|
| | | |

---

## 8. Trade-offs & deferred work

_What you simplified for the hackathon and what you would do next._

---

## How to use this template

You may **skip any section** that does not apply. Where you skip, add a **brief reason** (for example: `N/A — single-process demo, no queues`) so reviewers know the omission was deliberate.

_Keep diagrams ASCII or link to an image in the repo; avoid huge prose._
