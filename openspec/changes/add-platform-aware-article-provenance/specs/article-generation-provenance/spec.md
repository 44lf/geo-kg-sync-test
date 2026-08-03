## ADDED Requirements

### Requirement: A successfully generated article can have one immutable context
The system SHALL support at most one immutable `article_generation_contexts` record for each successfully saved generated Article. The context SHALL describe the successful generation that produced the saved Article; failed model calls, rejected drafts, and unsuccessful attempts SHALL remain in existing run/task logs rather than creating Article contexts.

#### Scenario: A successful generated save commits
- **WHEN** a valid MCP or platform-configured Pipeline save creates a generated Article
- **THEN** the Article and its context commit in one transaction
- **AND** exactly one context is associated with the Article

#### Scenario: Context creation fails
- **WHEN** context validation or persistence fails
- **THEN** neither the Article nor a partial context remains committed

#### Scenario: A generation attempt fails before Article save
- **WHEN** Writer, model invocation, verification, or save validation fails without saving an Article
- **THEN** no Article context is created
- **AND** the failure remains observable through the existing execution logs

### Requirement: Context stores generation facts without duplicating current Article state
The generation context SHALL store the generation entrypoint, authoritative template identity and immutable template snapshots, application-controlled effective prompt and SHA-256, immutable policy-version ID, optional authoritative question snapshot, model label, and creation time. It SHALL NOT duplicate `articles.target_platform_code`, the full platform-policy JSON, generation parameters, or evidence references. The original generation platform SHALL be derived from the referenced immutable policy version.

#### Scenario: Context is created
- **WHEN** a generated Article is saved with complete provenance
- **THEN** the context contains `article_id`, `entrypoint`, template ID/name/content/update-time snapshots, effective prompt/hash, `platform_policy_version_id`, question snapshot when available, model label, and creation time
- **AND** it contains no duplicated target-platform field or policy snapshot

#### Scenario: Current Article platform is manually changed
- **WHEN** a user retargets an Article after generation
- **THEN** the context and referenced policy version remain unchanged
- **AND** the original generation platform remains derivable

### Requirement: Authoritative mutable sources are snapshotted
The server SHALL build template and question snapshots from authoritative database records rather than trusting client-supplied copies. Because templates and questions may be edited later, source fingerprints supplied from MCP discovery SHALL be recomputed at save. A mismatch SHALL reject the save rather than combining an old effective prompt with newer source data.

#### Scenario: A template is edited after discovery
- **WHEN** Writer saves with a template fingerprint that no longer matches the authoritative template
- **THEN** the save is rejected as a source conflict
- **AND** no Article or context is committed

#### Scenario: A template changes after successful save
- **WHEN** an operator later edits or disables the source template
- **THEN** the context's template name, content, and update-time snapshots remain unchanged

#### Scenario: A question is available
- **WHEN** a save references an authoritative question item
- **THEN** the context stores the server-derived question identifier, category, and text
- **AND** a stale question fingerprint causes a source conflict

### Requirement: Policy history is referenced, not copied
The context SHALL reference one immutable activated or retired policy-version row. The referenced policy SHALL belong to the platform resolved for the generation attempt. Active and retired policy versions referenced by contexts SHALL be protected from mutation and physical deletion.

#### Scenario: A policy version is pinned
- **WHEN** an attempt saves against an immutable policy version
- **THEN** the context stores its database ID
- **AND** the policy's platform matches the attempt's Article target at initial save

#### Scenario: A new policy becomes active later
- **WHEN** the platform activates a newer policy version
- **THEN** existing contexts continue to reference the old immutable version
- **AND** no per-Article policy JSON rewrite occurs

### Requirement: The application-controlled effective prompt is preserved
The context SHALL preserve the complete application-controlled prompt or normalized message sequence that GEO assembled and supplied to Writer for the successful attempt, together with a SHA-256 of the exact stored UTF-8 bytes. Documentation and API fields SHALL state that this does not include hidden provider instructions, model-internal context, or host instructions that GEO cannot observe.

#### Scenario: An effective prompt is saved
- **WHEN** a generated article is committed
- **THEN** the stored prompt represents the successful application's template, policy guidance, question context, and rewrite context
- **AND** its SHA-256 matches the exact stored bytes

#### Scenario: The stored prompt is altered
- **WHEN** the effective-prompt bytes differ from the saved bytes
- **THEN** recomputing SHA-256 produces a different value
- **AND** the provenance state does not report complete

### Requirement: Sensitive and oversized context is rejected
The server SHALL enforce a documented maximum effective-prompt size and SHALL reject recognizable authorization material or configured secrets in every persisted context text field. Validation SHALL cover the effective prompt, template name/content snapshots, question snapshot, and model label, including dynamically configured model credentials. Errors and logs SHALL not echo secret values or full prompt bodies.

#### Scenario: Effective prompt exceeds the maximum
- **WHEN** the effective prompt exceeds the configured UTF-8 byte limit
- **THEN** the generated save is rejected before commit

#### Scenario: Context metadata contains a secret
- **WHEN** a prompt, template snapshot, question snapshot, or model label contains a configured secret, API key, authorization header, cookie, bearer token, or recognizable JWT
- **THEN** the save is rejected
- **AND** neither persistence nor error output exposes the sensitive value

### Requirement: Reads distinguish current target from generation history
Article list and detail responses SHALL expose the current target platform and compact provenance state. Detail responses SHALL additionally expose the generation platform derived from the policy version and a computed indication when it differs from the current target. Full template/prompt/question context SHALL be returned only when explicitly requested.

#### Scenario: Current and generation platforms match
- **WHEN** a generated Article has not been retargeted
- **THEN** its current and generation platforms are equal
- **AND** the UI may present one platform label

#### Scenario: Current and generation platforms differ
- **WHEN** a generated Article has been manually retargeted
- **THEN** detail reads expose both platforms
- **AND** they report that the target changed after generation
- **AND** the immutable context remains complete

#### Scenario: A list is requested
- **WHEN** a client lists Articles
- **THEN** the response omits full template, effective-prompt, and question snapshots

#### Scenario: Full context is requested
- **WHEN** an authorized owner, administrator, or administrator-grade MCP service client explicitly requests full context
- **THEN** the response includes the immutable template, effective-prompt, policy-version reference, question, and model data

### Requirement: Historical and compatibility Articles remain readable
The migration SHALL NOT create contexts for historical Articles. Manual Articles and compatibility-generated Articles that lack complete context SHALL remain readable. The system SHALL report `complete`, `incomplete`, or `not_recorded` without inferring historical generation facts.

#### Scenario: A historical Article is read
- **WHEN** an Article predates the capability and has no target or context
- **THEN** it reports `not_recorded`
- **AND** no current template, platform, or policy is presented as its generation history

#### Scenario: A compatibility caller omits context
- **WHEN** an older generation caller saves during the compatibility window without complete context
- **THEN** the save MAY remain supported
- **AND** the Article reports `incomplete`

