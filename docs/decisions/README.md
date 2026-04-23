# Architectural Decision Records (ADRs)

An Architectural Decision (AD) is a justified software design choice that addresses a functional or non-functional requirement that is architecturally significant. An Architectural Decision Record (ADR) captures a single AD and its rationale.

For more information [see](https://adr.github.io/)

> **Looking for "how does this actually work" instead of "why did we choose this"?**
> ADRs are immutable decision records frozen at the moment of acceptance. For living
> narratives and diagrams that explain how subsystems work day-to-day, see
> [`docs/design/`](../design/). Each design doc links back to the relevant ADRs.

## How to Create an ADR

1. Copy `adr-template.md` to `NNNN-title-with-dashes.md`, where NNNN indicates the next number in sequence.
   - Check for existing PR's to make sure you use the correct sequence number.
   - There is also a short form template `adr-short-template.md` for smaller decisions.
2. Edit `NNNN-title-with-dashes.md`.
   - Status must initially be `proposed`
   - List `deciders` who will sign off on the decision
   - List people who were `consulted` or `informed` about the decision
3. For each option, list the good, neutral, and bad aspects of each considered alternative.
4. Share your PR with the deciders and other interested parties.
   - The status must be updated to `accepted` once a decision is agreed and the date must also be updated.
5. Decisions can be changed later and superseded by a new ADR.

## ADR Style

ADRs record decisions, not engineering logs. Keep them short and forward-facing so a reader can grok the decision in a single pass.

- **No `## Validation` sections.** Dated phase-by-phase acceptance logs ("Phase 1 diagnosis...", "Correction to Phase 1...", "23/25 Kustomizations Ready on 2026-04-19") belong in the commit message, the PR description, or a design doc under `docs/design/`. Future readers reproduce validation from the code, not from the ADR.
- **No post-acceptance `## Amendment` sections.** If a decision needs revising after acceptance, write a new ADR that supersedes it (per step 5 above). Inline amendments re-open a record that should be closed.
- **No incident narrative in Context.** State the structural problem the decision addresses. Specific clusters, timeout values, and triggering incidents are useful in the PR that introduces the ADR but age poorly inside the ADR itself.
- **One-line option rejections.** In Considered Options, write "Rejected: \<one clause\>" rather than paragraphs re-litigating prior attempts. The decision is what was chosen; rejected alternatives get just enough to show the trade-off.
- **Forward-looking, not retrospective.** "Supersedes X because..." is fine; "The previous version of this ADR proposed..." is a sign the ADR should be superseded rather than edited in place.


## When to Create an ADR

Create ADRs for:

- Architecture patterns (deployment strategies, dependency management, GitOps workflows)
- Technology choices (middleware selection, Kubernetes operators, CLI frameworks)
- Design patterns (namespace models, credential management, ingress strategies)
- Infrastructure decisions (provider abstraction, resource allocation, caching)
- Configuration strategies (profile-based deployment, ConfigMap patterns)
- Security decisions (credential handling, certificate management)

**Rule of thumb**: If the decision could be made differently and the alternative would be reasonable, document it with an ADR.

## Templates

- **Full Template**: [`adr-template.md`](./adr-template.md) - Comprehensive template with all sections
- **Short Template**: [`adr-short-template.md`](./adr-short-template.md) - Simplified template for smaller decisions

## ADR Index

| ADR | Title | Status |
|-----|-------|--------|