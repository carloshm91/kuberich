# Development assistants and skills

Repository guidance in AGENTS.md is the shared engineering contract. Skills
provide focused assistance; contributors do not need Codex to build or use
Kubetrol. Installing a skill does not connect an external service, grant cluster
access, or authorize unrelated actions.

## Installed in the planning environment

The following skills were installed from the official
[openai/skills](https://github.com/openai/skills) repository at commit
49f948faa9258a0c61caceaf225e179651397431:

| Skill | Purpose |
| --- | --- |
| cli-creator | CLI interface and command design |
| gh-fix-ci | Diagnose and repair GitHub Actions failures |
| gh-address-comments | Address review feedback on PRs |
| security-best-practices | Focused supported-language security review |
| security-threat-model | Explicit trust boundaries and abuse cases |

Use security skills for relevant review tasks. Their web-framework examples do
not change this project's terminal architecture or require a hosted application.

The project also maintains the original
[python-textual-kubernetes skill](../contrib/skills/python-textual-kubernetes/SKILL.md)
for async lifecycles, terminal UX, Kubernetes clients, subprocesses, plugins, and
verification. Its source is tracked here so changes can be reviewed.

## Reproduce installation

Use Codex's skill-installer to install the five curated skill directories from
the pinned official commit. Install the custom skill from this repository's
contrib/skills/python-textual-kubernetes directory into your Codex skills folder.
Do not overwrite an existing customized skill without inspecting it first.

The planning environment installs into the user's Codex skill directory; no
credentials or machine-specific absolute paths belong in this repository.
Newly installed skills become available on the next turn. No additional plugin
connection is required: local tools, gh, Git over SSH, and the documented skills
cover the planned development workflow.

Planning uses Astra as requested by the maintainer. Implementation is intended
for GPT-6.1 Sol after the maintainer switches the conversation model. The choice
of model does not alter acceptance criteria, review, or required CI checks.
