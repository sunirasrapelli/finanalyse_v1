# hack-apr-26-template-repo

Template for **Hack Apr 26** team repos. Full participant steps live in **[GITHUB.md](./GITHUB.md)**; cloud resource details (AWS + Gemini) are in **[CLOUD.md](./CLOUD.md)**.

## Quick start

1. **Register your repo** on the organizer sheet — see [GITHUB.md](./GITHUB.md).
2. **Pick your service folder(s).** The template ships with three examples:

   | Folder | Stack | Keep or delete |
   |--------|-------|----------------|
   | `service-one/` | Python (FastAPI / Poetry) | Delete if not needed |
   | `service-two/` | Next.js | Delete if not needed |
   | `service-three/` | Java Spring Boot (Maven) | Delete if not needed |

   Delete the ones you don't need. Rename the rest (folder name + `helmReleaseName` in `config/deploy.yaml`). Add more `service-*/` folders as needed.

3. **Edit `config/deploy.yaml`** in each service you keep — set `helmReleaseName`, `namespace`, and your stack's `docker.buildArgs`.
4. **Edit `config/secrets.json`** — map env var names to GitHub repo secret names, then create the secrets with `gh secret set`.
5. **Push to `stage`** — the pipeline detects changed `service-*` folders and deploys them automatically.

See [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) for detailed config options and troubleshooting.
