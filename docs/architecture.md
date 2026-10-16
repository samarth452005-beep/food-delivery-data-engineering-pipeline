# Project Architecture

```text
Historical CSV files
        |
        v
Compressed Parquet
        |
        +----> Private AWS S3 storage
        |
        +----> BigQuery Sandbox
        |        |
        |        +----> SQL analytics views
        |
        v
DuckDB incremental processing prototype
        |
        +----> fact_orders
        +----> pipeline_runs
        +----> data_quality_results
                    |
                    v
             Streamlit dashboards
              /              \
     Pipeline monitoring   Business analytics
```

## Architecture Diagram

The following diagram shows the major components of the project. The diagram represents the overall architecture; the components are not all connected as one automated production pipeline.

```mermaid
flowchart TD
    A["Raw CSV datasets"] --> B["Python data preparation"]
    B --> C["Parquet files"]
    C --> D["Private Amazon S3 storage"]
    C --> E["BigQuery tables"]
    E --> F["BigQuery analytics views"]
    C --> G["DuckDB local incremental pipeline"]
    G --> H["Data quality checks"]
    G --> I["Pipeline run logs"]
    F --> J["Analytics insights"]
    H --> K["Pipeline monitoring dashboard"]
    I --> K
    J --> L["Streamlit analytics demo"]
    M["Synthetic demo data"] --> L
```

## Current scope

- BigQuery is used for read-only SQL analytics.
- DuckDB is used for the local incremental upsert prototype.
- Dashboards currently run in Google Colab.
- Scheduling, production orchestration, and persistent dashboard hosting
  remain future improvements.
