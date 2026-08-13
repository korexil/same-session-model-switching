# Subscription access versus API access

“I pay monthly” does not identify an authentication protocol. Before building an adapter, classify the route by how the provider authorizes machine requests.

## The three useful categories

### 1. Usage-priced API

The provider issues a key or supported OAuth credential for a documented API endpoint. This is usually the easiest gateway route: request/response formats, quotas, error codes, and automation rights are explicit.

A consumer subscription normally does not fund this API balance unless the provider explicitly says it does.

### 2. Native product subscription

The official CLI or application signs in to a consumer/product account and consumes that product's allowance. This can be ideal when you want subscription usage, but the authorization is supported for that client—not automatically for an unrelated gateway.

Examples:

- OpenAI documents ChatGPT sign-in for official Codex clients and API-key login as a separate, usage-based path.
- Gemini CLI documents Google sign-in, including Google AI Pro/Ultra quota, separately from Gemini API-key authentication.

An adapter may use this path only when the provider supports the adapter/client relationship. Possessing a local token is not proof of portability.

### 3. Fixed-price plan with a provider key

Some services sell a monthly quota and issue an API key for their own endpoint. OpenCode Go documents this shape. Economically it is a subscription; technically the gateway integration resembles an API.

This is often the simplest way to combine predictable monthly cost with a custom shell, because the provider intentionally exposes a programmatic credential. It still has its own model list, quota, privacy terms, and rate limits.

## Practical comparison

| Question | Usage API | Native product sign-in | Plan with provider key |
| --- | --- | --- | --- |
| Programmatic endpoint intended for gateways | Yes | Not necessarily | Yes |
| Credential portable to arbitrary clients | Within provider policy | No assumption allowed | Within provider policy |
| Billing | Per usage / API credits | Product subscription | Fixed plan quota |
| Easiest Anthropic-compatible routing | Usually | Only with supported connector | Usually |
| Model list controlled by | API entitlement | Official product entitlement | Plan entitlement |
| Must independently verify tools/context | Yes | Yes | Yes |

## Provider notes

### Claude / Anthropic

Claude Code can use its native account flow. Anthropic also documents LLM gateway configuration for routing Claude Code through an Anthropic-compatible gateway. A third-party model route must still use that third party's supported authentication.

### Codex / OpenAI

Official Codex clients support ChatGPT sign-in for subscription access. OpenAI separately documents API-key login as usage-based API access. Do not assume a ChatGPT/Codex login token is a generic OpenAI API credential for a custom proxy.

### Gemini / Google

Official Gemini CLI supports Google sign-in and documents quota tied to Google AI plans. API-key authentication is a separate route. A Google login working in Gemini CLI does not by itself authorize replay through a Claude Code gateway.

### OpenCode Go

OpenCode Go is a paid plan that provides an API key and provider endpoint. This makes it suitable for a gateway adapter when its terms and supported models meet your needs. It should be labelled `auth_mode: plan_api_key`, not “native OAuth subscription.”

## Honest UI labels

Expose both provider and auth mode, for example:

```text
Claude — native_subscription
Codex — native_official_client
Gemini — provider_api_key
OpenCode Go model — plan_api_key
```

Never label a route merely “subscription” or “API” if that hides which account, quota, privacy boundary, or provider actually receives the conversation.

## Official references

- Anthropic: <https://docs.anthropic.com/en/docs/claude-code/llm-gateway>
- OpenAI Codex authentication: <https://learn.chatgpt.com/docs/auth>
- Gemini CLI authentication: <https://geminicli.com/docs/get-started/authentication/>
- Gemini CLI quotas and pricing: <https://geminicli.com/docs/resources/quota-and-pricing/>
- OpenCode providers: <https://opencode.ai/docs/providers/>
- OpenCode Go: <https://opencode.ai/docs/go/>
