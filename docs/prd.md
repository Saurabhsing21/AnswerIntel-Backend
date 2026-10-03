# AnswerIntel — Product PRD

# 1. Product Vision

Build a simple AI-visibility product for startups, small businesses, and founders that answers one question:

**“When potential customers ask AI about my category, where does my business stand, who gets recommended instead, and what can I do about it?”**

The product continuously tests realistic customer questions across major AI search platforms and turns the responses into actionable business insights.

The core workflow is:

**Discover → Monitor → Understand → Fix → Re-test**

---

# 2. Target Customer

## Primary ICP

The initial customer should be:

**One business + one brand + one market + a small marketing team or founder.**

Examples:

- SaaS startup
- D2C/e-commerce brand
- Fintech startup
- Marketing agency
- Professional service business
- Local business
- Founder-led company

But the product should initially optimize for **one-brand businesses**, not large enterprises.

### Typical customer

> “I have a website, competitors, some SEO/content work, but I don't know whether ChatGPT/Perplexity/Gemini recommend me when buyers ask category questions.”

They don't need:

- 500 users
- enterprise SSO
- 20 workspaces
- huge API infrastructure
- complex approval workflows
- millions of tracked prompts

They need:

> **“Tell me where I am losing AI visibility and what I should fix this week.”**

---

# 3. The Problem We Solve

Traditional SEO answers:

> “Where does my website rank on Google?”

AI visibility introduces different questions:

> “Does AI mention my company?”

> “Does AI recommend my company?”

> “Who does AI recommend instead?”

> “How does AI describe my company?”

> “Which websites are influencing that recommendation?”

> “What does my competitor have that I don't?”

> “What should I change?”

This difference is important. Peec, for example, already tracks visibility, position, sentiment and share of voice, while also exposing competing brands and cited sources.

So **those metrics become table stakes, not our unique product.**

---

# 4. Core Product

The product should have 6 core areas.

## A. Business Setup

The user enters:

- Business name
- Website
- Category
- Country
- Primary market
- Short business description
- 3–5 competitors

Example:

```text
Brand:
Notion

Category:
Productivity software

Market:
USA

Competitors:
Coda
Asana
ClickUp
Monday
```

The system then builds the initial AI-search profile.

---

# 5. Prompt Discovery

The product should automatically generate the questions a real potential customer might ask.

Don't focus only on:

> “What is Notion?”

Instead generate commercial and problem-oriented prompts:

### Category

```text
What are the best productivity tools for startups?
```

### Comparison

```text
Notion vs ClickUp for a small startup?
```

### Alternative

```text
What are the best alternatives to Notion?
```

### Use case

```text
What is the best tool for managing startup documentation?
```

### Problem

```text
How can a small team organize its internal knowledge?
```

### Buyer intent

```text
What productivity software should a 10-person startup use?
```

### Competitor prompts

```text
ClickUp alternatives for startups
```

This is a core feature because the quality of the **prompt set** determines the usefulness of everything downstream.

Current products already recognize this: Peec emphasizes prompt discovery and organization, while Profound uses prompt-volume data to help teams select questions based on real demand.

---

# 6. AI Visibility Scan

The system runs those prompts through selected AI platforms.

For the first version:

**ChatGPT\
Perplexity\
Gemini\
Google AI Search / AI Overviews**

Later:

**Claude\
Copilot\
AI Mode\
Grok\
other emerging engines**

For each prompt we store the actual response.

Example:

```text
Prompt:
Best CRM for an early-stage startup?

AI:
1. HubSpot
2. Attio
3. Pipedrive
4. Salesforce
```

But instead of blindly treating this as a traditional ranking, we capture:

```text
Brand mentioned: YES

Recommendation: YES

Position: 2

Competitors:
HubSpot
Pipedrive
Salesforce

Sentiment:
Positive

Citations:
attio.com
g2.com
reddit.com
techcrunch.com
```

That gives us the raw evidence.

---

# 7. Visibility Dashboard

The founder should open the dashboard and immediately understand:

```text
AI VISIBILITY

Brand Mention Rate       38%
Recommendation Rate      24%
Citation Rate            31%
Share of Voice           18%

Trend                    ↑ 12%
```

Then:

### Where are we visible?

```text
ChatGPT       42%
Perplexity    31%
Gemini        28%
Google AI     19%
```

### Which competitors dominate?

```text
HubSpot       48%
Attio         41%
Pipedrive     35%
Our Brand     24%
```

### What topics are we losing?

```text
CRM for startups
CRM alternatives
Simple CRM
CRM for small teams
Affordable CRM
```

---

# 8. Competitor Intelligence

This is one of the most important parts of the product.

Instead of:

> “Your visibility is 24%.”

We should answer:

> **“Why is Attio appearing while you aren't?”**

For every important prompt:

```text
Prompt:
Best CRM for a 10-person startup?

You:
Not mentioned

Competitor:
Attio

Why Attio appeared:
• 3 third-party comparison articles
• G2 reviews
• Startup-focused publications
• Frequently cited in AI responses

Your evidence:
• Own website only
• No strong third-party comparison coverage
```

This turns a metric into an explanation.

---

# 9. Citation / Source Intelligence

This should be a first-class feature.

For every prompt we should identify:

### Owned sources

```text
yourwebsite.com
yourblog.com
docs.yoursite.com
```

### Third-party sources

```text
G2
Reddit
TechCrunch
Forbes
Capterra
industry publications
comparison websites
YouTube
etc.
```

Then show:

```text
Sources influencing competitor visibility

                 Your Brand   Competitor

G2                     ✓          ✓
Reddit                 —          ✓
Capterra               —          ✓
TechCrunch             —          ✓
Own Website            ✓          ✓
Industry Blog          —          ✓
```

This is where the product starts becoming useful for actual marketing decisions.

Recent Reddit discussions specifically describe source-level visibility—knowing whether AI is using your site, a competitor, directories, Reddit, or other third-party sources—as more actionable than a single visibility score.

---

# 10. “Why Am I Losing?” Engine

This should become our main differentiator.

For every important visibility gap, classify the likely problem.

### Type 1 — Content Gap

```text
AI recommends competitor because:

Competitor has:
"Best CRM for startups"

You don't have equivalent content.
```

### Type 2 — Citation Gap

```text
Competitor:
mentioned by 8 relevant sources

You:
mentioned by 2
```

### Type 3 — Authority Gap

```text
AI repeatedly sees competitor
in trusted third-party sources.
```

### Type 4 — Entity/Positioning Gap

```text
Your website describes you as:
"business software"

AI doesn't clearly associate you with:
"CRM for startups"
```

### Type 5 — Comparison Gap

```text
Competitor has:
Competitor vs Alternative pages
Review pages
Comparison articles
Use-case pages

You don't.
```

### Type 6 — Technical AI-readability Gap

```text
Important content is difficult
for AI crawlers to access/extract.
```

The product should not simply show:

> “Visibility: 21%”

It should say:

> **“You are losing these 7 prompts mainly because competitors have stronger third-party coverage.”**

That is the insight the founder actually needs.

---

# 11. Action Center

Every problem should become an action.

Example:

```text
🚨 HIGH IMPACT

You are losing:
"Best CRM for startups"

Competitor:
Attio

Reason:
5 third-party sources cite Attio.

Recommended actions:

□ Create "CRM for Startups" page
□ Add startup-specific use cases
□ Create competitor comparison page
□ Identify 5 third-party sources to target
□ Improve startup positioning on homepage
```

The product should organize actions by:

**Website\
Content\
Third-party presence\
Technical\
Positioning**

---

# 12. Experiment Tracking

This is another major differentiator.

The user should be able to say:

> “We updated our homepage positioning.”

Then create:

```text
Experiment #12

Change:
Updated homepage positioning

Target:
CRM for startups

Before:
24% visibility

After 14 days:
37% visibility

Competitor:
Attio

Result:
+13 percentage points
```

This creates the loop:

**Action → Re-run prompts → Compare results**

Without this, the product is just another dashboard.

---

# 13. Weekly Founder Report

The founder shouldn't need to log in every day.

Every week:

```text
YOUR AI VISIBILITY THIS WEEK

Overall:
↑ 8%

Biggest win:
You are now appearing for
"CRM for early-stage startups"

Biggest loss:
Attio gained visibility on
"simple CRM for small teams"

Important discovery:
4 competitor citations came from
startup review sites.

Recommended this week:

1. Create startup CRM comparison page
2. Improve homepage positioning
3. Target 3 missing third-party sources
```

This should be email/report/shareable.

---

# 14. Simple “Ask My AI Visibility” Interface

Later in MVP/V1, provide a chat-like interface:

```text
Why is my competitor appearing more than me?

Which 5 prompts should I focus on?

What changed this week?

What sources are helping my competitors?

What should I fix first?

Show me prompts where I rank below competitor X.
```

This makes the product feel like a **visibility analyst**, rather than a reporting database.

---

# 15. Core Dashboard Structure

The product can stay extremely simple:

```text
Dashboard
│
├── Overview
│
├── Prompts
│
├── Competitors
│
├── Sources
│
├── Opportunities
│
└── Experiments
```

That's enough for the first classic product.

---

# 16. What We DO NOT Build Initially

This is extremely important.

We should explicitly reject enterprise bloat.

## Not MVP

❌ SSO\
❌ SCIM\
❌ Enterprise RBAC\
❌ Audit logs\
❌ 20 workspaces\
❌ 100+ users\
❌ Huge APIs\
❌ White-label agency infrastructure\
❌ AI shopping analytics\
❌ AI advertising analytics\
❌ CMS publishing automation\
❌ Autonomous marketing agents\
❌ CRM integrations\
❌ 100+ AI models\
❌ Massive historical prompt datasets\
❌ Full SEO replacement\
❌ Real-time AI conversation monitoring

Profound, Semrush and other enterprise offerings already go deeply into agents, integrations, governance, APIs, multi-brand operations and large-scale tracking.

We don't need to fight them there.

---

# 17. MVP Scope

For the actual first build, I would freeze the scope at:

### One customer

```text
1 brand
1 website
1 market
3–5 competitors
```

### Prompt volume

```text
30–50 meaningful prompts
```

### AI engines

```text
ChatGPT
Perplexity
Gemini
Google AI
```

### Metrics

```text
Mention rate
Recommendation rate
Position when mentioned
Share of voice
Sentiment
Citation rate
Competitor visibility
```

### Analysis

```text
Prompt-level response
Competitors mentioned
Citations
Source categories
Visibility gaps
Competitor gaps
```

### Action layer

```text
Top opportunities
Reason for gap
Recommended action
Priority
```

### Tracking

```text
Baseline
Weekly re-scan
Before/after comparison
```

### Reporting

```text
Dashboard
Weekly email report
Shareable report
```

That is a **real SaaS product**, not just a technical demo.

---

# 18. V1 After MVP

Once the core loop works:

```text
MVP
  ↓
Better prompt discovery
  ↓
More AI engines
  ↓
Multi-country
  ↓
Local business visibility
  ↓
Website AI-readiness audit
  ↓
Google Search Console
  ↓
GA4 / AI referral measurement
  ↓
Content recommendations
  ↓
Agency workspaces
  ↓
API / MCP
```

And only much later:

```text
Agents
CMS publishing
AI shopping
AI advertising
Enterprise governance
```

---

# 19. Our Product Positioning

I would **not** position it as:

> “AI Rank Tracker”

or

> “Track your ChatGPT ranking.”

Instead:

> **AI Visibility Intelligence for Businesses**

And the product promise:

> **Know when AI recommends you, understand why it recommends your competitors, and know what to do next.**

The internal product philosophy becomes:

```text
          ┌──────────────┐
          │   MONITOR    │
          │ What AI says │
          └──────┬───────┘
                 ↓
          ┌──────────────┐
          │   EXPLAIN    │
          │ Why it says  │
          └──────┬───────┘
                 ↓
          ┌──────────────┐
          │     ACT      │
          │ What to fix  │
          └──────┬───────┘
                 ↓
          ┌──────────────┐
          │   RETEST     │
          │ Did it work? │
          └──────┬───────┘
                 │
                 └──────────→ MONITOR
```

---

# 20. The One-Sentence Definition

**We are building a lightweight AI-visibility intelligence product for founders and small businesses that continuously measures how AI assistants recommend their brand, identifies why competitors appear instead, and turns those gaps into specific actions that can be re-tested over time.**
