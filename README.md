# Eidolon

Network scanner with AI-powered analysis and automation. Scans your infrastructure with nmap, stores it in a graph database (Neo4j), and lets you query and operate on it using natural language. LLM agents generate plans, execute approved actions, and log everything for audit.

## Features

- **Network scanning**: Automated nmap scans build a real-time map of hosts, ports, and services
- **Graph database**: Neo4j stores assets, networks, and connectivity relationships
- **Natural language queries**: Ask "What paths exist from internet to database X?" and get answers
- **Plan generation**: LLM translates intents like "isolate host X" into executable steps
- **Execution runtime**: Sandboxed tools (terminal, browser, file edit) with permission controls
- **Audit trail**: Every scan, query, plan, and execution logged to Postgres
- **Interactive UI**: React frontend for graph visualization, chat, and approval workflows

## Quick Start

```powershell
# Windows PowerShell
.\scripts\dev.ps1

# Linux/macOS
chmod +x scripts/dev.sh && ./scripts/dev.sh
```

This starts all services:
- Postgres (audit logs, chat history): `localhost:5432`
- Neo4j (knowledge graph): `localhost:7474` (browser), `localhost:7687` (bolt)
- API server: `http://localhost:8080`
- React UI: `http://localhost:5173`

## Configuration

Optional: Copy `.env.example` to `.env` and configure:
- Database credentials (if changing defaults)
- LLM settings: `EIDOLON_LLM__MODEL`, `EIDOLON_LLM__API_KEY`, `EIDOLON_LLM__API_BASE`

## Development

**Run tests**:
```bash
pytest
```

**Lint**:
```bash
ruff check .
```

## License

MIT

