# Constraint Context Design

There is value in storing project standards such as frontend colors, UI rules,
API contracts, security requirements, and LLM answer values.

The important rule: do not store them as a giant always-on Markdown prompt.
Store them as scoped policy records.

## Policy Record Shape

```json
{
  "id": "P001",
  "kind": "frontend_visual",
  "priority": "must",
  "applies_to": ["src/ui/**", "src/components/**"],
  "task_tags": ["frontend", "design", "css"],
  "compact": "UI: use approved color tokens, 8px max card radius.",
  "content": "Longer human-readable policy text."
}
```

## Retrieval Rule

Inject a policy only when:

- the edited path matches `applies_to`, and
- the task intent matches `task_tags`.

This keeps standards available without turning every prompt into a policy dump.

## Where It Fits

```text
user task + changed files
  -> policy selector
  -> compact constraint packet
  -> graph/code/doc packet
  -> LLM
```

The constraint packet should be separate from the graph packet. That lets us
cache stable policies, audit which rule affected an answer, and measure policy
token overhead independently.

## Recommended Use

- Frontend standards: scoped to UI paths and frontend/design tasks.
- Security standards: scoped to auth, token, permission, and backend paths.
- API contracts: scoped to routes and public handler code.
- Testing rules: scoped to behavior changes and touched modules.
- LLM answer values: cached global prefix or scoped answering policy.

## Anti-Pattern

Avoid a single file like:

```text
always include all colors, frontend rules, backend rules, security rules,
testing rules, answer style, repo conventions...
```

It will usually have perfect policy recall, but bad signal-to-noise and repeated
token cost.
