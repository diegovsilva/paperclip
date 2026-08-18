---
name: DataCorp AI
description: Multi-agent AI data company for pipelines, analytics, governance, automation, and ML across cloud and open-source platforms
slug: datacorp-ai
schema: agentcompanies/v1
version: 2.0.0
license: MIT
authors:
  - name: DataCorp AI Operators
goals:
  - Build reliable data pipelines with clear ownership and handoffs
  - Deliver governed analytics and machine learning assets with strong quality controls
  - Operate across GCP, AWS, Azure, and open-source stacks without lock-in
includes:
  - teams/platform/TEAM.md
  - teams/architecture/TEAM.md
  - teams/delivery/TEAM.md
---

DataCorp AI is a complete AI-native data company designed for multi-agent execution.

The company operates as a hub-and-spoke system with delegated execution. The Data Lead receives goals from the board, turns them into scoped work, and delegates to specialist leads. Those specialists can further delegate to downstream experts when delivery requires design, platform work, validation, observability, or automation.

Operating model:

- The Data Lead owns intake, prioritization, approvals, budget control, and cross-team coordination.
- The Platform team groups runtime, infrastructure, and observability ownership under the Cloud Engineer.
- The Architecture team groups canonical modeling and governance ownership under the Data Architect.
- The Delivery team groups pipeline implementation, analytics, ML, automation, and validation execution under the Senior Data Engineer.
- The Data Architect turns business intent into canonical models, contracts, and technical direction.
- The Cloud Engineer owns runtime platforms, environments, infrastructure, and deployment reliability.
- The N8N Engineer owns business workflow automation and operational integrations.
- Delivery specialists implement, validate, govern, and monitor data products until they are production ready.

Definition of done:

- Work has a clear owner and reporting path.
- Data contracts, tests, and operational checks are updated together.
- Approval-gated changes are escalated before risky execution.
- Handoffs leave durable artifacts for the next agent, not just transient status.
