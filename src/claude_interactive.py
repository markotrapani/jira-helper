#!/usr/bin/env python3
"""
Claude Interactive Mode - Use Claude Code session for ticket analysis

This script allows you to use your current Claude Code session (Claude Max)
to analyze Zendesk tickets interactively, without requiring Anthropic API access.

Usage:
    python3 src/claude_interactive.py redislabs.zendesk.com_tickets_149320_print.pdf

This will:
1. Parse the Zendesk PDF
2. Generate a structured prompt for Claude
3. Display instructions for you to paste into Claude Code
4. Save Claude's response to create the Jira ticket
"""

import sys
import json
from pathlib import Path
from universal_ticket_parser import UniversalTicketParser


def generate_analysis_prompt(zendesk_data: dict, ticket_id: str, customer: str = "Unknown") -> str:
    """
    Generate the prompt for Claude Code analysis.

    Args:
        zendesk_data: Parsed Zendesk ticket data
        ticket_id: Zendesk ticket ID
        customer: Customer name

    Returns:
        Formatted prompt string for Claude
    """
    conversation = zendesk_data.get('description', '')

    prompt = f"""I need you to analyze this Zendesk support ticket and create a Jira bug report.

**Zendesk Ticket #{ticket_id}**
**Customer:** {customer}
**Product:** Redis Software

**Full Ticket Conversation:**
```
{conversation}
```

---

**Your Task:**

Analyze this Zendesk conversation and generate:

1. **Summary (one-line title)**
   - Concise, technical summary of the ACTUAL issue (not the original ticket title)
   - Format: "[Customer] - [Component/ROOT CAUSE] [specific technical issue] causing [PRIMARY IMPACT]"
   - Examples:
     - "FedEx - CRDB slave OVC higher than master causing local and inter-CRDB replication failure"
     - "Wells Fargo - node_mgr crash due to missing system_user_password after upgrade"
   - Focus on ROOT CAUSE and PRIMARY IMPACT (not secondary symptoms like memory discrepancy)
   - Omit technical details like hash slot ranges, specific values, etc. - save for description
   - If the ticket evolved (e.g., started as "support package request" but became "CRDB issue"), use the evolved issue

2. **Structured Description**

Use this format with markdown headers (##):

## Customer Context
| Field | Value |
|-------|-------|
| Customer | [Company name] |
| Account # | [Account ID if available] |
| Subscription ID | [Subscription ID(s)] |
| Product | [Redis Cloud Pro/Enterprise, Active-Active, etc.] |
| Region(s) | [AWS/GCP regions affected] |

## Problem Statement
[2-3 sentence overview of the issue and its impact]
[If customer has operational constraints (peak freeze, maintenance windows, business-critical periods), mention them BRIEFLY at the end of this section]

## Issue Observed
[Specific error messages, symptoms, or anomalies - use code blocks for logs]

## Impact
[Bullet points of impact: service state, data risk, customer operations, etc.]
[If customer has operational constraints (peak freeze, etc.), integrate naturally into one impact bullet rather than repeating throughout]
[Example: "Data loss risk: Database vulnerable to data loss... – Customer is in peak freeze period, so they may object to invasive workarounds"]

## Preliminary Analysis
[If known: technical explanation of why this occurred - FOCUS ON CAUSAL RELATIONSHIPS]
[Clearly distinguish: ROOT CAUSE → PRIMARY EFFECT → SECONDARY CONSEQUENCES]
[Example: "OVC corruption (root cause) → local replication failure (primary) → inter-CRDB sync blocked + memory discrepancy (secondary)"]
[If unknown: State "Root cause of [issue] is unknown and requires R&D investigation."]
[Highlight any unusual findings that contradict expected behavior]

## Reproduction Steps
[If reproduction steps are provided in the conversation: include FULL details with actual commands and outputs]
[Use numbered steps with code blocks showing exact commands, outputs, and observations]
[Example format:
1. Created test environment: `command here`
   ```
   actual output here
   ```
2. Observed behavior: description
   ```
   evidence/logs here
   ```
]
[If not reproducible or no reproduction provided: skip this section]

## Technical Details
[Technical specifics NOT in Customer Context: software versions, cluster/node IDs, specific error codes, OVC values, config settings, etc.]
[Use code blocks for technical data]
[Do NOT repeat customer/account/subscription info - that's in Customer Context above]

## Ask From R&D
[Structure this section as follows:]

[First: List specific investigation questions for R&D - numbered list]
[Example:
1. Investigate OVC corruption source: Why did slave OVC increment beyond master?
2. Explain restart behavior: Why did restart correct OVC in test but fail in production?
3. Explain gap reduction: How did the slave's OVC gap decrease after restart?
]

[Then: Add subsections for solutions and workarounds:]

Potential workarounds:
[Bullet list of workarounds that could be attempted]
[Example: • Manually correct OVC: should we consider using CRDT.OVC commands to artificially lower the slave's OVC?]

Potential Improvements:
[Bullet list of long-term fixes or preventative measures]
[Example:
• Add safeguards: Implement OVC validation checks to prevent slave clock from exceeding master
• Consider auto-recovery: Develop mechanism to auto-correct slave OVC mismatches during restart
]

[If applicable: Add customer communication status]
We are still communicating with the customer on the following potential workaround:
[Bullet list of pending customer approval items]

[If support packages exist: Add S3 links]
Support package(s):
[S3 GT-logs links if available - format: s3://gt-logs/exa-to-gt/ZD-TICKETID-RED-JIRAID/debuginfo.HASH.tar.gz]
[If ZD ticket number is available but Jira ID is not yet known, use: s3://gt-logs/exa-to-gt/ZD-TICKETID/...]

---

**Important Guidelines:**
- Extract the NARRATIVE from the conversation (Problem → Investigation → Solution)
- Use technical precision (exact error messages, version numbers, component names)
- Use code blocks for logs, commands, output
- Use bullet points for lists
- Be concise - focus on facts for R&D, not the support conversation flow
- If the ticket is still under investigation, say so explicitly
- Highlight any unusual findings (e.g., "restart worked in test but failed in prod")
- Use professional, measured language (prefer "affects" over "blocks", "may" over "will")
- Avoid repetition - mention customer constraints (peak freeze, etc.) once, integrated naturally
- Do NOT include internal metadata (Slack threads, TAM names, similar ticket references) - R&D doesn't need this

**Output Format:**

Please provide your response in this exact format:

```
SUMMARY: [one-line summary here]

DESCRIPTION:
[structured description here]
```
"""
    return prompt


def save_response_template(output_file: Path, ticket_id: str):
    """Create a template file for saving Claude's response."""
    template = f"""# Claude Analysis Response for Ticket #{ticket_id}

Paste Claude's response below this line:
---

SUMMARY:

DESCRIPTION:

"""
    with open(output_file, 'w') as f:
        f.write(template)

    return output_file


def parse_claude_response(response_file: Path) -> tuple[str, str]:
    """
    Parse Claude's response from the saved file.

    Returns:
        Tuple of (summary, description)
    """
    with open(response_file, 'r') as f:
        content = f.read()

    # Find the separator line
    if '---' in content:
        content = content.split('---', 1)[1].strip()

    lines = content.split('\n')
    summary = ""
    description = ""
    in_description = False

    for line in lines:
        if line.startswith("SUMMARY:"):
            summary = line.replace("SUMMARY:", "").strip()
        elif line.startswith("DESCRIPTION:"):
            in_description = True
            continue
        elif in_description:
            description += line + "\n"

    return summary.strip(), description.strip()


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 src/claude_interactive.py <zendesk_pdf_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]

    if not Path(pdf_path).exists():
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)

    print("="*80)
    print("CLAUDE INTERACTIVE MODE - Zendesk to Jira Analysis")
    print("="*80)
    print(f"Input: {pdf_path}")
    print()

    # Parse Zendesk ticket
    print("Parsing Zendesk ticket...")
    parser = UniversalTicketParser(pdf_path)
    zendesk_data = parser.parse()
    ticket_id = zendesk_data.get('ticket_id', 'Unknown')
    customer = zendesk_data.get('customer_name', 'Unknown')

    print(f"✓ Ticket ID: {ticket_id}")
    print(f"✓ Customer: {customer}")
    print()

    # Generate prompt
    print("Generating Claude analysis prompt...")
    prompt = generate_analysis_prompt(zendesk_data, ticket_id, customer)

    # Save prompt to file
    output_dir = Path('output')
    output_dir.mkdir(exist_ok=True)

    prompt_file = output_dir / f"claude_prompt_{ticket_id}.txt"
    with open(prompt_file, 'w') as f:
        f.write(prompt)

    print(f"✓ Prompt saved to: {prompt_file}")
    print()

    # Create response template
    response_file = output_dir / f"claude_response_{ticket_id}.txt"
    save_response_template(response_file, ticket_id)
    print(f"✓ Response template saved to: {response_file}")
    print()

    print("="*80)
    print("NEXT STEPS")
    print("="*80)
    print()
    print("OPTION 1 - Copy/Paste in Claude Code:")
    print("  1. Copy the content from:")
    print(f"     {prompt_file}")
    print("  2. Paste it into Claude Code (this chat)")
    print("  3. Claude will analyze and respond")
    print("  4. Copy Claude's response to:")
    print(f"     {response_file}")
    print("  5. Run: python3 src/create_jira_from_claude_response.py {response_file}")
    print()
    print("OPTION 2 - Direct prompt display:")
    print("  Run: cat", prompt_file)
    print("  Then paste the output into this chat")
    print()
    print("="*80)
    print()

    # Ask if they want to see the prompt now
    print("Would you like to see the prompt now? (y/n): ", end='')
    try:
        choice = input().strip().lower()
        if choice == 'y':
            print()
            print("="*80)
            print("CLAUDE ANALYSIS PROMPT")
            print("="*80)
            print()
            print(prompt)
            print()
            print("="*80)
    except (EOFError, KeyboardInterrupt):
        print()

    print()
    print("Prompt saved. You can now paste it into Claude Code for analysis.")


if __name__ == "__main__":
    main()
