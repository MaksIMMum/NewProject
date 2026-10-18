# 6. LLM Agenda Parsing with Amazon Bedrock

Date: 2026-10-18

## Status

Accepted

## Context

Real meeting agendas do not originate as structured forms. They arrive as emails from managers, quick messages in team chats, or rough informal notes (e.g., *"Пн 10:00, синк по прайсингу, 45 хв. 1) нові тарифи Pro — Олена, 15 хв 2) фідбек від клієнтів — Taras 3) що робимо з річною знижкою. Taras до п'ятниці збирає порівняння з конкурентами."*).

Users need a way to turn unstructured text into structured agendas (topics, owners, durations) and actionable items (tasks, assignees, due dates) without manual data entry.

However, several architectural constraints apply:
1. **No NAT Gateway in the VPC**: The existing backend Lambda runs in a private VPC subnet to access Aurora Serverless v2 PostgreSQL securely without a NAT Gateway or public IP, saving over $32/month.
2. **Cost Control**: LLM inference costs money per token. The architecture must enforce strict budget caps, user authentication, payload length limits, and client cancellation.
3. **Untrusted External Data**: Text pasted by users is untrusted data and can contain adversarial prompt injection attempts designed to extract system instructions or manipulate data.
4. **Reliability & Human Agency**: LLM models are non-deterministic and can hallucinate or fail. The application must ensure that the user remains in complete control and that core functionality never depends on LLM availability.

## Decision

1. **Foundation Model & Tool-Use**:
   - We use **Anthropic Claude Haiku** (`us.anthropic.claude-haiku-4-5-20251001-v1:0`) via Amazon Bedrock through the Anthropic Messages API.
   - We enforce structured output via Bedrock tool use (`record_agenda`) and validate all extracted fields against a strict Pydantic schema (`ParsedAgenda`).
   - If the model returns malformed JSON or invalid schema values, the parser automatically sends the validation error back for one retry.

2. **Serverless Infrastructure Outside the VPC**:
   - The parser function (`agenda-parser`) is deployed as an AWS Lambda function running the backend container image **outside the VPC**.
   - It is exposed directly via a **Lambda Function URL** with CORS enabled.
   - Because the parser only converts text to JSON and never interacts with the database, running outside the VPC allows it to reach Amazon Bedrock over the AWS public backbone at zero networking cost, without needing a VPC endpoint or NAT Gateway.

3. **Authentication & Defense-in-Depth**:
   - The Function URL verifies Cognito JWT ID tokens in code before invoking Bedrock, preventing unauthenticated access and wallet-draining abuse.
   - Payloads larger than 10,000 characters are rejected with `413 Payload Too Large`.
   - An AWS Budgets alarm is configured at **$5.00/month**, notifying engineering via email if spend approaches the limit.

4. **Human-in-the-Loop: Model Suggests, Human Decides**:
   - The model **never writes directly to the database**.
   - The frontend parses the text and displays a pre-filled editable form with subtle visual badges marking AI-suggested fields.
   - Any manual edit clears the badge. The user can add missing topics, delete hallucinated tasks, or discard the parse entirely.
   - Saving goes through the standard authenticated `POST /meetings/{id}/agenda` endpoint on the core VPC API, saving the final user-approved agenda alongside the AI suggestion metadata (`model`, `prompt_version`, `raw_suggestion`) for quality tracking.

5. **Client-Side Abort**:
   - The frontend integrates `AbortController`. If parsing takes too long or the user cancels, the network request is aborted immediately.

## Alternatives Considered

1. **Calling Bedrock from the VPC API via a VPC Interface Endpoint (`bedrock-runtime`)**:
   - *Rejected*: AWS VPC Interface Endpoints cost ~$7.30/month per availability zone ($14.60/month across two subnets) regardless of traffic volume. For an intermittent feature, this would exceed the monthly LLM inference budget by an order of magnitude. In addition, holding VPC database connections open during 2–5s LLM calls causes connection pool starvation.

2. **Direct Anthropic Claude API instead of Amazon Bedrock**:
   - *Rejected*: The external Anthropic API requires provisioning, rotating, and securing external API keys in secrets storage. Amazon Bedrock uses native AWS IAM roles (`bedrock:InvokeModel`) with temporary credentials, integrates natively into AWS Budgets and CloudWatch, and keeps data and billing consolidated in AWS.

3. **Calling Bedrock Directly from the Browser via Cognito Identity Pool**:
   - *Rejected*: Browser SDK calls require granting direct IAM model invocation permissions to client identities. This prevents server-side prompt enforcement, allows arbitrary prompts to be sent to Bedrock under our account, and makes per-user rate limiting impossible.

4. **Regular Expression or Heuristic Parser**:
   - *Rejected*: Agendas vary drastically in formatting, language (e.g. Ukrainian colloquialisms), and date expressions ("до п'ятниці", "next Tuesday after lunch"). RegEx parsers are brittle, cannot resolve contextual relative dates, and produce high error rates.

5. **Larger LLM Models (Claude Sonnet 4.5 / Claude Opus 5.5)**:
   - *Rejected*: Haiku provides sub-3s latency and costs ~$0.00028 per parse (approx $0.10/$0.50 per 1M tokens), which is 10x to 40x cheaper than Sonnet or Opus while delivering near-perfect extraction on structured agenda schemas.

## Consequences

- **Cost**: Each agenda parse costs approximately **$0.00028** (~1,250 input tokens, ~300 output tokens). Even at 2,400 parses per month across multiple organizations, the total cost is under $0.70/month.
- **Observability**: Every parse emits a structured JSON log line in CloudWatch with `event="agenda_parsed"`, `user`, `model`, `prompt_version`, `input_tokens`, `output_tokens`, `latency_ms`, and `cost_usd`.
- **System Resilience**: If Amazon Bedrock experiences downtime or rate limits, the core application continues to function normally. Users can still create meetings and type agendas manually.
- **Auditability**: Saving the original AI suggestion alongside the user-edited agenda provides an evaluation dataset to benchmark future prompt versions (`agenda-v2`).
