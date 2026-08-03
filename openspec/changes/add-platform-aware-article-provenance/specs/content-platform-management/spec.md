## ADDED Requirements

### Requirement: Content platforms are database-managed
The system SHALL maintain a database-backed content-platform registry independent from publication-driver registration. Each content platform SHALL have a unique stable code, display name, aliases, enabled state, optional description, default-generation state, creator, updater, and timestamps. Backend validation, Web selectors, MCP tools, Pipelines, and Skills SHALL discover supported content platforms from this registry rather than from hardcoded platform-code lists.

#### Scenario: An authenticated user adds a content-only platform
- **WHEN** an authenticated user creates an enabled content platform with a unique code
- **THEN** it becomes available to content-platform discovery, template assignment, and article targeting without a backend, Web, or Skill code change
- **AND** the platform is not represented as automatically publishable unless a separate publication driver and account integration exist

#### Scenario: A platform code is already referenced
- **WHEN** a content platform is referenced by an article, template, or policy version
- **THEN** its machine code cannot be renamed or physically deleted
- **AND** its display name, aliases, description, and enabled state remain editable

#### Scenario: A platform is disabled
- **WHEN** an authenticated user disables a content platform
- **THEN** it is excluded from new article, template, Pipeline, and Skill selections
- **AND** historical articles, generation contexts, and policy versions that reference it remain readable

### Requirement: Content-platform CRUD is available to authenticated users
Every authenticated user SHALL be allowed to create, read, update, and disable content platforms and to manage their policy drafts and lifecycle. Mutations SHALL use optimistic concurrency protection and SHALL append an audit-log entry identifying the actor, action, target, and before/after business values. Referenced records SHALL use disable/retire semantics instead of destructive deletion.

#### Scenario: A normal user changes platform metadata
- **WHEN** an authenticated non-admin user updates a platform display name or aliases using the current record version
- **THEN** the update succeeds
- **AND** an audit entry records the user and changed fields

#### Scenario: Two users edit the same platform concurrently
- **WHEN** a user submits an update based on a stale record version
- **THEN** the update is rejected as a conflict
- **AND** the newer database state is not overwritten

### Requirement: The generation default is data-managed
The content-platform registry SHALL support exactly one enabled default generation platform when platform-aware generation is enabled. A goal that omits its target platform SHALL resolve the current database-configured default rather than a hardcoded Skill default. Changing the default SHALL affect only new generation attempts.

#### Scenario: A goal omits the platform
- **WHEN** the Orchestrator starts a new goal without an explicit target platform
- **THEN** it resolves the enabled default platform from the registry
- **AND** the resolved platform is pinned for the complete attempt

#### Scenario: A user changes the default
- **WHEN** an authenticated user activates a different enabled platform as the generation default
- **THEN** the previous default is cleared atomically
- **AND** already saved articles and in-progress attempts retain their previously resolved platforms

### Requirement: Platform policies are immutable versioned database records
Each content platform SHALL have policy versions with `draft`, `active`, or `retired` status. A policy version SHALL contain a unique platform-scoped version label, declarative rules, source information, learned/effective dates, creator, and timestamps. Drafts MAY be edited or deleted. An active or retired version SHALL be immutable and SHALL NOT be physically deleted while referenced. At most one policy version per platform SHALL be active.

#### Scenario: A draft policy is activated
- **WHEN** an authenticated user explicitly activates a valid draft
- **THEN** it becomes the platform's sole active policy in one transaction
- **AND** the previous active policy becomes retired
- **AND** an audit entry records the activation

#### Scenario: A user edits an active policy
- **WHEN** any user attempts to change the rules of an active or retired policy version
- **THEN** the mutation is rejected
- **AND** the user must create a new draft version instead

#### Scenario: A referenced policy is deleted
- **WHEN** a policy version is referenced by a generation context
- **THEN** physical deletion is rejected
- **AND** historical policy reads remain available

### Requirement: Policy rules are declarative and staged
Each policy rule SHALL identify a stable rule code, severity (`hard` or `soft`), target field or content property, allowlisted operator, parameter value, applicable stages, source, and learned date. Rules SHALL contain data only and SHALL NOT contain executable Python, JavaScript, SQL, or arbitrary expressions. The backend SHALL execute only registered generic operators.

#### Scenario: A hard rule applies to multiple stages
- **WHEN** an active rule declares severity `hard` and applies to `write`, `review`, `save`, and `publish`
- **THEN** the MCP policy response exposes it to Writer and Verifier
- **AND** the backend enforces it at the declared save and publication boundaries

#### Scenario: A soft preference is not met
- **WHEN** content does not satisfy a `soft` rule
- **THEN** Writer and Verifier may use the rule as guidance or scoring input
- **AND** the backend does not reject article save or publication solely for that soft-rule result

#### Scenario: A policy uses an unsupported operator
- **WHEN** a draft contains an operator outside the backend allowlist
- **THEN** activation is rejected with a validation error
- **AND** no active policy state changes

### Requirement: MCP exposes dynamic platform discovery and policy lookup
MCP SHALL expose `list_content_platforms` for enabled platform codes, names, aliases, and default state, and `get_platform_content_policy` for the active or explicitly requested immutable policy version. These tools SHALL read the database registry and SHALL NOT return a Skill-maintained platform or rule list.

#### Scenario: A Skill resolves a Chinese alias
- **WHEN** the user requests a platform by an alias such as a localized display name
- **THEN** the Orchestrator resolves the alias using `list_content_platforms`
- **AND** it passes the canonical database code through the remainder of the attempt

#### Scenario: A policy version is requested explicitly
- **WHEN** an authorized MCP client requests a known historical policy version for a platform
- **THEN** the tool returns that immutable version and its structured rules
- **AND** it does not silently substitute the active version

