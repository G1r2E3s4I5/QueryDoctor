# Data Flow Diagrams (DFD)

## Level 0 (Context Diagram)
- **External Entity:** Application User (via web UI)
- **Process:** QueryDoctor System
- **Data Store:** Project Database (PostgreSQL)
- **Data Flow:**
  1. User submits a SQL query through the React UI.
  2. The query is sent to the FastAPI backend.
  3. Backend returns performance analysis and suggestions.

## Level 1 (High‑Level Decomposition)
1. **Collect Query** (Frontend → Backend)
   - Receives raw SQL from the user.
2. **Analyze Query** (Backend)
   - Executes `EXPLAIN ANALYZE` on a sandbox copy of the target DB.
   - Extracts plan features.
3. **Predict Recommendation** (Backend ML Service)
   - Loads the trained Random Forest model.
   - Generates suggested query rewrites.
4. **Present Results** (Backend → Frontend)
   - Returns JSON with execution metrics and recommendations.

## Level 2 (Detailed Processes)
- **Process 2.1: Execute Plan**
  - Input: SQL query, sandbox DB connection string.
  - Output: JSON execution plan.
- **Process 2.2: Feature Extraction**
  - Input: Execution plan JSON.
  - Output: Feature vector for ML model.
- **Process 2.3: Model Inference**
  - Input: Feature vector.
  - Output: Recommendation label and optional rewrite SQL.
- **Process 2.4: Response Formatting**
  - Input: Metrics and recommendation.
  - Output: Structured API response for UI rendering.

*All data stores are read‑only for the analysis phase; no modifications are made to the target database.*
