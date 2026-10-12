# HROne Employee Attendance & Analytics API

Backend-only FastAPI + PyMongo implementation of the HROne assignment. Application logic stays in `app/main.py`. It provides employee CRUD, attendance punch-in/out and regularization, four analytics endpoints, a MongoDB explain endpoint, and `/health`.

## Requirements

- Python 3.11+
- MongoDB 6.0+ (the trend and leaderboard use `$densify` and `$setWindowFields`)
- PowerShell on Windows

## Windows setup

From the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` only if needed:

```dotenv
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db
```

Process environment variables override `.env`. Start MongoDB using your local service or use a MongoDB Atlas URI in `MONGO_URI`. Never commit `.env` or credentials.

Start the API:

```powershell
uvicorn app.main:app --port 8000
```

Open Swagger at http://127.0.0.1:8000/docs. `GET /health` returns `{"status":"ok"}` only when MongoDB answers a ping; otherwise it returns 503. Required indexes are created idempotently at startup when MongoDB is reachable. If MongoDB was offline at startup, restart the API after it is available so indexes are initialized.

## Seed sample data

The included `sample_seed.py` can load the supplied sample data. Review the script and ensure `MONGO_URI` and `MONGO_DB` point to a disposable development database before running it:

```powershell
python sample_seed.py
```

Do not run seed/reset scripts against a database containing data you need to preserve.

## Tests

```powershell
python -m pytest -q
```

The full suite covers deterministic calculations, strict timestamp validation, legacy-record regularization, concurrent punch-out, no-log department trends, department headcount, leaderboard ties, and an explain-plan check with 100,200 attendance documents. The full suite requires MongoDB 6+; GitHub Actions starts MongoDB 6.0 and runs it on pull requests and pushes to main. For helper-only tests without MongoDB, run `python -m pytest tests/test_helpers.py tests/test_contract_helpers.py -q`.

## Endpoints

- `GET /health`
- `POST /employees`, `GET /employees`
- `POST /attendance/punch-in`, `GET /attendance`, `POST /attendance/punch-out`, `PATCH /attendance/{emp_code}/{date}`
- `GET /analytics/employees/{emp_code}/monthly`
- `GET /analytics/departments/summary`
- `GET /analytics/leaderboard/late`
- `GET /analytics/departments/{department}/trend`
- `GET /admin/explain/{endpoint}`

## Limitations / verification status

The CI integration suite has passed against MongoDB 6.0, including concurrent punch-out and the 100,200-document attendance-list explain plan. This does not guarantee every hidden dataset or endpoint plan; keep the grader's exact schemas and business rules in `openapi.yaml` and `DATA_MODEL.md` authoritative.
