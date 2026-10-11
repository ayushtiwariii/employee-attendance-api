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

The included unit tests cover deterministic time calculations. Endpoint integration tests and performance/explain verification should be run against a dedicated MongoDB test database. Do not treat helper tests alone as proof that all hidden-dataset behavior passes.

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

The service and unit helper tests can be checked locally without MongoDB, but API/database integration, concurrent request tests, explain-plan requirements on 100,000 records, and the full hidden contract have not been verified in this environment because PyMongo/MongoDB were unavailable. Confirm those before submission. The grader's exact schemas in `openapi.yaml` remain authoritative.
