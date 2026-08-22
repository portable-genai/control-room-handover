# FAQ index

Answers to the questions different teams ask when evaluating, adopting, or reviewing this
repository as a common base for an operations control-room scorecard and shift handover. Each file
is written for a specific audience; skim the one that matches your role.

| FAQ | For | Answers |
|---|---|---|
| [security-faq.md](security-faq.md) | AppSec / security review | what is processed, server-side identity, the exposure guard, secrets, supply chain, the audit chain's honest limits, what is out of scope |
| [portability-faq.md](portability-faq.md) | Architecture / cloud / exit planning | the no-lock-in claim, the three profiles, the executable portability proof, the sovereign exit, residency |
| [features-faq.md](features-faq.md) | Product / operations / delivery | what the agent produces, what is deterministic vs narrated, and the boundary with sibling catalog systems |
| [adoption-faq.md](adoption-faq.md) | Engineering leads forking the repo | rename, upstream fixes, extension points, adding a feed, whether the demo rots |
| [compliance-faq.md](compliance-faq.md) | Compliance / operational risk / model risk | regulatory posture, maker-checker, residency, auditability, model-risk evidence |

These FAQs deliberately do **not** re-document capabilities owned by sibling systems in the
catalog. Where a concern belongs to another repo (the guardrail gateway, the human-review console,
the eval platform, the upstream worklist publishers), the FAQ points at it and explains the
boundary rather than duplicating it. See [features-faq.md](features-faq.md) for the full "what this
repo owns vs what it integrates" map, and [`../../COMPLIANCE.md`](../../COMPLIANCE.md) for the row
by row status of each integration.
