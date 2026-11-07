# OpenRouter endpoint and price-bound probe

On 2026-11-07 at 21:09 UTC, unauthenticated, read-only requests to OpenRouter's [model endpoint-list API](https://openrouter.ai/docs/api/api-reference/endpoints/list-endpoints) returned the following point-in-time catalog observations. The selected public fields and endpoint pricing objects are retained in ignored `.local/verification/openrouter-endpoints-public.json`, SHA-256 `4c7c24a753fbeca93d17b58bd5138335e67dd4cdbbf11c29b93234323033ad49`. The snapshot contains no account credential or private account data. Endpoint counts do not establish account eligibility, availability at dispatch, or the provider that would actually be selected.

| Configured model | Listed endpoints | Catalog tokenizer label | Observed pricing keys across endpoints |
|---|---:|---|---|
| `deepseek/deepseek-v4.1-flash-1017` | 51 | DeepSeek | prompt, completion, input_cache_read, discount, overrides |
| `tencent/hy4` | 1 | Other | prompt, completion, input_cache_read, discount |
| `meta/muse-spark-open` | 7 | Other | prompt, completion, input_cache_read, discount |
| `openai/gpt-6.1-terra` | 7 | GPT | prompt, completion, input_cache_read, input_cache_write, discount, overrides, web_search |

A separate fresh endpoint read fed each endpoint's listed pricing and context/output limits to the current `qjig.pricing.upper_cost` using **assumed**, unverified 2,000 input and 6,000 output tokens. DeepSeek: 42 endpoint records produced arithmetic values and 9 were refused for a nonzero discount. Hy4: its single record was refused for a nonzero discount. Muse: 7 produced values. Terra: 7 were refused for an unsupported pricing category. This diagnostic does not reserve a call, prove actual costs, establish complete charge categories, or account for endpoint eligibility or changes between reads.

The Hy4 endpoint reported `discount: 0.5`; observed DeepSeek discounts varied by endpoint. OpenRouter states that its [discounted-model listings show discounted prices and promotions can change without notice](https://openrouter.ai/collections/discounted-models). That page does not establish the exact semantics of every endpoint JSON field or a safe undiscounted bound. The existing pricing helper correctly refuses nonzero discount rather than inferring a stable upper price. The selected Hy4 path therefore cannot currently pass its arithmetic preflight even if an input-token bound were supplied. Terra additionally exposes a `web_search` category the helper refuses; its presence is not evidence the current request would invoke web search.

This public snapshot is neither a price lock nor a guarantee of routing, tokenizer framing, provider billing, or BYOK configuration. The configured key's BYOK spend exclusion, full input-token bound, dynamic endpoint prices, all assigned work and paid-dispatch authorization remain open. No account credential or hosted model call was used in this probe.
