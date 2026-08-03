## ADDED Requirements

### Requirement: An article has one current content target
The system SHALL represent an article's current intended content platform with nullable `articles.target_platform_code` referencing the database content-platform registry. The field SHALL answer where the article is currently intended to be used and SHALL remain distinct from actual publication destinations recorded by publication tasks and records. Historical articles SHALL remain null unless a user explicitly assigns a platform.

#### Scenario: Historical articles are migrated
- **WHEN** the target-platform field is added
- **THEN** all existing articles retain `NULL`
- **AND** the migration does not infer a target from templates, text, accounts, or publication history

#### Scenario: A generated article is saved
- **WHEN** an upgraded MCP or platform-configured Pipeline saves a generated article
- **THEN** it records the attempt's resolved enabled target platform on the Article

#### Scenario: A manual article is created
- **WHEN** a user creates a manual article
- **THEN** the user may choose an enabled target platform or leave it unclassified
- **AND** no generation context is manufactured

### Requirement: The Web UI displays and edits the current target platform
Article list items and article detail SHALL display the current target platform using database-provided names. An authenticated user with article edit access SHALL be able to change the platform using a selector populated from enabled database platforms. A platform change SHALL preserve historical generation context, return the article to pending review, and affect only future validation and publication.

#### Scenario: A user changes a generated article's platform
- **WHEN** an editable Article generated for Toutiao is manually retargeted to Xiaohongshu
- **THEN** `articles.target_platform_code` changes to Xiaohongshu
- **AND** the immutable generation context continues to identify the original generation-policy version
- **AND** the article returns to pending review
- **AND** existing completed publication records are unchanged

#### Scenario: Current and generation platforms differ
- **WHEN** an Article's current target differs from the platform of its generation-policy version
- **THEN** the detail UI displays both values and identifies that the target was manually changed
- **AND** the provenance record is not rewritten or falsely marked corrupt

#### Scenario: A non-terminal publication exists
- **WHEN** a user attempts to retarget an Article that has a non-terminal publication task or record
- **THEN** the update is rejected with instructions to cancel or finish the in-flight publication first

### Requirement: Platform context is propagated end to end
The Orchestrator, template selection, Writer, Verifier, save boundary, and platform-configured Pipeline nodes SHALL use one resolved content-platform code and one pinned policy version for a generation attempt. Existing platform-less Pipeline configurations and compatibility callers MAY retain generic behavior during the migration window.

#### Scenario: Writer and Verifier receive one platform context
- **WHEN** an Orchestrator starts a new platform-aware attempt
- **THEN** it passes the same canonical platform code and policy-version ID to Writer and Verifier
- **AND** neither component substitutes a Skill-local platform or rule definition

#### Scenario: The default platform changes during an attempt
- **WHEN** the database default platform changes after an attempt has resolved its target
- **THEN** the in-progress attempt retains its pinned platform and policy version
- **AND** only later attempts use the new default

#### Scenario: An existing generic Pipeline runs
- **WHEN** a stored Pipeline generation node has no target-platform configuration
- **THEN** it continues to run without a configuration migration
- **AND** its output MAY remain without a recorded target during the compatibility window

### Requirement: Generation templates are platform compatible
A generation template SHALL reference either no content platform (generic) or one database content platform. Platform-aware template selection SHALL return only enabled, non-deleted `generation` templates that are generic or match the resolved platform. The article save boundary SHALL repeat this validation so a direct template-ID call cannot bypass it.

#### Scenario: A platform-specific template is selected
- **WHEN** a Toutiao attempt lists generation templates
- **THEN** the candidates contain only generic and Toutiao templates
- **AND** Xiaohongshu-specific templates are excluded

#### Scenario: A generic template is selected
- **WHEN** a platform-aware attempt selects an enabled generic generation template
- **THEN** the template remains valid for that platform

#### Scenario: A wrong-platform template is submitted directly
- **WHEN** a Toutiao article save references a Xiaohongshu template ID
- **THEN** the server rejects the save before creating an Article

#### Scenario: Existing templates are migrated
- **WHEN** platform foreign-key support is introduced for templates
- **THEN** existing templates remain generic
- **AND** the migration does not infer platform ownership from template content or usage

### Requirement: Writer, Verifier, and backend consume one policy source
Writer and Verifier SHALL receive the pinned database policy through MCP. Writer SHALL use hard and soft rules as generation guidance. Verifier SHALL mechanically evaluate applicable hard rules and MAY score soft rules. The backend SHALL independently load and execute the same pinned hard rules at generated-article save.

#### Scenario: The Skill follows a hard title rule
- **WHEN** the pinned policy contains a hard maximum-title-length rule
- **THEN** Writer receives it before composing
- **AND** Verifier evaluates it
- **AND** the backend rejects a violating generated save even if the Skill fails to enforce it

#### Scenario: A policy changes between writing and saving
- **WHEN** the pinned immutable version becomes retired before the attempt saves
- **THEN** the save MAY complete against that exact pinned version
- **AND** the generation context references that version
- **AND** no active-version substitution occurs

### Requirement: Publication uses the current target and current active hard policy
Publication preview and task creation SHALL use the Article's current target platform and the target platform's current active hard policy. They SHALL reject a current-target mismatch and hard-rule violations before creating publication records. The historical generation-policy version SHALL remain audit data and SHALL NOT bypass a newer active publication rule.

#### Scenario: Matching publication succeeds
- **WHEN** an approved Article currently targets Toutiao and a Toutiao publication is requested
- **THEN** platform matching does not block the request
- **AND** the current active Toutiao hard policy is evaluated

#### Scenario: Publication platform mismatches
- **WHEN** an Article currently targets Toutiao and a WeChat publication is requested
- **THEN** preview and task creation reject the request consistently
- **AND** no publication task or record is created

#### Scenario: A newer policy is stricter
- **WHEN** an Article was generated under policy v1 but the current active policy is v2
- **THEN** publication evaluates v2
- **AND** v1 remains visible only as generation history

### Requirement: Platform-specific loop and reference queries are truthful
Loop status queries SHALL support filtering by the Article's current target platform so concurrent goals do not count each other's output. Quality-reference queries described as same-platform SHALL return only references associated with the requested platform and SHALL report insufficiency instead of substituting other platforms.

#### Scenario: Loop completion is filtered by platform
- **WHEN** the Orchestrator checks today's approved Toutiao output
- **THEN** only Articles currently targeting Toutiao are counted
- **AND** null and other-platform Articles are excluded

#### Scenario: Same-platform references are insufficient
- **WHEN** fewer than the requested same-category, same-platform references exist
- **THEN** the query reports insufficient coverage
- **AND** Writer or Verifier does not claim that cross-platform substitutions are same-platform evidence

