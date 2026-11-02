# ER Diagram (QueryDoctor)

```mermaid
erDiagram
    ANALYZED_QUERIES ||--o{ QUERY_FEATURES : "has"
    ANALYZED_QUERIES ||--o{ ANALYSIS_RESULTS : "produces"
    ANALYSIS_RESULTS ||--o{ RECOMMENDATIONS : "generates"

    ANALYZED_QUERIES {
        uuid query_id PK "UUID primary key"
        text query_text "SQL query text"
        timestampz captured_at "Capture timestamp"
        varchar target_db "Target database identifier"
        float execution_time_ms "Execution time (ms)"
    }
    QUERY_FEATURES {
        serial feature_id PK "Feature identifier"
        uuid query_id FK "FK to ANALYZED_QUERIES"
        varchar feature_name "Name of extracted feature"
        float feature_value "Numeric value"
    }
    ANALYSIS_RESULTS {
        serial result_id PK "Result identifier"
        uuid query_id FK "FK to ANALYZED_QUERIES"
        varchar model_version "ML model version"
        timestampz analysis_timestamp "When analysis ran"
        jsonb plan_json "EXPLAIN ANALYZE JSON plan"
        varchar status "completed|failed"
    }
    RECOMMENDATIONS {
        serial rec_id PK "Recommendation identifier"
        int result_id FK "FK to ANALYSIS_RESULTS"
        text suggestion "Human readable suggestion"
        text rewritten_sql "Optional rewritten SQL"
        float confidence "0..1 confidence score"
    }
```

*All foreign keys enforce referential integrity. The schema stores captured queries, extracted features, analysis results (tied to a specific model version), and recommendations linked to a particular analysis result.*
