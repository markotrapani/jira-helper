#!/usr/bin/env python3
"""
Jira Creator - Create Jira tickets with impact scores

This module creates Jira tickets from Zendesk tickets and RCA templates,
automatically calculating impact scores and mapping fields appropriately.

Usage:
    python jira_creator.py zendesk_ticket.pdf --type bug
    python jira_creator.py --create-rca --customer "Customer Name" --date "10/25/25"
"""

import sys
import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

# Import existing modules
from intelligent_estimator import IntelligentImpactEstimator
from universal_ticket_parser import UniversalTicketParser
from impact_score_calculator import ImpactScoreCalculator, ImpactScoreComponents
from label_extractor import extract_labels

# Optional: Claude AI for intelligent description generation
try:
    from claude_analyzer import ClaudeAnalyzer
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False


@dataclass
class JiraTicketData:
    """Data structure for Jira ticket creation."""
    project: str
    issue_type: str
    summary: str
    description: str
    priority: str
    severity: str
    assignee: Optional[str] = None
    labels: List[str] = None
    custom_fields: Dict = None
    linked_issues: List[str] = None
    
    def __post_init__(self):
        if self.labels is None:
            self.labels = []
        if self.custom_fields is None:
            self.custom_fields = {}
        if self.linked_issues is None:
            self.linked_issues = []


class JiraCreator:
    """Creates Jira tickets with impact scores and proper field mapping."""
    
    # Project mappings based on your requirements
    PROJECT_MAPPINGS = {
        'redis': 'RED',
        'modules': 'MOD', 
        'documentation': 'DOC',
        'rdi': 'RDSC',
        'rca': 'Root Cause Analysis'
    }
    
    # Severity mappings (from your PDF)
    SEVERITY_MAPPINGS = {
        0: 'Very High',
        1: 'High', 
        2: 'Medium',
        3: 'Low'
    }
    
    # Priority mappings based on impact score
    PRIORITY_MAPPINGS = {
        'critical': 'Highest',
        'high': 'High',
        'medium': 'Medium', 
        'low': 'Low',
        'minimal': 'Lowest'
    }
    
    def __init__(self, jira_url: str = None, username: str = None, api_token: str = None,
                 claude_analyzer: Optional['ClaudeAnalyzer'] = None):
        """
        Initialize Jira creator.

        Args:
            jira_url: Jira instance URL (for future API integration)
            username: Jira username (for future API integration)
            api_token: Jira API token (for future API integration)
            claude_analyzer: Optional ClaudeAnalyzer for AI-powered description generation
        """
        self.jira_url = jira_url
        self.username = username
        self.api_token = api_token
        self.claude_analyzer = claude_analyzer
        # TODO: Initialize Jira API client when ready
    
    def create_bug_from_zendesk(self, zendesk_file: str, project: str = 'RED',
                                 use_claude: bool = None) -> JiraTicketData:
        """
        Create a bug Jira ticket from Zendesk PDF.

        Args:
            zendesk_file: Path to Zendesk PDF
            project: Jira project key (RED, MOD, DOC, RDSC)
            use_claude: Whether to use Claude AI for description generation
                       (defaults to True if claude_analyzer is available)

        Returns:
            JiraTicketData object ready for creation
        """
        print(f"Analyzing Zendesk ticket: {zendesk_file}")

        # Parse Zendesk ticket
        parser = UniversalTicketParser(zendesk_file)
        zendesk_data = parser.parse()

        # Calculate impact score
        estimator = IntelligentImpactEstimator(zendesk_file)
        estimator.load_data()
        ticket_info = estimator.extract_ticket_info()
        components = estimator.estimate_all_components()
        base_score, final_score, priority = estimator.calculate_impact_score(components)

        # Determine whether to use Claude
        if use_claude is None:
            use_claude = self.claude_analyzer is not None

        # Use Claude for summary and description if enabled
        if use_claude and self.claude_analyzer:
            print("Using Claude AI to generate summary and description...")
            try:
                summary, description = self.claude_analyzer.analyze_zendesk_ticket(
                    zendesk_conversation=zendesk_data.get('description', ''),
                    ticket_id=zendesk_data.get('ticket_id', 'Unknown'),
                    customer=zendesk_data.get('customer_name', 'Unknown'),
                    product=self._detect_product(zendesk_data.get('description', ''))
                )

                # Override zendesk_data with Claude-generated content
                zendesk_data['summary'] = summary
                zendesk_data['description'] = description
                print(f"✓ Claude generated summary: {summary[:60]}...")
            except Exception as e:
                print(f"⚠ Claude analysis failed ({e}), falling back to keyword-based extraction")
                # Fall back to normal processing

        # Map to Jira fields
        jira_data = self._map_zendesk_to_jira(zendesk_data, components, final_score, priority, project)

        return jira_data
    
    def create_rca_ticket(self, customer_name: str, date: str, 
                         zendesk_tickets: List[str] = None,
                         related_bugs: List[str] = None,
                         bug_jira_file: str = None) -> JiraTicketData:
        """
        Create an RCA ticket based on the template.
        
        Args:
            customer_name: Customer name for the RCA
            date: Date in MM/DD/YY format
            zendesk_tickets: List of Zendesk ticket IDs
            related_bugs: List of related bug Jira keys
            bug_jira_file: Path to bug Jira PDF for auto-population
            
        Returns:
            JiraTicketData object ready for creation
        """
        # Format customer name (replace spaces with underscores for labels)
        account_name = customer_name.replace(' ', '_')
        
        # Auto-populate from bug Jira if provided
        auto_populated_data = {}
        if bug_jira_file and Path(bug_jira_file).exists():
            auto_populated_data = self._extract_bug_jira_info(bug_jira_file)
        
        # Create RCA ticket data based on template
        jira_data = JiraTicketData(
            project='Root Cause Analysis',
            issue_type='RCA',
            summary=f"{customer_name} - RCA {date}",
            description=self._create_rca_description(customer_name, date, zendesk_tickets, auto_populated_data),
            priority='Medium',  # RCA tickets are typically medium priority
            severity='Medium',
            labels=[account_name],
            custom_fields={
                'zendesk_tickets': zendesk_tickets or [],
                'slack_channel': f"#prod-{date.replace('/', '')}-{customer_name.lower().replace(' ', '')}",
                'initial_root_cause': auto_populated_data.get('initial_root_cause', '<Add your initial RCA here>'),
                'final_root_cause': auto_populated_data.get('final_root_cause', '<Add your final RCA and Conclusions here>'),
                'action_items': auto_populated_data.get('action_items', []),
                'cluster_id': auto_populated_data.get('cluster_id', ''),
                'account_id': auto_populated_data.get('account_id', ''),
                'affected_component': auto_populated_data.get('affected_component', ''),
                'environment': auto_populated_data.get('environment', ''),
                'cache_name': auto_populated_data.get('cache_name', ''),
                'region': auto_populated_data.get('region', '')
            },
            linked_issues=related_bugs or []
        )
        
        return jira_data
    
    def _extract_bug_jira_info(self, bug_jira_file: str) -> Dict:
        """Extract information from bug Jira PDF to auto-populate RCA."""
        try:
            # Parse the bug Jira PDF
            parser = UniversalTicketParser(bug_jira_file)
            bug_data = parser.parse()
            
            # Extract key information
            description = bug_data.get('description', '')
            summary = bug_data.get('summary', '')
            
            # Extract cache info
            cache_info = self._extract_cache_info(description)
            
            # Generate initial root cause from bug description
            initial_root_cause = self._generate_initial_root_cause(summary, description)
            
            # Generate action items from bug description
            action_items = self._generate_action_items(summary, description)
            
            return {
                'initial_root_cause': initial_root_cause,
                'final_root_cause': '<Add your final RCA and Conclusions here>',
                'action_items': action_items,
                'cluster_id': self._extract_cluster_id(description),
                'account_id': self._extract_account_id(description),
                'affected_component': self._detect_component(description),
                'environment': self._detect_organization(description),
                'cache_name': cache_info.get('cache_name', ''),
                'region': cache_info.get('region', ''),
                'bug_summary': summary,
                'bug_description': description[:500] + '...' if len(description) > 500 else description
            }
        except Exception as e:
            print(f"Warning: Could not extract bug Jira info: {e}")
            return {}
    
    def _generate_initial_root_cause(self, summary: str, description: str) -> str:
        """Generate initial root cause from bug information."""
        if not summary and not description:
            return '<Add your initial RCA here>'
        
        # Extract key phrases that might indicate root cause
        root_cause_indicators = []
        
        if 'cpu' in description.lower():
            root_cause_indicators.append("High CPU utilization")
        if 'audit' in description.lower():
            root_cause_indicators.append("Audit logging issues")
        if 'connection' in description.lower():
            root_cause_indicators.append("Connection problems")
        if 'restart' in description.lower():
            root_cause_indicators.append("Service restart required")
        
        if root_cause_indicators:
            return f"Initial analysis suggests: {', '.join(root_cause_indicators)}. " + \
                   f"Bug: {summary}. Requires detailed investigation."
        else:
            return f"Bug: {summary}. Root cause analysis needed."
    
    def _generate_action_items(self, summary: str, description: str) -> List[Dict]:
        """Generate suggested action items from bug information."""
        action_items = []
        
        # Common action items based on bug type
        if 'cpu' in description.lower():
            action_items.append({
                'description': 'Investigate CPU utilization patterns',
                'type': 'Investigate',
                'owner': '@name',
                'ticket': '<jira-ticket>'
            })
        
        if 'audit' in description.lower():
            action_items.append({
                'description': 'Review audit logging configuration',
                'type': 'Investigate', 
                'owner': '@name',
                'ticket': '<jira-ticket>'
            })
        
        if 'restart' in description.lower():
            action_items.append({
                'description': 'Implement automatic recovery mechanisms',
                'type': 'Prevent',
                'owner': '@name', 
                'ticket': '<jira-ticket>'
            })
        
        # Default action item if none detected
        if not action_items:
            action_items.append({
                'description': 'Investigate root cause of reported issue',
                'type': 'Investigate',
                'owner': '@name',
                'ticket': '<jira-ticket>'
            })
        
        return action_items
    
    def _extract_cluster_id(self, description: str) -> str:
        """Extract cluster ID from description."""
        import re
        cluster_match = re.search(r'cluster[:\s]+([^\s,]+)', description, re.IGNORECASE)
        return cluster_match.group(1) if cluster_match else ''
    
    def _extract_account_id(self, description: str) -> str:
        """Extract account ID from description."""
        import re
        account_match = re.search(r'account[:\s]+([^\s,]+)', description, re.IGNORECASE)
        return account_match.group(1) if account_match else ''
    
    def _map_zendesk_to_jira(self, zendesk_data: Dict, components: Dict, 
                           impact_score: float, priority: str, project: str) -> JiraTicketData:
        """Map Zendesk data to Jira fields."""
        
        # Extract key information
        summary = zendesk_data.get('summary', 'No summary provided')
        description = zendesk_data.get('description', 'No description provided')
        ticket_id = zendesk_data.get('ticket_id', 'Unknown')
        
        # Map severity based on impact score
        if impact_score >= 90:
            severity = 'Very High'
        elif impact_score >= 70:
            severity = 'High'
        elif impact_score >= 50:
            severity = 'Medium'
        else:
            severity = 'Low'
        
        # Extract keyword-based labels from ticket content
        labels = extract_labels(
            summary=zendesk_data['summary'],
            description=description,
            customer_name=zendesk_data.get('customer_name'),
            source='zendesk',
            max_labels=5
        )
        
        # Extract cache info if present
        cache_info = self._extract_cache_info(description)
        
        # Create custom fields
        custom_fields = {
            'impact_score': impact_score,
            'impact_severity': components['impact_severity']['score'],
            'customer_arr': components['customer_arr']['score'],
            'sla_breach': components['sla_breach']['score'],
            'frequency': components['frequency']['score'],
            'workaround': components['workaround']['score'],
            'rca_action_item': components['rca_action_item']['score'],
            'zendesk_id': ticket_id,
            'component': self._detect_component(description),
            'environment': 'Production',
            'affected_organizations': self._detect_organization(description)
        }
        
        # Add cache info if found
        if cache_info:
            custom_fields.update(cache_info)
        
        return JiraTicketData(
            project=project,
            issue_type='Bug',
            summary=summary,
            description=self._format_description(description, ticket_id, impact_score),
            priority=self.PRIORITY_MAPPINGS.get(priority.lower(), 'Medium'),
            severity=severity,
            labels=labels,
            custom_fields=custom_fields
        )
    
    def _extract_cache_info(self, description: str) -> Dict:
        """Extract cache name and region from description."""
        cache_info = {}
        
        # Look for cache name patterns
        import re
        cache_match = re.search(r'cache name[:\s]+([^\s,]+)', description, re.IGNORECASE)
        if cache_match:
            cache_info['cache_name'] = cache_match.group(1)
        
        # Look for region patterns
        region_match = re.search(r'region[:\s]+([^\s,]+)', description, re.IGNORECASE)
        if region_match:
            cache_info['region'] = region_match.group(1)
        
        return cache_info
    
    def _detect_component(self, description: str) -> str:
        """Detect component from description."""
        description_lower = description.lower()
        
        if 'dmc' in description_lower:
            return 'DMC'
        elif 'redis' in description_lower:
            return 'Redis'
        elif 'cluster' in description_lower:
            return 'Cluster'
        else:
            return 'Unknown'
    
    def _detect_organization(self, description: str) -> str:
        """Detect affected organization."""
        description_lower = description.lower()
        
        if 'azure' in description_lower:
            return 'Azure'
        elif 'aws' in description_lower:
            return 'AWS'
        elif 'gcp' in description_lower:
            return 'GCP'
        else:
            return 'Unknown'
    
    def _format_description(self, description: str, zendesk_id: str, impact_score: float) -> str:
        """Format description with additional context."""
        # Just return the description without embedding score calculation details
        return description

    def generate_markdown(self, jira_data: JiraTicketData, components: Dict = None,
                         zendesk_id: str = None, impact_score: float = None,
                         ticket_type: str = "bug") -> str:
        """
        Generate clean markdown format for Jira ticket (not Jira wiki markup).

        Args:
            jira_data: JiraTicketData object
            components: Impact score component breakdown
            zendesk_id: Zendesk ticket ID
            impact_score: Calculated impact score
            ticket_type: Type of ticket (bug, rca)

        Returns:
            Formatted markdown string
        """
        lines = []

        # Header section
        if ticket_type == "bug":
            # Check if RCA is needed based on description
            needs_rca = "rca" in jira_data.description.lower() or "root cause" in jira_data.description.lower()
            if needs_rca:
                lines.append("# JIRA BUG TICKET - RCA NEEDED")
            else:
                lines.append("# JIRA BUG TICKET - READY FOR SUBMISSION")
        else:
            lines.append("# JIRA RCA TICKET")

        lines.append("")
        lines.append(f"**PROJECT:** {jira_data.project}")
        lines.append(f"**ISSUE TYPE:** {jira_data.issue_type}")
        lines.append(f"**PRIORITY:** {self._map_priority_to_p_level(jira_data.priority)}")

        # Add impact score if available
        if impact_score:
            priority_level = self._get_priority_level(impact_score)
            lines.append(f"**IMPACT SCORE:** {int(impact_score)} points ({priority_level})")

        # Add impact score breakdown if components available
        if components:
            lines.append("")
            lines.append("### Impact Score Breakdown")
            lines.append("| Component | Score | Reason |")
            lines.append("|-----------|-------|--------|")

            # Define component display order and names
            component_display = [
                ('impact_severity', 'Impact & Severity', 38),
                ('customer_arr', 'Customer ARR', 15),
                ('sla_breach', 'SLA Breach', 8),
                ('frequency', 'Frequency', 16),
                ('workaround', 'Workaround', 15),
                ('rca_action_item', 'RCA Action Item', 8),
            ]

            for comp_key, comp_name, max_pts in component_display:
                if comp_key in components:
                    comp_data = components[comp_key]
                    score = comp_data.get('score', 0)
                    reason = comp_data.get('reason', 'Unknown')
                    lines.append(f"| {comp_name} | {score}/{max_pts} | {reason} |")

        lines.append("")

        # Summary section
        lines.append("## Summary")
        lines.append("")
        lines.append(jira_data.summary or "[No summary available]")
        lines.append("")

        # Description section
        lines.append("## Description")
        lines.append("")
        lines.append(jira_data.description or "[No description available]")
        lines.append("")

        # Environment section
        lines.append("## Environment")
        lines.append("")

        # Extract environment info from custom fields
        if jira_data.custom_fields:
            env_fields = {
                'Product': jira_data.custom_fields.get('environment', 'Redis Software'),
                'Version': jira_data.custom_fields.get('version', ''),
                'Customer': jira_data.custom_fields.get('customer', ''),
                'Cluster': jira_data.custom_fields.get('cluster_id', ''),
                'Region': jira_data.custom_fields.get('region', '')
            }

            for key, value in env_fields.items():
                if value:
                    lines.append(f"- **{key}:** {value}")

        lines.append("")

        # Labels section
        lines.append("## Labels")
        lines.append("")
        if jira_data.labels:
            lines.append(", ".join(jira_data.labels))
        lines.append("")

        # Related tickets section
        lines.append("## Related Tickets")
        lines.append("")
        if zendesk_id:
            lines.append(f"- **Zendesk:** #{zendesk_id}")
        if jira_data.linked_issues:
            lines.append(f"- **Related:** {', '.join(jira_data.linked_issues)}")
        lines.append("")

        # Attachments section
        lines.append("## Attachments")
        lines.append("")
        if zendesk_id:
            lines.append(f"- Zendesk PDF: redislabs.zendesk.com_tickets_{zendesk_id}_print.pdf")
        lines.append("")

        # Components section
        lines.append("## Components")
        lines.append("")
        if jira_data.custom_fields and jira_data.custom_fields.get('component'):
            lines.append(jira_data.custom_fields['component'])
        lines.append("")

        # Affects versions section
        lines.append("## Affects Versions")
        lines.append("")
        if jira_data.custom_fields and jira_data.custom_fields.get('version'):
            lines.append(jira_data.custom_fields['version'])
        lines.append("")

        # Fix versions section
        lines.append("## Fix Versions")
        lines.append("")
        lines.append("[To be determined by R&D]")
        lines.append("")

        return "\n".join(lines)

    def _map_priority_to_p_level(self, priority: str) -> str:
        """Map Jira priority to P-level designation."""
        mapping = {
            'Highest': 'P1 - Critical',
            'High': 'P2 - High',
            'Medium': 'P3 - Medium',
            'Low': 'P4 - Low',
            'Lowest': 'P5 - Minimal'
        }
        return mapping.get(priority, priority)

    def _get_priority_level(self, impact_score: float) -> str:
        """Get priority level text from impact score."""
        if impact_score >= 90:
            return "CRITICAL"
        elif impact_score >= 70:
            return "HIGH"
        elif impact_score >= 50:
            return "MEDIUM"
        elif impact_score >= 30:
            return "LOW"
        else:
            return "MINIMAL"
    
    def _create_rca_description(self, customer_name: str, date: str, zendesk_tickets: List[str], auto_populated_data: Dict = None) -> str:
        """Create RCA description based on template with auto-populated data."""
        if auto_populated_data is None:
            auto_populated_data = {}
        
        # Use auto-populated summary or default
        summary = auto_populated_data.get('bug_summary', '<Add the summary here.>')
        description = f"**Summary:** {summary}\n\n"
        
        # Add cluster and account info if available
        if auto_populated_data.get('cluster_id'):
            description += f"**Cluster ID:** {auto_populated_data['cluster_id']}\n"
        if auto_populated_data.get('account_id'):
            description += f"**Account ID:** {auto_populated_data['account_id']}\n"
        if auto_populated_data.get('cache_name'):
            description += f"**Cache Name:** {auto_populated_data['cache_name']}\n"
        if auto_populated_data.get('region'):
            description += f"**Region:** {auto_populated_data['region']}\n"
        
        description += f"\n**Date and Time (UTC)**\n"
        description += f"**Activity**\n"
        description += f"MMM-DD-YYYY, HH:MM <What happened/what has been done>\n\n"
        
        if zendesk_tickets:
            description += f"**Related Zendesk Tickets:** {', '.join(zendesk_tickets)}\n\n"
        
        # Use auto-populated initial root cause or default
        initial_rca = auto_populated_data.get('initial_root_cause', '<Add your initial RCA here>')
        description += f"**Initial Root Cause:** {initial_rca}\n\n"
        description += f"**Final Root Cause & Conclusions:** <Add your final RCA and Conclusions here>\n\n"
        
        # Add auto-generated action items
        action_items = auto_populated_data.get('action_items', [])
        if action_items:
            description += f"**Action item(s):**\n"
            description += f"After updating the table below, ensure the tickets are linked with the `relates to` type.\n\n"
            description += f"| Description | Type | Owner | Ticket |\n"
            description += f"|-------------|------|-------|--------|\n"
            for item in action_items:
                description += f"| {item['description']} | {item['type']} | {item['owner']} | {item['ticket']} |\n"
        else:
            description += f"**Action item(s):**\n"
            description += f"After updating the table below, ensure the tickets are linked with the `relates to` type.\n\n"
            description += f"| Description | Type | Owner | Ticket |\n"
            description += f"|-------------|------|-------|--------|\n"
            description += f"| <What is the AI about?> | Investigate or Prevent or Mitigate | @name | <jira-ticket> |\n"
        
        return description
    
    def suggest_jira_fields(self, zendesk_file: str) -> Dict:
        """
        Analyze Zendesk ticket and suggest Jira fields without creating ticket.
        
        Args:
            zendesk_file: Path to Zendesk PDF
            
        Returns:
            Dictionary with suggested Jira fields
        """
        print(f"Analyzing Zendesk ticket for Jira field suggestions: {zendesk_file}")
        
        # Parse and analyze
        parser = UniversalTicketParser(zendesk_file)
        zendesk_data = parser.parse()
        
        estimator = IntelligentImpactEstimator(zendesk_file)
        estimator.load_data()
        ticket_info = estimator.extract_ticket_info()
        components = estimator.estimate_all_components()
        base_score, final_score, priority = estimator.calculate_impact_score(components)
        
        # Create suggestions
        suggestions = {
            'ticket_info': {
                'zendesk_id': zendesk_data.get('ticket_id'),
                'summary': zendesk_data.get('summary'),
                'description': zendesk_data.get('description', '')[:500] + '...' if len(zendesk_data.get('description', '')) > 500 else zendesk_data.get('description', '')
            },
            'impact_analysis': {
                'final_score': final_score,
                'priority': priority,
                'base_score': base_score,
                'components': {
                    'impact_severity': components['impact_severity'],
                    'customer_arr': components['customer_arr'],
                    'sla_breach': components['sla_breach'],
                    'frequency': components['frequency'],
                    'workaround': components['workaround'],
                    'rca_action_item': components['rca_action_item']
                }
            },
            'suggested_jira_fields': {
                'project': 'RED',  # Default to RED, could be enhanced with detection
                'issue_type': 'Bug',
                'priority': self.PRIORITY_MAPPINGS.get(priority.lower(), 'Medium'),
                'severity': 'High' if final_score >= 70 else 'Medium' if final_score >= 50 else 'Low',
                'labels': ['Support', 'Customer-Reported'],
                'component': self._detect_component(zendesk_data.get('description', '')),
                'environment': 'Production',
                'custom_fields': {
                    'impact_score': final_score,
                    'zendesk_id': zendesk_data.get('ticket_id'),
                    'cache_name': self._extract_cache_info(zendesk_data.get('description', '')).get('cache_name'),
                    'region': self._extract_cache_info(zendesk_data.get('description', '')).get('region')
                }
            }
        }
        
        return suggestions


def main():
    parser = argparse.ArgumentParser(
        description='Create Jira tickets with impact scores',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s zendesk_ticket.pdf --type bug
  %(prog)s zendesk_ticket.pdf --suggest-only
  %(prog)s --create-rca --customer "Customer Name" --date "10/25/25"
        """
    )
    
    parser.add_argument(
        'file',
        nargs='?',
        help='Path to Zendesk PDF file'
    )
    
    parser.add_argument(
        '--type',
        choices=['bug', 'rca'],
        help='Type of Jira ticket to create'
    )
    
    parser.add_argument(
        '--suggest-only',
        action='store_true',
        help='Only suggest Jira fields, do not create ticket'
    )
    
    parser.add_argument(
        '--create-rca',
        action='store_true',
        help='Create RCA ticket'
    )
    
    parser.add_argument(
        '--customer',
        help='Customer name for RCA ticket'
    )
    
    parser.add_argument(
        '--date',
        help='Date for RCA ticket (MM/DD/YY format)'
    )
    
    parser.add_argument(
        '--zendesk-tickets',
        nargs='+',
        help='Zendesk ticket IDs to link to RCA'
    )
    
    parser.add_argument(
        '--related-bugs',
        nargs='+',
        help='Related bug Jira keys to link to RCA'
    )
    
    parser.add_argument(
        '--project',
        choices=['RED', 'MOD', 'DOC', 'RDSC'],
        default='RED',
        help='Jira project for bug tickets'
    )
    
    parser.add_argument(
        '--output',
        help='Output file for ticket data (JSON format)'
    )
    
    args = parser.parse_args()
    
    creator = JiraCreator()
    
    if args.create_rca:
        if not args.customer or not args.date:
            print("Error: --customer and --date are required for RCA creation")
            sys.exit(1)
        
        print("Creating RCA ticket...")
        rca_data = creator.create_rca_ticket(
            customer_name=args.customer,
            date=args.date,
            zendesk_tickets=args.zendesk_tickets,
            related_bugs=args.related_bugs
        )
        
        print("\n" + "="*80)
        print("RCA TICKET DATA")
        print("="*80)
        print(f"Project: {rca_data.project}")
        print(f"Issue Type: {rca_data.issue_type}")
        print(f"Summary: {rca_data.summary}")
        print(f"Priority: {rca_data.priority}")
        print(f"Labels: {', '.join(rca_data.labels)}")
        print(f"Custom Fields: {json.dumps(rca_data.custom_fields, indent=2)}")
        
        if args.output:
            with open(args.output, 'w') as f:
                json.dump({
                    'project': rca_data.project,
                    'issue_type': rca_data.issue_type,
                    'summary': rca_data.summary,
                    'description': rca_data.description,
                    'priority': rca_data.priority,
                    'severity': rca_data.severity,
                    'labels': rca_data.labels,
                    'custom_fields': rca_data.custom_fields,
                    'linked_issues': rca_data.linked_issues
                }, f, indent=2)
            print(f"\n✓ RCA ticket data saved to {args.output}")
    
    elif args.file:
        if args.suggest_only:
            print("Analyzing Zendesk ticket for Jira field suggestions...")
            suggestions = creator.suggest_jira_fields(args.file)
            
            print("\n" + "="*80)
            print("JIRA FIELD SUGGESTIONS")
            print("="*80)
            print(f"Zendesk ID: {suggestions['ticket_info']['zendesk_id']}")
            print(f"Summary: {suggestions['ticket_info']['summary']}")
            print(f"Impact Score: {suggestions['impact_analysis']['final_score']}")
            print(f"Priority: {suggestions['impact_analysis']['priority']}")
            print(f"Suggested Project: {suggestions['suggested_jira_fields']['project']}")
            print(f"Suggested Priority: {suggestions['suggested_jira_fields']['priority']}")
            print(f"Suggested Severity: {suggestions['suggested_jira_fields']['severity']}")
            print(f"Suggested Labels: {', '.join(suggestions['suggested_jira_fields']['labels'])}")
            print(f"Suggested Component: {suggestions['suggested_jira_fields']['component']}")
            
            print("\nComponent Breakdown:")
            for component, data in suggestions['impact_analysis']['components'].items():
                print(f"  {component}: {data['score']} points - {data['reason']}")
            
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(suggestions, f, indent=2)
                print(f"\n✓ Suggestions saved to {args.output}")
        
        else:
            print("Creating bug Jira ticket from Zendesk...")
            bug_data = creator.create_bug_from_zendesk(args.file, args.project)
            
            print("\n" + "="*80)
            print("BUG TICKET DATA")
            print("="*80)
            print(f"Project: {bug_data.project}")
            print(f"Issue Type: {bug_data.issue_type}")
            print(f"Summary: {bug_data.summary}")
            print(f"Priority: {bug_data.priority}")
            print(f"Severity: {bug_data.severity}")
            print(f"Labels: {', '.join(bug_data.labels)}")
            print(f"Custom Fields: {json.dumps(bug_data.custom_fields, indent=2)}")
            
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump({
                        'project': bug_data.project,
                        'issue_type': bug_data.issue_type,
                        'summary': bug_data.summary,
                        'description': bug_data.description,
                        'priority': bug_data.priority,
                        'severity': bug_data.severity,
                        'labels': bug_data.labels,
                        'custom_fields': bug_data.custom_fields,
                        'linked_issues': bug_data.linked_issues
                    }, f, indent=2)
                print(f"\n✓ Bug ticket data saved to {args.output}")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
