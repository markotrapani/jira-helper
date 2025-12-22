#!/usr/bin/env python3
"""
Create Jira ticket from Claude's interactive analysis response

This script processes Claude's response from the interactive mode and creates
a properly formatted Jira ticket.

Usage:
    python3 src/create_jira_from_claude_response.py output/claude_response_149320.txt
    python3 src/create_jira_from_claude_response.py output/claude_response_149320.txt --zendesk redislabs.zendesk.com_tickets_149320_print.pdf
"""

import sys
import argparse
import json
from pathlib import Path
from jira_creator import JiraCreator, JiraTicketData
from intelligent_estimator import IntelligentImpactEstimator
from label_extractor import extract_labels


def parse_claude_response(response_file: Path) -> tuple[str, str]:
    """
    Parse Claude's response from the saved file.

    Returns:
        Tuple of (summary, description)
    """
    with open(response_file, 'r') as f:
        content = f.read()

    # Find the separator line if present (only split on FIRST ---)
    if '---' in content:
        parts = content.split('---', 1)  # maxsplit=1 to only split on first occurrence
        if len(parts) > 1:
            content = parts[1].strip()

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

    # Clean up
    summary = summary.strip()
    description = description.strip()

    # Remove LABELS: line from description (should be at the end, not in description body)
    description_lines = description.split('\n')
    cleaned_lines = []
    for line in description_lines:
        # Skip LABELS: line and IMPACT_SCORE: line
        if line.startswith('LABELS:') or line.startswith('IMPACT_SCORE:'):
            continue
        cleaned_lines.append(line)
    description = '\n'.join(cleaned_lines).strip()

    # Fallback if parsing failed
    if not summary:
        print("⚠ Warning: Could not parse SUMMARY from response file")
        summary = "Unable to parse summary from Claude response"

    if not description:
        print("⚠ Warning: Could not parse DESCRIPTION from response file")
        description = content  # Use entire content as fallback

    return summary, description


def main():
    parser = argparse.ArgumentParser(
        description='Create Jira ticket from Claude interactive response',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s output/claude_response_149320.txt
  %(prog)s output/claude_response_149320.txt --zendesk ticket.pdf
  %(prog)s output/claude_response_149320.txt --project MOD --output custom.md
        """
    )

    parser.add_argument(
        'response_file',
        help='Path to Claude response file'
    )

    parser.add_argument(
        '--zendesk',
        help='Path to original Zendesk PDF (for impact score calculation)'
    )

    parser.add_argument(
        '--project',
        choices=['RED', 'MOD', 'DOC', 'RDSC'],
        default='RED',
        help='Jira project for the ticket (default: RED)'
    )

    parser.add_argument(
        '--output',
        help='Output markdown file (default: auto-generated in output/)'
    )

    parser.add_argument(
        '--format',
        choices=['json', 'markdown', 'both'],
        default='markdown',
        help='Output format (default: markdown)'
    )

    args = parser.parse_args()

    # Validate response file
    response_file = Path(args.response_file)
    if not response_file.exists():
        print(f"Error: Response file not found: {args.response_file}")
        sys.exit(1)

    print("="*80)
    print("CREATE JIRA FROM CLAUDE RESPONSE")
    print("="*80)
    print(f"Response file: {args.response_file}")
    print()

    # Parse Claude's response
    print("Parsing Claude's response...")
    summary, description = parse_claude_response(response_file)

    print(f"✓ Summary: {summary[:80]}...")
    print(f"✓ Description: {len(description)} characters")
    print()

    # Calculate impact score if Zendesk PDF provided
    components = {}
    final_score = 0
    zendesk_id = "Unknown"

    if args.zendesk:
        zendesk_path = Path(args.zendesk)
        if zendesk_path.exists():
            print("Calculating impact score from Zendesk PDF...")

            # Extract Zendesk ticket ID from PDF
            from universal_ticket_parser import UniversalTicketParser
            parser = UniversalTicketParser(str(zendesk_path))
            zendesk_data = parser.parse()
            zendesk_id = zendesk_data.get('ticket_id', 'Unknown')

            # Calculate impact score
            estimator = IntelligentImpactEstimator(str(zendesk_path))
            estimator.load_data()
            ticket_info = estimator.extract_ticket_info()
            components = estimator.estimate_all_components()
            base_score, final_score, priority = estimator.calculate_impact_score(components)

            print(f"✓ Impact score: {final_score} points")
            print(f"✓ Zendesk ID: {zendesk_id}")
            print()
        else:
            print(f"⚠ Warning: Zendesk file not found: {args.zendesk}")
            print("Continuing without impact score calculation...")
            print()
    else:
        # Try to extract ticket ID from filename
        filename = response_file.stem
        import re
        match = re.search(r'(\d{6,})', filename)
        if match:
            zendesk_id = match.group(1)

    # Create Jira ticket data
    creator = JiraCreator()

    # Extract keyword-based labels from ticket content (R&D tickets - no source label)
    labels = extract_labels(
        summary=summary,
        description=description,
        source=None,  # Don't include "zendesk" for R&D tickets
        max_labels=5
    )

    # Build custom JiraTicketData with Claude's content
    jira_data = JiraTicketData(
        project=args.project,
        issue_type='Bug',
        summary=summary,
        description=description,
        priority='High',  # Default, will be overridden by impact score if available
        severity='High',
        labels=labels,
        custom_fields={
            'zendesk_id': zendesk_id,
            'source': 'zendesk_claude_interactive'
        }
    )

    # Override priority based on impact score if available
    if final_score > 0:
        if final_score >= 90:
            jira_data.priority = 'Highest'
        elif final_score >= 70:
            jira_data.priority = 'High'
        elif final_score >= 50:
            jira_data.priority = 'Medium'
        elif final_score >= 30:
            jira_data.priority = 'Low'
        else:
            jira_data.priority = 'Lowest'

    print("-"*80)
    print("JIRA TICKET DATA")
    print("-"*80)
    print(f"Project: {jira_data.project}")
    print(f"Issue Type: {jira_data.issue_type}")
    print(f"Summary: {jira_data.summary}")
    print(f"Priority: {jira_data.priority}")
    if final_score > 0:
        print(f"Impact Score: {final_score} points")
    print()

    # Generate output
    output_dir = Path('output')
    output_dir.mkdir(exist_ok=True)

    if not args.output:
        if args.format in ['markdown', 'both']:
            output_file = output_dir / f"JIRA-{zendesk_id}.md"
        else:
            output_file = output_dir / f"JIRA-{zendesk_id}.json"
    else:
        output_file = Path(args.output)

    # Save markdown format
    if args.format in ['markdown', 'both']:
        markdown_content = creator.generate_markdown(
            jira_data=jira_data,
            components=components,
            zendesk_id=zendesk_id,
            impact_score=final_score,
            ticket_type='bug'
        )

        markdown_file = output_file if args.format == 'markdown' else output_file.with_suffix('.md')
        with open(markdown_file, 'w') as f:
            f.write(markdown_content)
        print(f"✓ Markdown file saved to {markdown_file}")

    # Save JSON format
    if args.format in ['json', 'both']:
        ticket_data = {
            'project': jira_data.project,
            'issue_type': jira_data.issue_type,
            'summary': jira_data.summary,
            'description': jira_data.description,
            'priority': jira_data.priority,
            'severity': jira_data.severity,
            'labels': jira_data.labels,
            'custom_fields': jira_data.custom_fields,
            'impact_score': final_score,
            'components': components
        }

        json_file = output_file if args.format == 'json' else output_file.with_suffix('.json')
        with open(json_file, 'w') as f:
            json.dump(ticket_data, f, indent=2)
        print(f"✓ JSON data saved to {json_file}")

    print()
    print("="*80)
    print("NEXT STEPS")
    print("="*80)
    print("1. Review the generated markdown file")
    print("2. Copy and paste the markdown content into Jira")
    print("3. Verify all fields are correctly populated")
    print("4. Link any related tickets as needed")
    print()
    print("="*80)


if __name__ == "__main__":
    main()
