# service-one — Python FastAPI (Poetry)

> **Example service.** Delete this folder if your team doesn't need a Python service,
> or keep it and replace the source code with your own.

## Source layout

```
service-one/
├── config/
│   ├── deploy.yaml       ← pipeline + Helm config (edit this)
│   └── secrets.json      ← GitHub secret mappings (edit this)
├── src/                  ← your application source (this folder)
│   └── api/
│       ├── __init__.py
│       └── main.py       ← FastAPI entrypoint (must export `app`)
├── pyproject.toml        ← Poetry project file (place at service root)
└── poetry.lock
```

## Minimal `pyproject.toml`

```toml
[tool.poetry]
name = "api"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.12"
fastapi = "^0.111.0"
uvicorn = {extras = ["standard"], version = "^0.30.0"}
```

## Minimal `src/api/main.py`

```python
from fastapi import FastAPI

app = FastAPI(title="service-one")

@app.get("/health")
def health():
    return {"status": "ok"}
```

## Local dev

```bash
poetry install
poetry run uvicorn api.main:app --reload --port 8000
```

## To rename this service

1. Rename the folder: `mv service-one service-my-name`
2. Update `config/deploy.yaml`: set `helmReleaseName` and `namespace`
3. Update `POETRY_APP_MODULE` in `docker.buildArgs` to match your entrypoint
