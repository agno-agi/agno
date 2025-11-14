# Database Schema Recommendations

This document outlines recommended improvements for all database schema files in `agno/db/`.

## Critical Issues

### 1. Redis Schema Missing Culture Table
**File:** `redis/schemas.py`
- **Issue:** `CULTURAL_KNOWLEDGE_SCHEMA` is defined but not included in `get_table_schema_definition()`
- **Fix:** Add `"culture": CULTURAL_KNOWLEDGE_SCHEMA` to the schemas dictionary

### 2. Missing `feedback` Field in Memory Tables
**Files:** All SQL-based schemas (PostgreSQL, MySQL, SQLite, SingleStore)
- **Issue:** `UserMemory` schema includes `feedback` field, but it's missing from table schemas
- **Impact:** Data loss when storing/retrieving memories with feedback
- **Fix:** Add `"feedback": {"type": String/Text, "nullable": True}` to `USER_MEMORY_TABLE_SCHEMA`

### 3. Missing `workflow_id` in Memory Tables
**Files:** All SQL-based schemas
- **Issue:** `UserMemory` schema includes `workflow_id`, but it's missing from table schemas
- **Impact:** Cannot filter memories by workflow
- **Fix:** Add `"workflow_id": {"type": String, "nullable": True}` to `USER_MEMORY_TABLE_SCHEMA`

## Consistency Issues

### 4. Inconsistent String Length Specifications
**Files:** PostgreSQL vs MySQL/SingleStore/SQLite
- **Issue:** 
  - PostgreSQL: Uses `String` without length
  - MySQL/SingleStore: Uses `String(128)` or `String(255)`
  - SQLite: Uses `String` without length
- **Recommendation:** 
  - Standardize on explicit lengths for better portability
  - Use `String(128)` for IDs, `String(255)` for names/descriptions
  - Document length limits in comments

### 5. Inconsistent Text vs String Types
**Files:** All SQL schemas
- **Issue:**
  - `input` field: PostgreSQL/SQLite use `String`, MySQL/SingleStore use `Text`
  - `description` field: PostgreSQL/SQLite use `String`, MySQL/SingleStore use `Text`
  - `status_message`: PostgreSQL/SQLite use `String`, MySQL/SingleStore use `Text`
- **Recommendation:**
  - Use `Text` for potentially long fields: `input`, `description`, `status_message`, `summary`
  - Use `String(length)` for fixed/short fields: IDs, names, types

### 6. JSON vs JSONB Inconsistency
**File:** `postgres/schemas.py`
- **Issue:** Only `CULTURAL_KNOWLEDGE_TABLE_SCHEMA` uses `JSONB`, others use `JSON`
- **Recommendation:** 
  - Use `JSONB` for all JSON fields in PostgreSQL (better indexing, querying)
  - Or document why `JSON` is preferred for certain fields

### 7. Missing Default Values
**Files:** MySQL, SingleStore schemas
- **Issue:** 
  - MySQL `METRICS_TABLE_SCHEMA` missing `default` values
  - SingleStore missing defaults for some fields
- **Recommendation:** Add consistent defaults:
  ```python
  "agent_runs_count": {"type": BigInteger, "nullable": False, "default": 0},
  "token_metrics": {"type": JSON, "nullable": False, "default": {}},
  "completed": {"type": Boolean, "nullable": False, "default": False},
  ```

### 8. Missing Unique Constraints
**File:** `singlestore/schemas.py`
- **Issue:** Missing unique constraint on `(date, aggregation_period)` for metrics table
- **Fix:** Add `_unique_constraints` similar to MySQL/PostgreSQL/SQLite

## Index Optimization

### 9. Missing Composite Indexes
**Files:** All SQL schemas
- **Issue:** Missing indexes for common query patterns:
  - `(user_id, agent_id, updated_at)` for memory queries
  - `(user_id, team_id, updated_at)` for memory queries
  - `(agent_id, created_at)` for eval queries
  - `(team_id, created_at)` for eval queries
  - `(workflow_id, created_at)` for eval queries
- **Recommendation:** Add composite indexes based on actual query patterns

### 10. Missing Single-Field Indexes
**Files:** All SQL schemas
- **Issue:** Missing indexes on frequently filtered fields:
  - `model_id` in eval tables
  - `model_provider` in eval tables
  - `status` in knowledge tables
  - `type` in knowledge tables
- **Recommendation:** Add indexes for fields used in WHERE clauses

### 11. Inconsistent Index Definitions
**Files:** All SQL schemas
- **Issue:** Some schemas use `"index": True`, others don't specify
- **Recommendation:** Standardize index definitions with explicit index names

## DynamoDB Specific

### 12. Hardcoded Provisioned Throughput
**File:** `dynamo/schemas.py`
- **Issue:** All tables use `ReadCapacityUnits: 5, WriteCapacityUnits: 5`
- **Recommendation:**
  - Consider using `PAY_PER_REQUEST` billing mode for development
  - Make throughput configurable
  - Document capacity planning guidelines

### 13. Missing GSI for Common Queries
**File:** `dynamo/schemas.py`
- **Issue:** Missing GSI for:
  - `(user_id, session_type, created_at)` composite queries
  - `(model_id, created_at)` for eval queries
- **Recommendation:** Add GSIs based on actual query patterns

## MongoDB/Firestore Specific

### 14. Incomplete Index Definitions
**Files:** `mongo/schemas.py`, `firestore/schemas.py`
- **Issue:** Missing composite indexes for common query patterns
- **Recommendation:** Add indexes matching SQL database patterns

### 15. Missing Unique Constraints
**Files:** `mongo/schemas.py`
- **Issue:** Missing unique constraint on `(date, aggregation_period)` for metrics
- **Fix:** Add composite unique index similar to other databases

## Documentation Improvements

### 16. Missing Schema Documentation
**Files:** All schema files
- **Issue:** No documentation explaining:
  - Field purposes
  - Index rationale
  - Query patterns
  - Migration considerations
- **Recommendation:** Add docstrings explaining schema design decisions

### 17. Missing Type Hints
**Files:** All schema files
- **Issue:** Return types not fully specified
- **Recommendation:** Use `TypedDict` or `Protocol` for better type safety

## Best Practices

### 18. Schema Validation
**Recommendation:** Add validation functions to ensure schema consistency across databases

### 19. Migration Support
**Recommendation:** Document schema versioning and migration strategy

### 20. Field Ordering
**Recommendation:** Standardize field ordering:
  1. Primary key
  2. Foreign keys (user_id, agent_id, team_id, workflow_id)
  3. Core fields
  4. Metadata fields
  5. Timestamps (created_at, updated_at)

## Priority Recommendations

### High Priority (Data Integrity)
1. Add missing `feedback` field to memory tables
2. Add missing `workflow_id` to memory tables
3. Fix Redis culture table mapping
4. Add unique constraints where missing

### Medium Priority (Performance)
5. Add missing indexes for common queries
6. Standardize on JSONB for PostgreSQL
7. Add composite indexes for multi-field queries

### Low Priority (Maintainability)
8. Standardize field types (Text vs String)
9. Add explicit string lengths
10. Improve documentation

## Implementation Notes

- Test schema changes against actual query patterns
- Ensure backward compatibility or provide migration scripts
- Consider creating a shared schema definition that generates database-specific schemas
- Document any database-specific optimizations

