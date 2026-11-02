# Report

## Abstract
QueryDoctor aims to automate the identification and remediation of inefficient SQL queries using machine‑learning techniques. By collecting slow‑query logs, analyzing execution plans, and providing actionable suggestions, the system reduces the manual effort required for performance tuning.

## Problem Statement
Performance bottlenecks in relational databases are frequently caused by sub‑optimal query design. Existing approaches rely on DBA expertise, manual EXPLAIN analysis, and ad‑hoc tuning, which are time‑consuming and error‑prone.

## Objectives
- Automate slow‑query log ingestion from PostgreSQL.
- Execute `EXPLAIN ANALYZE` on captured queries in a safe, sandboxed environment.
- Extract quantitative features from query plans.
- Train a Random Forest model to predict performance‑improving recommendations.
- Expose a RESTful FastAPI service and a React dashboard for users to submit queries and view suggestions.

## Scope
Phase 1 focuses on project scaffolding, configuration, and documentation. No functional code for log collection, plan execution, or ML is implemented yet. Subsequent phases will add these capabilities.

## Database Design
The PostgreSQL schema for QueryDoctor is defined in `backend/app/db/schema.sql`. It includes the core tables:

- **analyzed_queries** – stores captured queries and execution metadata.
- **query_features** – numeric features extracted from each query's execution plan.
- **analysis_results** – stores EXPLAIN ANALYZE JSON plans, model version, and status.
- **recommendations** – model‑generated suggestions linked to a specific analysis result.

Refer to the ER diagram in `docs/er-diagram.md` for visual relationships.

## Proposed Methodology
1. **Data Collection** – Use PostgreSQL `pg_stat_statements` or log files to gather slow queries.
2. **Plan Execution** – Run queries with `EXPLAIN ANALYZE` against a controlled copy of the database.
3. **Feature Extraction** – Parse the JSON plan output to derive metrics (e.g., cost, rows, width, index usage).
4. **Model Training** – Train a Random Forest classifier on labeled data (good vs. bad plans).
5. **Recommendation Engine** – Map model predictions to specific SQL rewrite suggestions.
6. **API & UI** – Provide endpoints for analysis and a web UI for visualizing results.

## Technology Stack
- **Backend**: Python 3.12, FastAPI, Uvicorn, psycopg‑binary, scikit‑learn, pandas, numpy, python‑dotenv
- **Frontend**: React 18, Vite, JavaScript (ES2022)
- **Database**: PostgreSQL (target) and a sample e‑commerce DB for testing
- **ML**: scikit‑learn (Random Forest)

## Expected Outcomes
- Reduced time to identify slow queries.
- Automated generation of concrete, testable SQL recommendations.
- A reusable platform that can be extended to other RDBMS.

## Limitations
- Initial prototype will rely on synthetic data and a limited set of query patterns.
- Security considerations around executing arbitrary queries are deferred to later phases.
- Model performance depends on the quality and diversity of training data.

---
*Prepared as part of Phase 1 documentation.*
