# Local tokenizer probe, 2026-11-07

This exploratory probe concerns the synthetic campaign under `.local/verification/full-factorial-synthetic-jdzwm67v/archives`. It is not a hosted call or an input-token upper bound. It does not establish that OpenRouter or its chosen upstream endpoint uses these artifacts or chat templates.

## Inputs and method

- DeepSeek publisher repository `deepseek-ai/DeepSeek-V4.1-Flash-1017`, revision `1bae0e1088993b9b82de08f59de5be5a34e42170`, `tokenizer.json`, SHA-256 `c90dfa01249db1be4245780a052ede752e1361c612ac6d08e2bdada7d599476b`: [model files](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/tree/1bae0e1088993b9b82de08f59de5be5a34e42170), [encoding reference](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/blob/1bae0e1088993b9b82de08f59de5be5a34e42170/encoding/README.md).
- Tencent publisher repository `tencent/Hy4-preview`, revision `705d81ee51566a186d645b74c974d642ef2828fe`, `tokenizer.json`, SHA-256 `ff67615de6e6ee073a20bd1fe3a776053e821573f4ae566aeb8e9d43de801201`: [model files](https://huggingface.co/tencent/Hy4-preview/tree/705d81ee51566a186d645b74c974d642ef2828fe), [chat template](https://huggingface.co/tencent/Hy4-preview/blob/705d81ee51566a186d645b74c974d642ef2828fe/chat_template.jinja). The equivalence of this published artifact to the `tencent/hy4` hosted endpoint is not established.
- Both artifacts were downloaded without credentials into ignored `.local/verification/tokenizers/`; no model weights or remote code were loaded. The installed `tokenizers` 0.23.3 library loaded each JSON and round-tripped three small ASCII, Unicode and special-token-like samples.
- Read request events from all 105 synthetic run archives, and tokenize each recorded `prompt` as text with `add_special_tokens=False`. This deliberately excludes message framing, system content added by an upstream provider, tool framing, routing metadata, and response tokens. The SHA-256 of sorted request input identity hashes joined by newline was `dad2a6a983d19e625fd8841d8d5275ce486c252abc5f2f9bbc223cdc9abd3b5b`. Duplicate hashes are retained. There were 228 request events, including 39 of 42 possible reviews; other stages were not exercised by this draft.

| Synthetic request stage | Count | Maximum prompt UTF-8 bytes | DeepSeek maximum prompt-only tokens | Hy4-preview maximum prompt-only tokens |
|---|---:|---:|---:|---:|
| direct_initial | 63 | 1,808 | 571 | 567 |
| judge_negative | 42 | 754 | 169 | 166 |
| judge_positive | 42 | 755 | 169 | 166 |
| plan_review | 39 | 2,701 | 926 | 914 |
| planner | 42 | 2,357 | 723 | 707 |

These maxima describe only these recorded synthetic prompts, not unexercised reviews, followups, escalations, future planner output or the assigned real campaign. No prompt texts, labels, credentials or raw provider account data are reproduced here. The local draft is not independent outcome evidence.

## Remaining gate

A safe paid-call reservation must cover the actual provider's complete framed input, its selected model and additional billed categories, and all assigned work. Local tokenizer counts cannot prove an upstream provider's message formatting or accounting, nor cap unobserved future prompts. Obtain a defensible, provider-specific bound and bind it to the exact wire request and current pricing before opening hosted dispatch. The independent BYOK billing uncertainty remains unresolved.
