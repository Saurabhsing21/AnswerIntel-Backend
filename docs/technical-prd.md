# AnswerIntel — Technical PRD

## AI Visibility & Competitor Intelligence Platform

**Document Type:** Technical Product & Engineering Specification\
**Version:** v1.0\
**Status:** Engineering Blueprint\
**Primary Users:** Founders, startups, small marketing teams\
**Architecture Style:** Modular Monolith + Async Workers\
**Primary Backend:** Python + FastAPI\
**Primary Database:** PostgreSQL\
**Cache / Queue:** Redis\
**Object Storage:** S3-compatible storage\
**Deployment:** Docker + Cloud Infrastructure

---

# 1. Product Definition

AnswerIntel measures how AI assistants describe and recommend businesses.

A customer gives AnswerIntel:

- Business
- Website
- Category
- Market
- Competitors

AnswerIntel automatically generates realistic customer prompts, sends them to supported AI/search providers, analyzes the responses, identifies competitors and citations, calculates visibility metrics, detects visibility gaps, and recommends actions.

The core loop is:

```text
Business Setup
      ↓
Prompt Discovery
      ↓
Prompt Selection
      ↓
AI Scan
      ↓
Raw Responses
      ↓
Response Analysis
      ↓
Visibility Metrics
      ↓
Competitor Analysis
      ↓
Citation Analysis
      ↓
Opportunity Detection
      ↓
Recommended Actions
      ↓
User Makes Changes
      ↓
Re-scan
      ↓
Measure Change
```

---

# 2. Product Boundary

AnswerIntel is NOT initially:

- an SEO replacement
- a CMS
- an autonomous marketing agent
- an advertising platform
- an enterprise workflow platform
- a CRM
- a content-generation platform

AnswerIntel's initial job is:

> **Measure → Explain → Recommend → Re-measure**

---

# 3. Initial Supported AI Providers

The provider architecture must be abstracted.

Initial providers:

```text
ChatGPT
Perplexity
Gemini
Google AI Search / AI Overviews
```

Future:

```text
Claude
Grok
Copilot
Other AI search engines
```

The application must never directly depend on one provider.

Use:

```text
AIProvider interface
       ↓
ChatGPTProvider
PerplexityProvider
GeminiProvider
GoogleAIProvider
```

---

# 4. High-Level Architecture

```text
                         ┌─────────────────────┐
                         │      Web App        │
                         │   React / Next.js   │
                         └──────────┬──────────┘
                                    │ HTTPS
                                    ▼
                         ┌─────────────────────┐
                         │      API Gateway   │
                         │      FastAPI       │
                         └──────────┬──────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
              ▼                     ▼                     ▼
       Auth Service          Project Service       Analytics API
              │                     │                     │
              └─────────────────────┼─────────────────────┘
                                    │
                                    ▼
                           ┌─────────────────┐
                           │    PostgreSQL   │
                           └─────────────────┘
                                    ▲
                                    │
                         ┌──────────┴──────────┐
                         │                     │
                         │    Redis Queue      │
                         │                     │
                         └──────────┬──────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
              ▼                     ▼                     ▼
       Prompt Worker          Scan Worker          Analysis Worker
              │                     │                     │
              │                     ▼                     │
              │            ┌────────────────┐             │
              │            │ AI Providers   │             │
              │            └───────┬────────┘             │
              │                    │                      │
              │                    ▼                      │
              │             Raw AI Responses              │
              │                    │                      │
              └────────────────────┼──────────────────────┘
                                   ▼
                            Analysis Pipeline
                                   │
                  ┌────────────────┼────────────────┐
                  ▼                ▼                ▼
              Mentions         Competitors       Citations
                  │                │                │
                  └────────────────┼────────────────┘
                                   ▼
                            Metrics Engine
                                   │
                                   ▼
                          Opportunity Engine
                                   │
                                   ▼
                              PostgreSQL
```

---

# 5. Architecture Decision

For V1, do NOT build microservices.

Use:

```text
FastAPI application
      +
PostgreSQL
      +
Redis
      +
Background workers
```

Internally separate code into modules.

Example:

```text
backend/
│
├── app/
│   ├── api/
│   ├── auth/
│   ├── users/
│   ├── projects/
│   ├── prompts/
│   ├── scans/
│   ├── providers/
│   ├── analysis/
│   ├── competitors/
│   ├── citations/
│   ├── opportunities/
│   ├── experiments/
│   ├── reports/
│   ├── billing/
│   └── common/
│
├── workers/
│   ├── prompt_worker.py
│   ├── scan_worker.py
│   ├── analysis_worker.py
│   └── report_worker.py
│
├── models/
├── schemas/
├── repositories/
├── services/
├── tests/
└── main.py
```

---

# 6. Authentication

Use:

```text
Email + Password
```

Optionally later:

```text
Google OAuth
GitHub OAuth
```

Authentication flow:

```text
User
 ↓
POST /auth/register
 ↓
Password hashed using Argon2id
 ↓
User created
 ↓
POST /auth/login
 ↓
Access Token
 ↓
Refresh Token
```

Recommended:

```text
Access token:
15 minutes

Refresh token:
30 days
```

Access token should be JWT.

Refresh tokens should be stored securely.

For browser:

```text
HttpOnly
Secure
SameSite=Lax
```

Never store authentication secrets in localStorage.

---

# 7. Authorization

Every resource belongs to a user/workspace.

Initial model:

```text
User
  ↓
Workspace
  ↓
Project
```

Example:

```text
User
 └── Workspace
      └── Project: Acme CRM
```

Every API request must validate:

```text
authenticated user
        ↓
workspace membership
        ↓
resource ownership
```

Never trust:

```text
project_id
user_id
workspace_id
```

from the client without authorization checks.

---

# 8. Core Domain Model

Main entities:

```text
User
Workspace
Project
Competitor
Prompt
PromptRun
Scan
AIResponse
BrandMention
CompetitorMention
Citation
MetricSnapshot
Opportunity
Recommendation
Experiment
ExperimentSnapshot
Report
```

---

# 9. Database

Use PostgreSQL.

## users

```sql
users
-----
id UUID PK
email VARCHAR UNIQUE
password_hash TEXT
name VARCHAR
created_at TIMESTAMP
updated_at TIMESTAMP
```

---

## workspaces

```sql
workspaces
----------
id UUID PK
name VARCHAR
created_at TIMESTAMP
updated_at TIMESTAMP
```

---

## workspace_members

```sql
workspace_members
-----------------
workspace_id UUID
user_id UUID
role VARCHAR

PRIMARY KEY(workspace_id, user_id)
```

Roles:

```text
owner
admin
member
```

---

# 10. Projects

A project represents one business being monitored.

```sql
projects
--------
id UUID PK
workspace_id UUID FK
name VARCHAR
brand_name VARCHAR
website_url TEXT
description TEXT
category VARCHAR
country VARCHAR
language VARCHAR
timezone VARCHAR
status VARCHAR
created_at TIMESTAMP
updated_at TIMESTAMP
```

Example:

```text
Project:
Acme CRM

Brand:
Acme

Website:
https://acme.com

Category:
CRM Software

Country:
United States
```

---

# 11. Competitors

```sql
competitors
-----------
id UUID PK
project_id UUID FK
name VARCHAR
website_url TEXT
description TEXT
created_at TIMESTAMP
```

Initial limit:

```text
3–5 competitors
```

---

# 12. Prompt Model

A prompt is the question we ask AI.

```sql
prompts
-------
id UUID PK
project_id UUID FK

text TEXT

category VARCHAR
intent VARCHAR

source VARCHAR

status VARCHAR

created_at TIMESTAMP
updated_at TIMESTAMP
```

Prompt categories:

```text
category
comparison
alternative
problem
use_case
buyer_intent
competitor
```

Intent:

```text
informational
commercial
transactional
comparison
```

---

# 13. Prompt Generation

Prompt generation uses an LLM.

Input:

```json
{
  "brand": "Acme",
  "category": "CRM",
  "market": "US",
  "competitors": [
    "HubSpot",
    "Attio",
    "Pipedrive"
  ]
}
```

LLM generates:

```text
30–50 prompts
```

Example:

```text
Best CRM for a 10-person startup?

What are the best HubSpot alternatives?

What CRM is easiest for startups?

Best affordable CRM for small businesses?

Which CRM should a SaaS startup use?
```

---

# 14. Prompt Generation Agent

Use a dedicated LLM agent.

Name:

```text
Prompt Discovery Agent
```

Responsibilities:

1. Understand business
2. Understand category
3. Understand target market
4. Understand competitors
5. Generate realistic customer questions
6. Categorize prompts
7. Remove duplicates
8. Score commercial relevance

Agent output:

```json
{
  "prompt": "...",
  "category": "comparison",
  "intent": "commercial",
  "importance": 0.91
}
```

---

# 15. Prompt Generation System Prompt

Conceptual prompt:

```text
You are a customer research and AI-search prompt generation agent.

Given a business, category, market, and competitors, generate realistic
questions a potential customer could ask an AI assistant.

Do not generate questions merely containing the company name.

Prioritize:
- category discovery
- commercial intent
- comparison
- alternatives
- use cases
- customer problems
- competitor discovery
- buying decisions

Every prompt must represent a realistic customer question.

Return structured JSON.
```

The actual prompt should live in version-controlled configuration.

---

# 16. Scan Model

A scan represents one complete measurement run.

```sql
scans
-----
id UUID PK
project_id UUID FK

status VARCHAR

started_at TIMESTAMP
completed_at TIMESTAMP

total_prompts INTEGER
completed_prompts INTEGER
failed_prompts INTEGER

created_at TIMESTAMP
```

Statuses:

```text
queued
running
completed
partial
failed
cancelled
```

---

# 17. Scan Flow

```text
POST /projects/{project_id}/scans
             ↓
Validate project
             ↓
Create Scan
             ↓
Load active prompts
             ↓
Create PromptRun records
             ↓
Push jobs to Redis
             ↓
Workers execute prompts
             ↓
Store raw responses
             ↓
Analysis jobs
             ↓
Calculate metrics
             ↓
Generate opportunities
             ↓
Mark Scan completed
```

---

# 18. AI Provider Abstraction

Define:

```python
class AIProvider(ABC):

    @abstractmethod
    async def generate_response(
        self,
        prompt: str,
        context: ProviderContext
    ) -> ProviderResponse:
        pass
```

Provider response:

```python
class ProviderResponse:
    provider: str
    model: str
    text: str
    citations: list
    metadata: dict
    latency_ms: int
```

---

# 19. Provider Adapter

Example:

```text
providers/
│
├── base.py
├── chatgpt.py
├── perplexity.py
├── gemini.py
└── google_ai.py
```

The scan worker should NOT know how an individual provider works.

Bad:

```python
if provider == "chatgpt":
    ...
elif provider == "gemini":
    ...
```

Instead:

```python
provider = provider_registry.get(provider_name)

response = await provider.generate_response(
    prompt,
    context
)
```

---

# 20. Provider Credentials

API credentials must NEVER be stored in PostgreSQL as plaintext.

Use:

```text
Secret Manager
```

Examples:

```text
AWS Secrets Manager
GCP Secret Manager
Doppler
Vault
```

Environment variables are acceptable for local development.

Production:

```text
Secret Manager
      ↓
Application
      ↓
Provider
```

---

# 21. Prompt Execution

Each prompt run should record:

```sql
prompt_runs
-----------
id UUID PK
scan_id UUID FK
prompt_id UUID FK

provider VARCHAR
model VARCHAR

status VARCHAR

started_at TIMESTAMP
completed_at TIMESTAMP

latency_ms INTEGER
error_code VARCHAR
error_message TEXT
```

---

# 22. AI Responses

Store the raw provider response.

```sql
ai_responses
-----------
id UUID PK
prompt_run_id UUID FK

provider VARCHAR
model VARCHAR

raw_text TEXT

raw_response JSONB

created_at TIMESTAMP
```

Why store raw response?

Because analysis logic will change.

Today:

```text
Mention detection v1
```

Tomorrow:

```text
Mention detection v2
```

We should be able to re-analyze old responses without paying the AI provider again.

---

# 23. Response Analysis Pipeline

After every AI response:

```text
Raw Response
      ↓
Brand Detection
      ↓
Competitor Detection
      ↓
Recommendation Detection
      ↓
Position Extraction
      ↓
Sentiment Detection
      ↓
Citation Extraction
      ↓
Reason Extraction
      ↓
Structured Result
```

---

# 24. Brand Detection

We need to determine:

```text
Was brand mentioned?
```

Output:

```json
{
  "mentioned": true,
  "mentions": 2,
  "recommendation": true
}
```

Detection should combine:

```text
exact name
aliases
domain
known product names
LLM classification
```

Do not rely only on string matching.

---

# 25. Competitor Detection

For every configured competitor:

```text
mentioned?
recommended?
position?
sentiment?
```

Example:

```json
{
  "competitor": "Attio",
  "mentioned": true,
  "recommended": true,
  "position": 1
}
```

---

# 26. Recommendation Detection

A mention does NOT automatically mean recommendation.

Example:

> “Acme is a company that provides CRM software, but HubSpot is often recommended for startups.”

Acme:

```text
mentioned = true
recommended = false
```

HubSpot:

```text
mentioned = true
recommended = true
```

This distinction is critical.

---

# 27. Position

If AI produces:

```text
1. HubSpot
2. Attio
3. Acme
```

store:

```text
position = 3
```

If response is prose:

```text
"Acme is one option, although HubSpot is generally better suited..."
```

Position may be:

```text
NULL
```

Do not invent rankings.

---

# 28. Citation Model

```sql
citations
---------
id UUID PK
ai_response_id UUID FK

url TEXT
domain VARCHAR

title TEXT

source_type VARCHAR

is_brand_owned BOOLEAN

created_at TIMESTAMP
```

Source categories:

```text
brand_website
review_site
reddit
news
blog
directory
social
comparison
documentation
other
```

---

# 29. Citation Analysis

For every response determine:

```text
Which sources were cited?
Who owns them?
Are they about our brand?
Are they about competitors?
How frequently do they appear?
```

This allows:

```text
Competitor has 8 recurring third-party sources.

Our brand has 2.
```

---

# 30. Metrics Engine

Metrics should be computed from raw observations.

Do not permanently store only a single score.

Core metrics:

```text
Mention Rate
Recommendation Rate
Average Position
Share of Voice
Citation Rate
Positive Sentiment Rate
Competitor Visibility
```

---

# 31. Mention Rate

```text
mention_rate =
prompts_where_brand_mentioned
/
total_successful_prompts
```

Example:

```text
Brand mentioned in 18 / 50

Mention Rate = 36%
```

---

# 32. Recommendation Rate

```text
recommendation_rate =
prompts_where_brand_recommended
/
total_successful_prompts
```

This is more important than raw mentions.

---

# 33. Share of Voice

For each prompt:

```text
brands recommended by AI
```

Calculate brand appearance relative to competitors.

Example:

```text
Acme: 25
HubSpot: 40
Attio: 35
```

Then:

```text
Acme SOV = 25 / 100 = 25%
```

The exact methodology must be documented and remain consistent across versions.

---

# 34. Metrics Snapshot

```sql
metric_snapshots
----------------
id UUID PK
project_id UUID FK
scan_id UUID FK

mention_rate DECIMAL
recommendation_rate DECIMAL
citation_rate DECIMAL
share_of_voice DECIMAL

average_position DECIMAL

created_at TIMESTAMP
```

---

# 35. Competitor Metrics

```sql
competitor_metrics
------------------
id UUID PK
scan_id UUID FK
competitor_id UUID FK

mention_rate DECIMAL
recommendation_rate DECIMAL
share_of_voice DECIMAL
average_position DECIMAL

created_at TIMESTAMP
```

---

# 36. Opportunity Engine

This is the intelligence layer.

Input:

```text
Brand metrics
Competitor metrics
Prompts
AI responses
Citations
Source frequency
Content signals
```

Output:

```text
Opportunity
```

---

# 37. Opportunity Types

Initial taxonomy:

```text
CONTENT_GAP
CITATION_GAP
COMPETITOR_GAP
POSITIONING_GAP
COMPARISON_GAP
ENTITY_GAP
TECHNICAL_GAP
```

---

# 38. Opportunity Example

```json
{
  "type": "CITATION_GAP",
  "title": "Competitor has stronger third-party coverage",
  "description": "Attio appears in 7 recurring sources while your brand appears in 2.",
  "impact": "high",
  "confidence": 0.87,
  "recommended_action": "Increase relevant third-party coverage."
}
```

---

# 39. Recommendation Engine

Recommendations should be generated from detected evidence.

Bad:

```text
Write more blog posts.
```

Good:

```text
Your brand is absent from 6 high-value startup CRM comparison prompts.
Create a dedicated "CRM for Startups" page and strengthen startup-specific
positioning.
```

Recommendations should contain:

```text
problem
evidence
recommended action
expected objective
related prompts
```

---

# 40. Opportunity Database

```sql
opportunities
-------------
id UUID PK
project_id UUID FK
scan_id UUID FK

type VARCHAR
title VARCHAR
description TEXT

impact VARCHAR
confidence DECIMAL

status VARCHAR

created_at TIMESTAMP
updated_at TIMESTAMP
```

Statuses:

```text
open
in_progress
completed
dismissed
```

---

# 41. Experiments

Users should be able to track changes.

```sql
experiments
-----------
id UUID PK
project_id UUID FK

name VARCHAR
description TEXT

status VARCHAR

started_at TIMESTAMP
ended_at TIMESTAMP

created_at TIMESTAMP
```

---

# 42. Experiment Snapshots

```sql
experiment_snapshots
--------------------
id UUID PK
experiment_id UUID FK
scan_id UUID FK

mention_rate DECIMAL
recommendation_rate DECIMAL
share_of_voice DECIMAL
average_position DECIMAL

created_at TIMESTAMP
```

This enables:

```text
Before change
      ↓
Website/content change
      ↓
Wait
      ↓
Re-scan
      ↓
After change
      ↓
Compare
```

---

# 43. Reports

Weekly report generation:

```sql
reports
-------
id UUID PK
project_id UUID FK

type VARCHAR
period_start DATE
period_end DATE

status VARCHAR

storage_url TEXT

created_at TIMESTAMP
```

Report types:

```text
weekly
monthly
manual
```

---

# 44. API Architecture

Base URL:

```text
/api/v1
```

---

# 45. Authentication APIs

### Register

```http
POST /api/v1/auth/register
```

Request:

```json
{
  "email": "user@example.com",
  "password": "********",
  "name": "John"
}
```

Response:

```json
{
  "user": {
    "id": "...",
    "email": "user@example.com",
    "name": "John"
  }
}
```

---

### Login

```http
POST /api/v1/auth/login
```

---

### Refresh

```http
POST /api/v1/auth/refresh
```

---

### Logout

```http
POST /api/v1/auth/logout
```

---

# 46. Project APIs

### Create project

```http
POST /api/v1/projects
```

```json
{
  "name": "Acme CRM",
  "brand_name": "Acme",
  "website_url": "https://acme.com",
  "category": "CRM Software",
  "country": "US",
  "description": "CRM for early stage startups"
}
```

---

### Get project

```http
GET /api/v1/projects/{project_id}
```

---

### Update project

```http
PATCH /api/v1/projects/{project_id}
```

---

### Delete project

```http
DELETE /api/v1/projects/{project_id}
```

---

# 47. Competitor APIs

```http
POST   /api/v1/projects/{project_id}/competitors
GET    /api/v1/projects/{project_id}/competitors
PATCH  /api/v1/competitors/{competitor_id}
DELETE /api/v1/competitors/{competitor_id}
```

---

# 48. Prompt APIs

```http
POST /api/v1/projects/{project_id}/prompts/generate
```

Generate prompts using Prompt Discovery Agent.

---

```http
GET /api/v1/projects/{project_id}/prompts
```

Filters:

```text
category
intent
status
```

---

```http
PATCH /api/v1/prompts/{prompt_id}
```

User can edit/deactivate a prompt.

---

# 49. Scan APIs

### Start scan

```http
POST /api/v1/projects/{project_id}/scans
```

Response:

```json
{
  "scan_id": "...",
  "status": "queued"
}
```

---

### Scan status

```http
GET /api/v1/scans/{scan_id}
```

Response:

```json
{
  "id": "...",
  "status": "running",
  "total_prompts": 50,
  "completed_prompts": 31,
  "failed_prompts": 2
}
```

---

### Scan results

```http
GET /api/v1/scans/{scan_id}/results
```

---

# 50. Dashboard API

```http
GET /api/v1/projects/{project_id}/dashboard
```

Response:

```json
{
  "visibility": {
    "mention_rate": 0.36,
    "recommendation_rate": 0.24,
    "citation_rate": 0.31,
    "share_of_voice": 0.18
  },
  "competitors": [],
  "top_opportunities": [],
  "trends": []
}
```

This endpoint should aggregate existing data.

Do NOT run expensive LLM analysis inside this request.

---

# 51. Competitor Intelligence API

```http
GET /api/v1/projects/{project_id}/competitors/analysis
```

Returns:

```text
Our brand
Competitor metrics
Visibility difference
Prompt-level wins/losses
Citation differences
```

---

# 52. Citation API

```http
GET /api/v1/projects/{project_id}/citations
```

Filters:

```text
brand
competitor
source_type
date
```

---

# 53. Opportunity APIs

```http
GET   /api/v1/projects/{project_id}/opportunities
GET   /api/v1/opportunities/{opportunity_id}
PATCH /api/v1/opportunities/{opportunity_id}
```

---

# 54. Experiment APIs

```http
POST /api/v1/projects/{project_id}/experiments

GET /api/v1/projects/{project_id}/experiments

GET /api/v1/experiments/{experiment_id}

POST /api/v1/experiments/{experiment_id}/complete
```

---

# 55. Report APIs

```http
GET /api/v1/projects/{project_id}/reports
POST /api/v1/projects/{project_id}/reports
GET /api/v1/reports/{report_id}
```

---

# 56. Background Jobs

Use Redis + worker system.

Recommended:

```text
Celery
```

or:

```text
RQ
```

For initial implementation:

```text
Celery + Redis
```

---

# 57. Queue Design

Queues:

```text
prompt-generation
scan
provider-execution
analysis
metrics
opportunities
reports
```

Flow:

```text
API
 ↓
Redis
 ↓
Worker
 ↓
Database
```

---

# 58. Job Idempotency

Every scan job must be idempotent.

A job should have:

```text
scan_id
prompt_id
provider
```

Unique constraint:

```text
(scan_id, prompt_id, provider)
```

This prevents accidental duplicate provider calls.

---

# 59. Retry Policy

Provider failure:

```text
Retry 1 → 30 sec
Retry 2 → 2 min
Retry 3 → 10 min
```

After retry exhaustion:

```text
status = failed
```

The scan can become:

```text
partial
```

instead of failing completely.

---

# 60. Rate Limiting

API:

```text
Login:
5 requests/minute/IP

General API:
100 requests/minute/user

Scan:
limited by plan
```

Provider requests:

```text
provider-specific rate limiter
```

---

# 61. Scan Cost Control

AI calls can become the biggest variable cost.

Therefore:

```text
User prompts
      ↓
Prompt deduplication
      ↓
Provider scheduling
      ↓
Rate limiting
      ↓
Execution
```

Never blindly execute duplicate prompts.

---

# 62. Response Caching

Do not cache forever because AI responses change.

Use:

```text
short-lived cache
```

for accidental duplicate executions.

But each scheduled scan should create a new observation.

Important distinction:

```text
Cache
≠
Historical observation
```

Historical scans must always remain immutable.

---

# 63. Security

Required:

```text
HTTPS
JWT authentication
Argon2id password hashing
HttpOnly cookies
CSRF protection where applicable
Rate limiting
Input validation
SQL parameterization
Secrets manager
Encryption at rest
Encryption in transit
```

Never log:

```text
password
JWT
refresh token
API keys
provider secrets
```

---

# 64. Data Isolation

Every database query involving customer data must be scoped to:

```text
workspace_id
```

Example:

```python
project = await project_repo.get(
    project_id=project_id,
    workspace_id=current_workspace.id
)
```

Never:

```python
project = await project_repo.get(project_id)
```

without authorization.

---

# 65. Observability

Use:

```text
structured logging
metrics
tracing
error monitoring
```

Recommended:

```text
OpenTelemetry
Sentry
Prometheus
Grafana
```

Track:

```text
API latency
provider latency
provider errors
scan duration
scan success rate
LLM cost
tokens consumed
worker failures
queue depth
database latency
```

---

# 66. Important Business Metrics

Product analytics:

```text
project_created
prompts_generated
first_scan_started
first_scan_completed
dashboard_viewed
competitor_added
opportunity_viewed
experiment_created
weekly_report_opened
```

Most important activation event:

> **User completes first scan and sees their brand vs competitors.**

---

# 67. LLM Architecture

There should NOT be one giant agent.

Use specialized components.

```text
Prompt Discovery Agent
        ↓
Response Analysis Agent
        ↓
Opportunity Analysis Agent
        ↓
Report Generation Agent
```

But deterministic code should handle calculations.

LLM should NOT calculate:

```text
share of voice
percentages
averages
counts
```

Python should do those.

LLM should handle:

```text
classification
semantic detection
reasoning
summarization
recommendation generation
```

---

# 68. Agent 1 — Prompt Discovery

Input:

```text
Business
Category
Market
Competitors
```

Output:

```text
30–50 prompts
```

---

# 69. Agent 2 — Response Analysis

Input:

```text
Prompt
Brand
Competitors
AI response
```

Output structured JSON:

```json
{
  "brand": {
    "mentioned": true,
    "recommended": true,
    "position": 2,
    "sentiment": "positive"
  },
  "competitors": [
    {
      "name": "Attio",
      "mentioned": true,
      "recommended": true,
      "position": 1
    }
  ],
  "reasoning": [
    "Attio is positioned as startup-friendly"
  ]
}
```

The response must be validated using Pydantic.

---

# 70. Agent 3 — Opportunity Analysis

Input:

```text
Recent scan
Historical scan
Competitors
Citations
Prompt-level results
```

Output:

```json
{
  "opportunities": [
    {
      "type": "CITATION_GAP",
      "title": "...",
      "evidence": [],
      "recommended_action": "..."
    }
  ]
}
```

---

# 71. Agent 4 — Report Generation

Input:

```text
Weekly metrics
Changes
Competitor movements
Top opportunities
```

Output:

```text
Founder-friendly weekly report.
```

Do not allow this agent to invent metrics.

It receives already-computed numbers.

---

# 72. LLM Safety

All LLM outputs must be treated as untrusted data.

Use:

```text
Pydantic validation
JSON schema
length limits
allowed enums
```

Reject malformed output.

Never execute LLM-generated:

```text
SQL
shell commands
code
URLs without validation
```

---

# 73. Frontend Pages

Initial pages:

```text
/login
/register

/onboarding

/dashboard

/projects
/projects/:id

/projects/:id/prompts
/projects/:id/competitors
/projects/:id/sources
/projects/:id/opportunities
/projects/:id/experiments
/projects/:id/reports
```

---

# 74. Onboarding Flow

```text
Sign up
 ↓
Create workspace
 ↓
Enter business
 ↓
Enter website
 ↓
Select category
 ↓
Select market
 ↓
Add competitors
 ↓
Generate prompts
 ↓
Review prompts
 ↓
Start first scan
 ↓
Processing
 ↓
Dashboard
```

---

# 75. First Scan UX

Show:

```text
Generating prompts        ✓
Preparing scan            ✓
Running AI queries        72%
Analyzing responses       41%
Calculating visibility    ...
Finding opportunities     ...
```

Then:

```text
Your AI Visibility Report is ready.
```

---

# 76. Dashboard

Top section:

```text
AI Visibility
36%

Recommendation Rate
24%

Share of Voice
18%

Citation Rate
31%
```

Second section:

```text
Visibility Trend
```

Third:

```text
You vs Competitors
```

Fourth:

```text
Top Opportunities
```

Fifth:

```text
Recent AI Answers
```

---

# 77. Prompt Detail Page

For each prompt:

```text
PROMPT

"Best CRM for a 10-person startup?"

────────────────────────────

ChatGPT

1. HubSpot
2. Attio
3. Acme

Your position:
3

────────────────────────────

Perplexity

HubSpot...
Attio...
```

Then:

```text
Why competitors appear
```

and:

```text
Sources cited
```

---

# 78. Competitor Page

Show:

```text
Your Brand
VS
Competitors
```

Metrics:

```text
Mention Rate
Recommendation Rate
Share of Voice
Average Position
Citation Coverage
```

Then:

```text
Prompts where competitor wins
```

---

# 79. Sources Page

Show:

```text
Most influential sources

reddit.com
g2.com
capterra.com
techcrunch.com
competitor.com
```

Group:

```text
Your brand
Competitors
Both
```

---

# 80. Opportunities Page

Each opportunity:

```text
HIGH IMPACT

Competitor citation gap

Attio appears in 7 sources.
You appear in 2.

Why it matters:
AI repeatedly cites these sources
when answering startup CRM questions.

Suggested action:
Improve third-party presence around
startup CRM use cases.

Related prompts:
5
```

---

# 81. Scheduling

Every project can have:

```text
Weekly scan
```

Later:

```text
Daily
Weekly
Custom
```

Scheduler:

```text
Cron
 ↓
Create scan
 ↓
Queue jobs
```

Do not run the entire scan inside the scheduler.

---

# 82. Scan Schedule Model

```sql
scan_schedules
--------------
id UUID PK
project_id UUID FK

frequency VARCHAR
day_of_week INTEGER
hour INTEGER

enabled BOOLEAN

created_at TIMESTAMP
updated_at TIMESTAMP
```

---

# 83. Billing Architecture

Do not implement complex billing initially.

But design for it.

Possible future plans:

```text
Free
Starter
Growth
Agency
```

Usage limits:

```text
projects
prompts
scans/month
AI providers
historical retention
reports
```

Create an internal usage model:

```sql
usage_records
-------------
id UUID PK
workspace_id UUID
metric VARCHAR
quantity INTEGER
period_start DATE
period_end DATE
```

---

# 84. Cost Model

Track cost per:

```text
scan
provider
prompt
LLM analysis
```

Example:

```sql
ai_usage
--------
id UUID PK
workspace_id UUID
scan_id UUID

provider VARCHAR
model VARCHAR

input_tokens INTEGER
output_tokens INTEGER

estimated_cost DECIMAL

created_at TIMESTAMP
```

This is critical because our gross margin depends on AI/provider costs.

---

# 85. API Error Format

All APIs should return:

```json
{
  "error": {
    "code": "PROJECT_NOT_FOUND",
    "message": "Project not found."
  }
}
```

Never expose:

```text
stack trace
SQL error
provider secret
internal exception
```

---

# 86. Common Error Codes

```text
AUTH_INVALID_CREDENTIALS
AUTH_UNAUTHORIZED

PROJECT_NOT_FOUND
PROJECT_ACCESS_DENIED

PROMPT_NOT_FOUND

SCAN_ALREADY_RUNNING
SCAN_NOT_FOUND

PROVIDER_UNAVAILABLE
PROVIDER_RATE_LIMITED

INVALID_REQUEST
VALIDATION_ERROR

INTERNAL_ERROR
```

---

# 87. Database Indexes

Important indexes:

```text
users.email

projects.workspace_id

competitors.project_id

prompts.project_id

scans.project_id

prompt_runs.scan_id

prompt_runs.prompt_id

ai_responses.prompt_run_id

citations.ai_response_id

metric_snapshots.project_id

opportunities.project_id
```

Composite:

```text
(project_id, created_at)
(scan_id, prompt_id)
```

---

# 88. Database Retention

Raw responses are valuable.

Initial:

```text
12 months
```

Later plan-based retention:

```text
Free:
30 days

Starter:
6 months

Growth:
12+ months
```

Do not delete analytical aggregates when deleting raw responses.

---

# 89. API Versioning

All public APIs:

```text
/api/v1
```

Never make breaking changes directly to v1.

Future:

```text
/api/v2
```

---

# 90. Testing Strategy

Four levels.

## Unit tests

Test:

```text
metric calculations
prompt validation
authorization
classification helpers
repository logic
```

## Integration tests

Test:

```text
API + PostgreSQL
API + Redis
worker + database
```

## Provider contract tests

Mock:

```text
ChatGPT
Perplexity
Gemini
```

Verify every provider adapter returns the same internal structure.

## End-to-end

Test:

```text
Register
 ↓
Create project
 ↓
Add competitors
 ↓
Generate prompts
 ↓
Run scan
 ↓
Analyze response
 ↓
Dashboard
```

---

# 91. Example E2E Flow

```text
POST /auth/register

        ↓

POST /projects

        ↓

POST /projects/{id}/competitors

        ↓

POST /projects/{id}/prompts/generate

        ↓

POST /projects/{id}/scans

        ↓

Redis Queue

        ↓

Scan Worker

        ↓

AI Provider

        ↓

AI Response

        ↓

Analysis Worker

        ↓

Metrics Worker

        ↓

Opportunity Worker

        ↓

GET /projects/{id}/dashboard
```

---

# 92. Deployment Architecture

Initial production:

```text
                    Internet
                       │
                       ▼
                  Cloudflare
                       │
                       ▼
                Load Balancer
                       │
            ┌──────────┴──────────┐
            ▼                     ▼
        FastAPI                 FastAPI
        Instance               Instance
            │                     │
            └──────────┬──────────┘
                       ▼
                  PostgreSQL
                       │
                       ▼
                     Redis
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
          Worker 1             Worker 2
```

Frontend:

```text
Next.js
```

can be deployed separately.

---

# 93. Object Storage

Use S3-compatible storage for:

```text
reports
exports
large raw artifacts
```

Database should store:

```text
metadata
storage key
```

not large files.

---

# 94. Environment Configuration

Example:

```env
APP_ENV=production

DATABASE_URL=
REDIS_URL=

JWT_SECRET=
JWT_ACCESS_TTL=
JWT_REFRESH_TTL=

OPENAI_API_KEY=
PERPLEXITY_API_KEY=
GEMINI_API_KEY=

S3_BUCKET=
S3_ACCESS_KEY=
S3_SECRET_KEY=

SENTRY_DSN=
```

Never commit `.env`.

Provide:

```text
.env.example
```

---

# 95. Repository Structure

```text
answerintel/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── auth/
│   │   ├── projects/
│   │   ├── competitors/
│   │   ├── prompts/
│   │   ├── scans/
│   │   ├── providers/
│   │   ├── analysis/
│   │   ├── citations/
│   │   ├── metrics/
│   │   ├── opportunities/
│   │   ├── experiments/
│   │   ├── reports/
│   │   ├── billing/
│   │   └── common/
│   │
│   ├── workers/
│   ├── models/
│   ├── schemas/
│   ├── repositories/
│   ├── services/
│   ├── tests/
│   └── main.py
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── features/
│   ├── lib/
│   └── tests/
│
├── infrastructure/
│   ├── docker/
│   ├── terraform/
│   └── scripts/
│
├── docs/
│   ├── architecture.md
│   ├── api.md
│   ├── database.md
│   └── agents.md
│
├── docker-compose.yml
├── .env.example
└── README.md
```

---

# 96. Development Phases

## Phase 1 — Foundation

Build:

```text
Repository
Docker
FastAPI
PostgreSQL
Redis
Alembic
Authentication
Workspace
Project
```

---

## Phase 2 — Business Configuration

Build:

```text
Project CRUD
Competitor CRUD
Business onboarding
```

---

## Phase 3 — Prompt Engine

Build:

```text
Prompt model
Prompt Discovery Agent
Prompt generation API
Prompt editing
Prompt categorization
```

---

## Phase 4 — Provider Engine

Build:

```text
AIProvider interface
ChatGPT adapter
Perplexity adapter
Gemini adapter
```

Start with one provider end-to-end before adding all providers.

---

## Phase 5 — Scan Engine

Build:

```text
Scan
PromptRun
Redis queue
Worker
Retries
Rate limits
Provider execution
```

---

## Phase 6 — Analysis Engine

Build:

```text
Brand detection
Competitor detection
Recommendation detection
Position detection
Citation extraction
Sentiment
```

---

## Phase 7 — Metrics

Build:

```text
Mention Rate
Recommendation Rate
Share of Voice
Citation Rate
Average Position
Competitor metrics
Historical trends
```

---

## Phase 8 — Intelligence

Build:

```text
Opportunity Engine
Competitor Gap Analysis
Citation Gap Analysis
Recommendations
```

---

## Phase 9 — Dashboard

Build:

```text
Overview
Prompt results
Competitors
Sources
Opportunities
```

---

## Phase 10 — Experiments

Build:

```text
Experiment
Before/after scans
Impact comparison
```

---

## Phase 11 — Reports

Build:

```text
Weekly reports
Email delivery
PDF/export
```

---

# 97. MVP Definition

MVP is complete when a new user can:

```text
1. Register
2. Create a project
3. Add website
4. Add competitors
5. Generate prompts
6. Review prompts
7. Start a scan
8. Query AI provider
9. Store response
10. Analyze response
11. Detect brand
12. Detect competitors
13. Extract citations
14. Calculate visibility
15. View dashboard
16. See competitor differences
17. See opportunities
18. Run another scan
19. Compare results
```

If these 19 things work reliably, we have the first real product.

---

# 98. MVP Acceptance Criteria

### Authentication

- User can register.
- User can login.
- Unauthorized users cannot access projects.
- Users cannot access another workspace's data.

### Prompt Engine

- Generates relevant prompts.
- No obvious duplicates.
- Prompts are categorized.
- User can edit/deactivate prompts.

### Scan Engine

- Scan can be started.
- Scan runs asynchronously.
- Failed prompts do not kill entire scan.
- Provider failures retry.
- Scan status is observable.

### Analysis

- Brand detection works.
- Competitor detection works.
- Recommendation differs from mention.
- Citations are stored.
- Raw response is preserved.

### Dashboard

- Metrics are calculated from stored observations.
- Historical scans can be compared.
- Competitors are visible.
- Opportunities are displayed.

### Security

- Passwords are hashed.
- Secrets are not exposed.
- Workspace isolation works.
- API rate limits work.

---

# 99. What We Should NOT Build Before the Core Loop Works

Do not build:

```text
Billing
Enterprise SSO
Agency white-label
50 AI providers
Mobile app
Chrome extension
AI content writer
Autonomous SEO agent
Complex permissions
Advanced CMS integrations
```

until this works:

```text
Prompt
 ↓
AI Answer
 ↓
Analysis
 ↓
Competitor
 ↓
Citation
 ↓
Metric
 ↓
Opportunity
```

That is the heart of AnswerIntel.

---

# 100. Most Important Technical Principle

The architecture must preserve the difference between:

## Observation

What AI actually said.

```text
Raw AI response
```

## Interpretation

What our system thinks it means.

```text
Brand mentioned
Competitor recommended
Citation detected
```

## Metric

What we calculate.

```text
24% recommendation rate
```

## Recommendation

What we suggest.

```text
Improve third-party coverage
```

These must never be mixed.

The data flow must remain:

```text
RAW DATA
   ↓
STRUCTURED OBSERVATION
   ↓
CALCULATED METRIC
   ↓
AI INTERPRETATION
   ↓
RECOMMENDATION
```

This separation is extremely important because if our analysis logic changes later, we can re-process historical raw responses.

---

# 101. Final System Flow

The complete system is:

```text
                         USER
                           │
                           ▼
                     WEB DASHBOARD
                           │
                           ▼
                    FASTAPI BACKEND
                           │
             ┌─────────────┼─────────────┐
             │             │             │
             ▼             ▼             ▼
           AUTH         PROJECTS       PROMPTS
                                         │
                                         ▼
                                PROMPT DISCOVERY
                                      AGENT
                                         │
                                         ▼
                                  PROMPT DATABASE
                                         │
                                         ▼
                                   START SCAN
                                         │
                                         ▼
                                    REDIS QUEUE
                                         │
                                         ▼
                                   SCAN WORKER
                                         │
                         ┌───────────────┼───────────────┐
                         ▼               ▼               ▼
                     ChatGPT        Perplexity        Gemini
                         │               │               │
                         └───────────────┼───────────────┘
                                         ▼
                                  RAW AI RESPONSE
                                         │
                                         ▼
                                ANALYSIS WORKER
                                         │
                  ┌──────────────────────┼─────────────────────┐
                  ▼                      ▼                     ▼
             BRAND DATA            COMPETITOR DATA        CITATIONS
                  │                      │                     │
                  └──────────────────────┼─────────────────────┘
                                         ▼
                                  METRICS ENGINE
                                         │
                                         ▼
                                OPPORTUNITY ENGINE
                                         │
                                         ▼
                                  POSTGRESQL
                                         │
                                         ▼
                                  DASHBOARD
                                         │
                                         ▼
                                  USER ACTION
                                         │
                                         ▼
                                  NEW SCAN
                                         │
                                         └──────────────►
```

---

# 102. Engineering North Star

Every feature we build should answer one of these questions:

### 1. Can we measure it?

> Is AI recommending the business?

### 2. Can we explain it?

> Why is AI recommending the competitor?

### 3. Can we act on it?

> What should the business change?

### 4. Can we prove whether it worked?

> Did AI visibility improve after the change?

If a feature doesn't contribute to one of these four questions, it should probably not be part of the initial product.

---

# 103. Final Product Architecture

```text
                   ANSWERINTEL
                        │
        ┌───────────────┼────────────────┐
        │               │                │
        ▼               ▼                ▼
    MEASURE           EXPLAIN           ACT
        │               │                │
        │               │                │
        ▼               ▼                ▼
   AI Scanning     Competitor       Opportunities
   Prompt Engine   Intelligence     Recommendations
   AI Providers    Citations        Experiments
        │               │                │
        └───────────────┼────────────────┘
                        ▼
                     RETEST
                        │
                        ▼
                  Measure Change
```

**This is the technical system we are going to build.**
