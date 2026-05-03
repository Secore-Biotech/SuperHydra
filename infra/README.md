# SuperHydra Infrastructure

## Phase 1 development environment

Local Postgres 16 + TimescaleDB + pg_partman via Docker Compose.

### Start the database

```bash
cd infra/docker
docker compose up -d
```

First-run initialization installs extensions and creates the `gen_uuidv7()` function from `infra/postgres/extensions/00_init_extensions.sql`.

### Verify

```bash
docker compose ps                    # status
docker compose logs postgres --tail=50  # logs
```

Connect with psql:

```bash
docker compose exec postgres psql -U superhydra -d superhydra
```

Inside psql, verify extensions:

```sql
SELECT extname, extversion FROM pg_extension ORDER BY extname;
```

Expected extensions: pgcrypto, pg_partman, plpgsql, timescaledb.

Verify UUIDv7 function:

```sql
SELECT gen_uuidv7();
```

### Stop

```bash
cd infra/docker
docker compose down       # stops containers, keeps volume
docker compose down -v    # stops and removes volume (destroys data)
```

### Connection string

Default: `postgresql://superhydra:superhydra_dev_only@localhost:5432/superhydra`

Available as `DATABASE_URL` environment variable when `.env` is copied from `.env.example`.

### Migrations

SQL migrations live in `infra/postgres/migrations/`, applied in lexicographic order. The first migration creates the schemas and tables per ledger schema v0.3 (`docs/decisions/2026-05-02-ledger-schema-design-v0.3.md`).
