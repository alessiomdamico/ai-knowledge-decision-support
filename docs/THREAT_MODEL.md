# Threat model

**Scope:** one trusted operator, local browser, local FastAPI/SQLite, and local model inference. Treat document content and model output as untrusted. The machine owner, app code, and installed model artifacts are in the trusted computing base.

| Risk | Current control | Remaining exposure |
|---|---|---|
| Document attempts to override instructions | Only published chunks are retrieved; evidence and question are quoted as JSON strings, angle brackets are escaped to avoid literal chat delimiters, and the prompt instructs Qwen to ignore embedded instructions. The model has no tools or write access. | Prompt instructions are not a security boundary. The model can still repeat malicious content or cite it. Review the source and output. |
| Hallucinated or forged source | Exact version/chunk mapping; invalid or missing citation IDs cause abstention. Retrieval uses a similarity threshold. | Valid IDs do not imply factual entailment. The small model may answer incorrectly or decline relevant questions. |
| Browser injection and storage | React renders document text and output as text. SQL parameters separate untrusted values from queries. Loopback publishing and trusted host checks limit exposure. | No authentication, CSRF token, TLS, or per-user permissions. Anyone with local API access can inspect drafts or change publication state. |
| Sensitive corpus or prompts | No cloud inference. The cache-only default prevents runtime model downloads unless enabled. No application prompt history. | SQLite stores document text and embeddings unencrypted. Logs, filesystem access, and backups are outside the app’s controls. Only use cleared material. |
| Resource exhaustion or poisoned model artifacts | Input length, retrieval depth, and generation length are bounded; models are loaded from fixed identifiers and inference calls are serialized. | No quotas, rate limits, hard CPU deadline, or pinned checkpoint revisions. The SQLite scan and model memory use limit scale. Review model provenance and pin reviewed revisions before broader use. |

Production use would require identity, authenticated editorial roles, tenant isolation, audit logs, resource controls, model supply-chain controls, and measured grounding and security checks.
