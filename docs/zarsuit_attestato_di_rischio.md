# Zarsuit Risk Attestation Contract

> File for Codex / coding agents.
>
> Scope: define the standard file exchanged between Zarsuit and `il_segretario` for risk assessment, context request, correction, and routing directives.
>
> This document only describes Zarsuit-side responsibilities and the shared handoff contract. It must not define the internal behavior of `il_segretario` inside the vault.

---

## 1. Purpose

Zarsuit and `il_segretario` exchange information through a standard risk attestation file.

The file is created by Zarsuit and corrected by `il_segretario`.

The risk attestation exists to:

1. preserve the full original user request;
2. declare which private/profile/vault knowledge Zarsuit believes it needs;
3. estimate the sensitivity risk of the request;
4. allow `il_segretario` to correct the assessment;
5. allow `il_segretario` to provide only filtered, generalized, ranged, tokenized, or redacted context back to Zarsuit;
6. allow `il_segretario` to control whether Zarsuit may answer the user directly or must return its output to `il_segretario`.

Zarsuit must never assume that a user-facing answer is allowed just because it received context back from `il_segretario`.

---

## 2. Boundary rule

The risk attestation is a boundary object.

Zarsuit may:

- create the initial attestation;
- include the complete original user request;
- request the data categories it needs;
- estimate sensitivity and risk;
- receive a corrected copy from `il_segretario`;
- use only the approved context projection returned by `il_segretario`;
- follow the routing directive contained in the corrected attestation.

Zarsuit must not:

- directly read private vault data for this flow;
- directly access Gmail, Calendar, or other private tools through this contract;
- infer that denied data may be reconstructed from other sources;
- send output to the user when the corrected attestation blocks direct delivery;
- modify the internal vault copy kept by `il_segretario`;
- define what `il_segretario` does after receiving Zarsuit output.

`il_segretario` is the authority for correction, filtering, and routing decisions.

---

## 3. Required lifecycle

### 3.1 Zarsuit creates initial attestation

When a request may require private profile data, vault knowledge, or user-sensitive context, Zarsuit must create an attestation.

The attestation must include the complete original user request, not only a summary.

### 3.2 Zarsuit sends attestation to `il_segretario`

Zarsuit sends the attestation as a request for correction and context projection.

### 3.3 Zarsuit receives corrected attestation

The corrected attestation may contain:

- corrected risk level;
- approved filtered context;
- denied context;
- routing directive;
- direct-user-delivery permission;
- requirement to return the Zarsuit output to `il_segretario` instead of the user.

### 3.4 Zarsuit executes only within the corrected attestation

Zarsuit may only use `approved_context_projection` as input.

Zarsuit must not use unapproved assumptions to recover more specific private information.

### 3.5 Zarsuit routes the result according to the directive

If direct user delivery is allowed, Zarsuit may produce a user answer.

If direct user delivery is blocked, Zarsuit must not answer the user and must route its task output as instructed.

---

## 4. Standard attestation schema

The recommended machine-readable representation is YAML inside a `.md` file.

Use this as the canonical structure.

```yaml
risk_attestation:
  schema_version: "1.0"
  attestation_id: ""
  created_at: ""
  created_by: "zarsuit"
  status: "draft | corrected_by_secretary | completed_by_zarsuit"

  original_user_request:
    full_text: ""
    detected_intent: ""
    user_expected_output: ""

  zarsuit_context_request:
    requested_private_data:
      - field: ""
        reason_needed: ""
        estimated_sensitivity: "low | medium | high | critical"
        requested_granularity: "exact | range | generalized | tokenized | yes_no"

    requested_vault_knowledge:
      - field: ""
        reason_needed: ""
        estimated_sensitivity: "public | internal | private | sensitive"
        requested_granularity: "plain | generalized | summarized | tokenized | redacted"

  zarsuit_initial_risk_assessment:
    level: "low | medium | high | critical"
    rationale: ""
    risks:
      - "personal_data_exposure"
      - "confidential_data_exposure"
      - "financial_data_exposure"
      - "location_exposure"
      - "profile_inference"
      - "unverified_output"
      - "other"
    notes: ""

  secretary_review:
    corrected_risk_level: "low | medium | high | critical"
    corrected_notes: ""

    approved_context_projection:
      - field: ""
        value: ""
        sensitivity: "low | medium | high | critical"
        release_mode: "plain | generalized | range_only | tokenized | redacted"
        notes: ""

    denied_context:
      - field: ""
        reason: ""

  secretary_routing_directive:
    zarsuit_may_answer_user_directly: false
    zarsuit_must_return_output_to_secretary: false
    user_delivery_blocked_until_secretary_approval: false
    task_output_destination: "user | secretary"
    reason: ""

  zarsuit_execution:
    allowed_to_execute: false
    allowed_inputs_only: "secretary_approved_context_projection"
    execution_notes: ""

  zarsuit_task_output_for_secretary:
    status: "not_required | pending | completed"
    content: ""

  audit:
    secretary_keeps_vault_copy: true
    corrected_copy_returned_to_zarsuit: true
    final_user_delivery_out_of_scope_for_this_contract: true
    notes: ""
```

---

## 5. Required fields

Codex must enforce that the following fields exist in every attestation:

```yaml
risk_attestation.schema_version
risk_attestation.attestation_id
risk_attestation.created_at
risk_attestation.created_by
risk_attestation.original_user_request.full_text
risk_attestation.zarsuit_context_request
risk_attestation.zarsuit_initial_risk_assessment.level
risk_attestation.secretary_review
risk_attestation.secretary_routing_directive.zarsuit_may_answer_user_directly
risk_attestation.secretary_routing_directive.zarsuit_must_return_output_to_secretary
risk_attestation.secretary_routing_directive.task_output_destination
risk_attestation.zarsuit_execution.allowed_inputs_only
risk_attestation.audit.final_user_delivery_out_of_scope_for_this_contract
```

The most important required field is:

```yaml
risk_attestation.original_user_request.full_text
```

The full user request is mandatory because `il_segretario` must evaluate the real request, not only Zarsuit's summary.

---

## 6. Sensitivity levels

Use only these sensitivity levels:

```text
low
medium
high
critical
```

### Low

Public or non-sensitive context.

Example:

```text
Current car model: Golf 7
```

### Medium

General personal context that can still identify lifestyle, location, or routine if combined with other data.

Example:

```text
User lives in Torino / Northern Italy
```

### High

Sensitive private context, especially economic, financial, personal, or profile-derived context.

Example:

```text
Annual income range: 20k-40k
```

### Critical

Credentials, secrets, exact private documents, highly sensitive personal content, or data that must not be exposed to Zarsuit except through a heavily constrained projection.

---

## 7. Release modes

Use only these release modes:

```text
plain
generalized
range_only
tokenized
redacted
summarized
yes_no
```

Meaning:

- `plain`: value may be passed as-is;
- `generalized`: exact value is replaced with broader context;
- `range_only`: exact number is replaced with a range;
- `tokenized`: stable token or label replaces the original value;
- `redacted`: field is acknowledged but value is not provided;
- `summarized`: detailed knowledge is compressed into a summary;
- `yes_no`: only a boolean answer is provided.

Zarsuit must treat these modes as hard limits.

---

## 8. Routing directive rules

The routing directive controls delivery.

### Direct user answer allowed

```yaml
secretary_routing_directive:
  zarsuit_may_answer_user_directly: true
  zarsuit_must_return_output_to_secretary: false
  user_delivery_blocked_until_secretary_approval: false
  task_output_destination: "user"
```

Zarsuit may answer the user using only approved context.

### Return output to `il_segretario`

```yaml
secretary_routing_directive:
  zarsuit_may_answer_user_directly: false
  zarsuit_must_return_output_to_secretary: true
  user_delivery_blocked_until_secretary_approval: true
  task_output_destination: "secretary"
```

Zarsuit must execute the task, but must return its non-final task output to `il_segretario` instead of sending it to the user.

This is required when the context provided to Zarsuit is generic and the final answer needs private refinement by `il_segretario`.

---

## 9. Hard safety invariant

Implement this invariant exactly:

```text
If zarsuit_must_return_output_to_secretary is true,
then zarsuit_may_answer_user_directly must be false,
and task_output_destination must be secretary.
```

Equivalent pseudocode:

```python
if attestation.secretary_routing_directive.zarsuit_must_return_output_to_secretary:
    assert attestation.secretary_routing_directive.zarsuit_may_answer_user_directly is False
    assert attestation.secretary_routing_directive.task_output_destination == "secretary"
```

If the corrected attestation violates this invariant, Zarsuit must fail closed and not answer the user.

---

## 10. Example: car recommendation request

User asks:

```text
Quale macchina potrei comprare in base alla mia persona?
```

Zarsuit initial attestation:

```yaml
risk_attestation:
  schema_version: "1.0"
  attestation_id: "risk-car-choice-001"
  created_at: ""
  created_by: "zarsuit"
  status: "draft"

  original_user_request:
    full_text: "Quale macchina potrei comprare in base alla mia persona?"
    detected_intent: "personalized_car_recommendation"
    user_expected_output: "A personalized car recommendation based on the user's profile."

  zarsuit_context_request:
    requested_private_data:
      - field: "current_car"
        reason_needed: "Understand the user's current reference point."
        estimated_sensitivity: "low"
        requested_granularity: "exact"
      - field: "user_location"
        reason_needed: "Account for local climate, city use, roads, availability, and practical constraints."
        estimated_sensitivity: "medium"
        requested_granularity: "generalized"
      - field: "annual_income_or_budget"
        reason_needed: "Avoid suggesting cars outside realistic economic range."
        estimated_sensitivity: "high"
        requested_granularity: "range"

    requested_vault_knowledge:
      - field: "known_preferences"
        reason_needed: "Use non-private or approved preference knowledge if available."
        estimated_sensitivity: "private"
        requested_granularity: "summarized"

  zarsuit_initial_risk_assessment:
    level: "high"
    rationale: "The request requires personal, location, and economic context."
    risks:
      - "financial_data_exposure"
      - "location_exposure"
      - "profile_inference"
    notes: "Full user request included for secretary review."
```

Corrected attestation excerpt returned to Zarsuit:

```yaml
secretary_review:
  corrected_risk_level: "high"
  corrected_notes: "Use only generalized context."

  approved_context_projection:
    - field: "current_car"
      value: "Golf 7"
      sensitivity: "low"
      release_mode: "plain"
      notes: "Non-sensitive enough for Zarsuit-side reasoning."

    - field: "user_location"
      value: "Torino / Northern Italy"
      sensitivity: "medium"
      release_mode: "generalized"
      notes: "Do not request exact address or routines."

    - field: "annual_income_or_budget"
      value: "20k-40k annual income range"
      sensitivity: "high"
      release_mode: "range_only"
      notes: "Use only as broad affordability signal."

secretary_routing_directive:
  zarsuit_may_answer_user_directly: false
  zarsuit_must_return_output_to_secretary: true
  user_delivery_blocked_until_secretary_approval: true
  task_output_destination: "secretary"
  reason: "The projected data is intentionally generic. Zarsuit output must be treated as a non-final draft for private refinement."

zarsuit_execution:
  allowed_to_execute: true
  allowed_inputs_only: "secretary_approved_context_projection"
  execution_notes: "Produce a non-final analytical draft only."
```

---

## 11. Implementation requirements for Codex

Codex should implement or adapt code so that:

1. Zarsuit can generate a risk attestation from a user request.
2. The full original user request is always included.
3. The attestation can represent both private-data requests and vault-knowledge requests.
4. The corrected copy can be parsed by Zarsuit.
5. Zarsuit only reads `approved_context_projection` from the corrected attestation.
6. Routing directives are enforced before any user-facing output.
7. The system fails closed when routing fields are missing, invalid, or contradictory.
8. The second-flow routing invariant is enforced.
9. The internal behavior of `il_segretario` is not implemented here.

---

## 12. Suggested tests

Add tests for:

- attestation creation includes `original_user_request.full_text`;
- missing full request fails validation;
- corrected attestation with approved context can be parsed;
- denied context is not exposed to Zarsuit execution input;
- `zarsuit_must_return_output_to_secretary: true` blocks user delivery;
- contradictory routing directive fails closed;
- Zarsuit execution uses only `approved_context_projection`;
- final user delivery after the Segretario receives output is out of scope.

---

## 13. Done definition

This task is complete when:

- a standard risk attestation structure exists;
- Zarsuit can create it with the complete user request;
- Zarsuit can parse the corrected copy;
- Zarsuit can enforce routing directives;
- Zarsuit cannot answer the user when the corrected attestation requires output return to `il_segretario`;
- tests cover the required invariants;
- no internal `il_segretario` vault behavior is implemented in this Zarsuit-side task.
