# QueryDoctor

**AI‑powered SQL query performance advisor**

## Problem Statement
Database performance issues often stem from poorly written SQL queries. Identifying slow queries, understanding why they are inefficient, and receiving actionable recommendations typically requires deep expertise and manual analysis.

## Objectives
- Collect slow‑query logs from a PostgreSQL instance.
- Run `EXPLAIN ANALYZE` on captured queries to obtain execution plans.
- Extract meaningful features from the plans.
- Train a machine‑learning model (Random Forest) to predict performance‑improving suggestions.
- Expose a clean FastAPI backend and a React dashboard for users to submit queries and view recommendations.

## Architecture Overview (Phase 1)
```
queryDoctor/
├─ backend/   (FastAPI, ML, DB helpers)
└─ frontend/  (React + Vite UI)
```
*Backend* handles configuration, environment loading, and placeholder routes.
*Frontend* provides placeholder components for the future dashboard.

## Technology Stack
- **Backend**: Python 3.12, FastAPI, Uvicorn, psycopg‑binary, scikit‑learn, pandas, numpy, python‑dotenv
- **Frontend**: React 18, Vite, JavaScript (ES2022)
- **Database**: PostgreSQL (target system) and a sample e‑commerce DB for testing
- **ML**: scikit‑learn (Random Forest)

## Prerequisites (Windows)
- Python 3.12 installed and added to `PATH`
- Node.js 20.x (includes npm) installed
- PostgreSQL client tools (e.g., `psql`) for local testing
- Git for version control

## Setup Instructions
1. **Clone the repo**
   ```powershell
   git clone <repo-url> queryDoctor
   cd queryDoctor
   ```
2. **Create a virtual environment**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
3. **Install backend dependencies**
   ```powershell
   pip install -r backend/requirements.txt
   ```
4. **Install frontend dependencies**
   ```powershell
   cd frontend
   npm install
   ```
5. **Configure environment variables**
   - Copy `backend/.env.example` to `backend/.env` and adjust values as needed.
   - Do **not** commit the generated `.env` file.

## Running the Project (Phase 1)
- **Backend** (development server)
  ```powershell
  cd backend
  uvicorn app.main:app --host $env:APP_HOST --port $env:APP_PORT --reload
  ```
- **Frontend** (development server)
  ```powershell
  cd frontend
  npm run dev
  ```
- Open the frontend URL (usually `http://localhost:5173`) to see placeholder UI.

## What Is Implemented
- Folder structure and placeholder files
- Backend requirements and environment configuration
- Minimal `.gitignore`
- Documentation skeletons (README, report, DFD, ER diagram)
- Basic React+Vite scaffolding (package.json, vite.config.js)

## What Is Not Yet Implemented
- Actual log collection, `EXPLAIN ANALYZE` execution
- Feature extraction and ML model training/prediction
- Database schema creation and migrations
- Real API endpoints and business logic
- Dashboard UI components

## Next Steps (Phase 2+)
- Implement `/analyze-queries` and `/suggestions` routes.
- Build the ML pipeline and store model artifacts.
- Create the PostgreSQL schema (queries, features, suggestions).
- Develop the interactive React dashboard.
- Add security controls around SQL execution.

### Database Setup

Run the PostgreSQL schema for QueryDoctor:

```bash
psql -U <your_user> -d <your_database> -f backend/app/db/schema.sql
```

*Ensure the `pgcrypto` extension is enabled (the schema will create it if missing).*

---
*Prepared for Phase 1 setup – ready for iterative development.*\n\nAI‑powered SQL query performance advisor.
