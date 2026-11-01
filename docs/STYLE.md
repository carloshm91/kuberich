# Documentation style

Write for someone using KubeRich at a terminal. Help them finish a task or find
an exact answer. Explain implementation details only when they affect a decision.

## Choose one documentation type

Use the four [Diátaxis documentation types](https://diataxis.fr/):

| Type | Reader's goal | Write it as |
| --- | --- | --- |
| Tutorial | Learn by doing | A complete, safe walkthrough with an observable result |
| How-to guide | Finish a task | Prerequisites, steps, expected result, and recovery |
| Reference | Look up a fact | Accurate declarations, limits, fields, and defaults |
| Explanation | Understand a concept | Reasons, relationships, tradeoffs, and examples |

Keep each page focused on one reader goal. Link to related tasks instead of
repeating their instructions. A tutorial can link to reference material without
turning into a catalogue of every option.

## Voice and sentences

- Write plain English. Address the reader as **you**.
- Use the present tense and active voice: “Press Enter to open the logs.”
- Prefer familiar words, concrete verbs, and short sentences.
- Start with the result or the action. Explain the reason when it helps.
- Name the resource, context, or file when “it” could be ambiguous.
- Use sentence case for headings. Use action headings for how-to guides.
- Avoid marketing claims, filler, rhetorical questions, and repeated summaries.
- Explain a technical term on first use if a Kubernetes user may not know it.

## Page and navigation budgets

`docs/navigation.json` is the only user-navigation source. It lists the canonical
pages, their documentation type, and any existing source fragments they include.
The budget is **20 user pages**, including the documentation index and generated
reference pages. Redirects are routes, not additional content pages.

Keep each user page at **250 lines or fewer**. Count headings, blank lines,
tables, code blocks, included fragments, and generated Markdown. Do not hide an
oversized page in imports or very long lines. Wrap ordinary prose at about
80–100 characters; commands and reference tables may need longer lines.

The task guides and generated references follow these budgets. Superseded guides,
architecture logs and acceptance records are preserved in `docs/internal/`,
outside public navigation. The architecture overview and ADRs are maintained
separately. Contributor-policy cleanup remains a separate task;
`docs/documentation-plan.json` records each document's disposition.

Keep development policies, ADRs, acceptance records, delivery logs, and source
audits out of user navigation and website search. The architecture overview and
ADRs are contributor documentation; they are not user guides.

## Use words that describe the behavior

Avoid these implementation terms in user prose. Use the replacement that fits
the behavior; do not replace words blindly inside code or official names.

| Avoid | Prefer |
| --- | --- |
| owned | started by KubeRich; created for this session |
| bounded | limited to a stated number of lines, bytes, or jobs |
| captured | selected; the context and resource you selected |
| qualified | tested on the stated platform and version |
| reviewed | checked; confirmed by you |
| original | previous; existing; first, when that is the meaning |
| retained | kept; available in history |
| lifecycle | when the session starts and stops |
| projection | table update; displayed rows |
| provenance | the source and checksum, when the reader needs them |
| preflight | check before applying the change |
| orchestration | the actual action or sequence of actions |
| invariant | rule; requirement |

Keep exact UI labels, CLI flags, configuration keys, API names, quoted output,
and license wording unchanged. For example, a **Review** button keeps its label.
Contributor architecture material can use precise implementation terminology.

## User pages do not contain project tracking

Do not include issue numbers, pull-request numbers, CI run IDs, acceptance
evidence, test counts, internal task codes, or implementation history in user
pages. Link to the task the reader can perform, not the ticket that implemented
it. Changelogs and authored release notes can credit contributors and link to
the relevant changes.

Let generated notices report the source version and publication status. Describe
an available feature and its limits without repeating a release diary. Do not
claim a planned capability works or infer provider support from a simulated test.

## Commands and examples

- Use fictional contexts, namespaces, resource names, and accounts.
- Never copy a customer's context, kubeconfig, token, Secret, or terminal output.
- Show an explicit context and namespace when the command depends on them.
- Start introductory sessions in read-only mode. Explain a write where you ask
  the reader to enable it.
- Keep commands copyable. Do not put a shell prompt or output in the command.
- Use one installation method in a tutorial; link to the alternatives.
- State prerequisites before steps and describe a visible success result.
- Explain an expected permission error or unsupported platform where it matters.
- Use code-generated reference for registered options, aliases, keys, and schema
  fields. Do not maintain a second handwritten catalogue.

Use approved synthetic screenshots. Add useful alternative text and identify a
mockup as a mockup. An image must not be the only place that explains a step.

## Structure a how-to guide

1. State the task and prerequisites.
2. Give the steps in the order you perform them.
3. Show how you recognize success.
4. Explain relevant recovery or cancellation behavior.
5. Link to reference or explanation when more detail helps.

Use lists for actual steps or parallel choices. Use tables for comparisons or
lookup data. Keep safety information specific to the action; avoid unrelated
warnings and promises of perfect reliability.

## Keep links and sources current

Add or change a canonical page in `docs/navigation.json`. Keep every source
fragment assigned to one page. Retired guide URLs must have explicit redirects
to an existing section, and rewritten in-page links must resolve to real anchors.
The builder includes the navigation, renderer, and every source fragment in its
checksum inventory.

Record every existing document's disposition in `docs/documentation-plan.json`:
**keep**, **merge**, **move**, or **delete**. Preserve useful guidance and historical
evidence before retiring a source. Update its inbound links and validators as
part of the migration.

Regenerate lookup pages with `uv run python -m scripts.site_reference --write`.
`uv run python -m scripts.site_reference` checks for declaration drift; CI runs
the same check through the documentation tests.

Run the documentation checks for both local surfaces. Review links, navigation,
and narrow-terminal examples. A successful build prepares static files; website
publication remains a separate maintainer action.
