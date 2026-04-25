#!/usr/bin/env python3
"""
Intelligent Impact Score Estimator

Analyzes Jira and Zendesk ticket exports and automatically estimates impact score
components based on ticket fields, description, labels, and other metadata.

Supported formats:
- Jira: PDF, Excel (.xlsx), XML, Word (.docx)
- Zendesk: PDF

Usage:
    python intelligent_estimator.py <ticket_export>
    python intelligent_estimator.py RED-12345.pdf --output scores.json
    python intelligent_estimator.py zendesk_ticket_789.pdf
"""

import sys
import re
import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd

# Import universal parser for multi-format support
try:
    from universal_ticket_parser import parse_ticket_file
    UNIVERSAL_PARSER_AVAILABLE = True
except ImportError:
    UNIVERSAL_PARSER_AVAILABLE = False


class IntelligentImpactEstimator:
    """Analyzes Jira tickets and estimates impact score components intelligently."""
    
    # Priority to severity mapping
    PRIORITY_TO_SEVERITY = {
        'blocker': 38,
        'critical': 38,
        'highest': 38,
        'high': 30,
        'medium': 22,
        'low': 16,
        'lowest': 8,
        'trivial': 8,
    }
    
    # Severity field mappings
    SEVERITY_MAPPINGS = {
        '1 - critical': 38,
        '1 - high': 38,
        'sev 1': 38,
        'p1': 38,
        '2 - high': 30,
        '2 - medium': 30,
        'sev 2': 30,
        'p2': 30,
        '3 - medium': 22,
        '3 - low': 22,
        'sev 3': 22,
        'p3': 22,
        '4 - low': 16,
        'p4': 16,
        '5 - trivial': 8,
        'p5': 8,
    }
    
    # Support tier keywords (from Zendesk organization notes)
    # Used to detect high-value customers based on support package tier
    SUPPORT_TIER_KEYWORDS = {
        'premium_enterprise': ['premium enterprise', 'premium-enterprise', 'vip support', 'vip package'],
        'enterprise': ['enterprise support', 'enterprise package'],
        'standard': ['standard support', 'standard package'],
        'essentials': ['essentials support', 'essentials package']
    }

    # ARR amount patterns. Each entry is (regex, unit) where unit is 'M' or 'K'.
    # Patterns are case-insensitive at match time.
    ARR_PATTERNS = [
        (r'\$\s*(\d+(?:\.\d+)?)\s*m\b', 'M'),          # $5M, $5.5M, $ 10M
        (r'\$\s*(\d+)\s*k\b', 'K'),                    # $500K, $750k
        (r'arr[:\s]+\$\s*(\d+(?:\.\d+)?)\s*m\b', 'M'), # ARR: $5M
        (r'arr[:\s]+\$\s*(\d+)\s*k\b', 'K'),           # ARR: $500K
        (r'(\d+(?:\.\d+)?)\s*m[-–]\s*(\d+(?:\.\d+)?)\s*m\s*arr', 'M-M'),  # 5M-10M ARR
    ]
    
    # Keywords indicating workaround availability
    WORKAROUND_KEYWORDS = {
        'simple': ['workaround', 'can use', 'alternative', 'use instead', 'run command'],
        'complex': ['manual', 'multiple steps', 'requires', 'need to'],
        'with_impact': [
            'performance', 'slower', 'degraded', 'limited',
            'inconvenient', 'operational overhead', 'manual intervention',
            'hard-coded', 'hardcoded', 'manual update', 'manually update',
            'reduced capability', 'reduced effectiveness', 'not as designed',
            'operational impact', 'requires updating', 'human error',
            'reduced confidence', 'less effective', 'workaround impact'
        ],
        'none': [
            'no workaround', 'cannot', 'impossible', 'requires fix', 'needs patch',
            'no confirmed workaround', 'unconfirmed', 'not confirmed',
            'requires r&d approval', 'requires approval', 'r&d approval',
            'with approval from', 'with r&d approval', 'pending approval',
            'proposed solutions require', 'unverified workaround', 'untested',
            'did not resolve', 'failed to fix', 'not fixed'
        ],
    }
    
    # SLA breach indicators
    SLA_KEYWORDS = ['sla breach', 'sla violated', 'exceeded sla', 'manual recovery', 'downtime']
    
    # Frequency indicators
    FREQUENCY_KEYWORDS = {
        'always': [
            'persistent', 'always', 'consistently', 'constantly', 'continuous',
            'survives restart', 'persists after restart', 'remains after restart',
            'still present after', 'did not resolve', 'not fixed by restart',
            'permanent', 'ongoing', 'reproduces every time'
        ],
        'multiple': ['multiple', 'several', 'recurring', 'repeated', 'again', 'reoccur'],
        'single': ['first time', 'one time', 'single', 'once'],
    }
    
    # RCA indicators
    RCA_KEYWORDS = ['rca', 'root cause', 'action item', 'post mortem', 'postmortem']
    
    def __init__(self, file_path: str, manual_arr: Optional[str] = None,
                 rca_jira_exists: Optional[bool] = None):
        """Initialize with path to ticket export (PDF/Excel/XML/Word).

        Args:
            rca_jira_exists: Pre-set the RCA Jira answer to skip the interactive
                prompt.  True → 8 points, False → 0 points, None → ask at
                runtime (default).
        """
        self.file_path = Path(file_path)
        self.file_ext = self.file_path.suffix.lower()
        self.df = None
        self.ticket_data = {}
        self.manual_arr = manual_arr  # User-provided ARR override
        self.rca_jira_exists = rca_jira_exists  # None = ask interactively

    def load_data(self):
        """Load ticket export data from any supported format."""
        try:
            # Try universal parser first for non-Excel formats
            if self.file_ext in ['.pdf', '.xml', '.docx']:
                if not UNIVERSAL_PARSER_AVAILABLE:
                    raise ImportError("universal_ticket_parser module required for non-Excel formats")

                print(f"✓ Parsing {self.file_ext.upper()} file: {self.file_path}")
                self.ticket_data = parse_ticket_file(self.file_path)
                print(f"  Source: {self.ticket_data.get('source', 'unknown').upper()}")
                print(f"  Ticket ID: {self.ticket_data.get('issue_key') or self.ticket_data.get('ticket_id')}")
                return self.ticket_data

            # Excel format - use existing pandas logic
            elif self.file_ext == '.xlsx':
                xl_file = pd.ExcelFile(self.file_path)
                sheet_name = xl_file.sheet_names[0]
                self.df = pd.read_excel(self.file_path, sheet_name=sheet_name)

                print(f"✓ Loaded Excel data from {self.file_path}")
                print(f"  Sheet: {sheet_name}")
                print(f"  Columns: {len(self.df.columns)}")

                return self.df
            else:
                raise ValueError(f"Unsupported file format: {self.file_ext}")

        except Exception as e:
            raise Exception(f"Error loading file: {e}")
    
    def extract_ticket_info(self) -> Dict:
        """Extract key information from the ticket."""
        # If already loaded via universal parser (PDF/XML/DOCX), return as-is
        if self.ticket_data and self.file_ext in ['.pdf', '.xml', '.docx']:
            return self.ticket_data

        # Excel format - extract from DataFrame
        if self.df is None:
            raise ValueError("No data loaded. Call load_data() first.")

        row = self.df.iloc[0]
        
        # Extract key fields
        self.ticket_data = {
            'issue_key': self._get_field(row, ['Issue key', 'Jira', 'Key']),
            'summary': self._get_field(row, ['Summary']),
            'description': self._get_field(row, ['Description']),
            'priority': self._get_field(row, ['Priority']),
            'issue_type': self._get_field(row, ['Issue Type']),
            'status': self._get_field(row, ['Status']),
            'severity': self._get_field(row, ['Custom field (Severity)', 'Severity']),
            'labels': self._get_labels(row),
            'customer_name': self._get_field(row, [
                'Custom field (Customer Name)',
                'Custom field (Account Name)',
                'Custom field (CSQ Customer Name)'
            ]),
            'workaround': self._get_field(row, ['Custom field (Workaround)']),
            'rca': self._get_field(row, ['Custom field (RCA)']),
            'zendesk': self._get_field(row, [
                'Custom field (Zendesk Link)',
                'Custom field (Zendesk)',
                'Custom field (Zendesk ID/s)'
            ]),
        }
        
        return self.ticket_data
    
    def _get_field(self, row, field_names: List[str]) -> Optional[str]:
        """Get field value from row, trying multiple possible field names."""
        for field in field_names:
            if field in row.index and pd.notna(row[field]):
                return str(row[field])
        return None
    
    def _get_labels(self, row) -> List[str]:
        """Extract all labels from the ticket."""
        labels = []
        for col in row.index:
            if col.startswith('Labels') and pd.notna(row[col]):
                labels.append(str(row[col]))
        return labels
    
    def estimate_impact_severity(self) -> Tuple[int, str]:
        """Estimate Impact & Severity score (0-38 points)."""
        reasons = []

        # Get description and summary for context analysis
        # Include raw_text for Zendesk tickets where description may be truncated
        desc = ((self.ticket_data.get('description') or '') + ' ' +
                (self.ticket_data.get('summary') or '') + ' ' +
                (self.ticket_data.get('raw_text') or '')[:5000]).lower()  # Limit raw_text to 5000 chars

        # First, check for P5/Trivial indicators (cosmetic/visual issues)
        trivial_indicators = [
            'cosmetic', 'visual oddities', 'visual', 'whitespace', 'logo',
            'pop-in', 'ui oddities', 'layout', 'styling', 'css', 'visual bug',
            'visual issue', 'display issue', 'formatting', 'alignment',
            'spacing', 'visual glitch', 'ui polish', 'aesthetics'
        ]

        # Check if this is purely cosmetic/visual (P5)
        is_cosmetic_issue = any(indicator in desc for indicator in trivial_indicators)

        # Check for functional impact keywords (if present, it's NOT just cosmetic)
        functional_impact_keywords = [
            'cannot', 'unable', 'blocked', 'broken', 'fails', 'error',
            'crash', 'data loss', 'performance', 'slow', 'timeout'
        ]
        has_functional_impact = any(keyword in desc for keyword in functional_impact_keywords)

        # If cosmetic AND no functional impact, it's P5/Trivial
        if is_cosmetic_issue and not has_functional_impact:
            reasons.append("Cosmetic/visual issue with no functional impact (P5/Trivial)")
            return 8, '; '.join(reasons)

        # Check for P2/High indicators (service crash/complete failure)
        p2_crash_indicators = [
            'fatal', 'spawn error', 'service crashed', 'service down',
            'supervisorctl', 'process not running', 'service failed',
            'exited too quickly', 'healthchecks failing', 'patching blocked',
            'service stopping', 'cannot start', 'failed to start',
            'critical service', 'control plane', 'all nodes down'
        ]

        # Check if this is a service crash (P2/High)
        is_service_crash = any(indicator in desc for indicator in p2_crash_indicators)

        # Check for data plane impact (if present, it's P1, not P2)
        data_plane_impact = any(kw in desc for kw in ['database down', 'data loss', 'outage', 'cluster down'])

        # If service crash but NOT data plane, it's P2/High
        if is_service_crash and not data_plane_impact:
            reasons.append("Service crash/failure detected (P2/High - control plane degradation)")
            return 30, '; '.join(reasons)

        # Check for P4 indicators (monitoring/reporting issues, not service degradation)
        p4_indicators = [
            'metric', 'metrics', 'monitoring', 'prometheus', 'grafana',
            'alert', 'alerting', 'false alert', 'reporting',
            'dashboard', 'visualization', 'observability'
        ]

        # Check for strong service degradation keywords FIRST (override monitoring detection)
        strong_degradation_keywords = [
            'broken', 'not replicating', 'replication broken', 'sync broken',
            'synchronization broken', 'failed to start', 'cannot start',
            'service degraded', 'crdb', 'replication'
        ]
        has_strong_degradation = any(kw in desc for kw in strong_degradation_keywords)

        # Check if this is a monitoring/metrics issue (P4) vs actual service issue
        is_monitoring_issue = any(indicator in desc for indicator in p4_indicators)

        # Check for actual service degradation keywords
        service_ok_indicators = [
            'service is fine', 'service working', 'db is working',
            'fully functional', 'no actual impact', 'appears to be fine',
            'reporting issue only', 'calculation artifact', 'metrics artifact'
        ]
        # Service is OK only if indicators are present AND no strong degradation
        service_is_ok = any(indicator in desc for indicator in service_ok_indicators) and not has_strong_degradation

        # If it's a monitoring issue AND service is OK AND no strong degradation, likely P4
        if is_monitoring_issue and service_is_ok and not has_strong_degradation:
            reasons.append("Monitoring/metrics issue with service functioning normally (P4)")
            return 16, '; '.join(reasons)
        
        # Check priority field
        priority = (self.ticket_data.get('priority') or '').lower()
        if priority in self.PRIORITY_TO_SEVERITY:
            score = self.PRIORITY_TO_SEVERITY[priority]
            # But adjust if it's clearly a monitoring issue
            if is_monitoring_issue and service_is_ok and score > 16:
                reasons.append(f"Priority '{priority}' indicates {score} points, but adjusted to 16 for monitoring-only issue")
                return 16, '; '.join(reasons)
            reasons.append(f"Priority '{priority}' indicates {score} points")
            return score, '; '.join(reasons)
        
        # Check severity field
        severity = (self.ticket_data.get('severity') or '').lower()
        for key, score in self.SEVERITY_MAPPINGS.items():
            if key in severity:
                # If severity field explicitly says P4/Low AND it's a monitoring issue
                if ('4' in key or 'low' in severity) and is_monitoring_issue:
                    reasons.append(f"Severity field '{severity}' maps to {score} points (monitoring issue)")
                    return 16, '; '.join(reasons)
                reasons.append(f"Severity field '{severity}' maps to {score} points")
                return score, '; '.join(reasons)
        
        # Check description for actual severity indicators
        # Check for degradation/broken FIRST (P2 - 30 points) before critical (P1 - 38 points)
        # This handles cases like "critical CRDB issue" which is degraded, not down
        if any(word in desc for word in ['degraded', 'slow', 'performance', 'broken', 'not replicating',
                                          'replication broken', 'sync broken', 'synchronization broken',
                                          'failed to start', 'cannot start', 'service degraded']):
            # Check if it's actual degradation or just monitoring
            # Strong degradation keywords like "broken" override monitoring downgrade
            if any(strong in desc for strong in ['broken', 'not replicating', 'replication broken',
                                                   'sync broken', 'failed to start', 'cannot start', 'crdb',
                                                   'replication']):
                reasons.append("Strong service degradation keywords found (broken/not replicating)")
                return 30, '; '.join(reasons)
            if is_monitoring_issue and service_is_ok:
                reasons.append("Performance keywords found but service OK (monitoring issue, P4)")
                return 16, '; '.join(reasons)
            reasons.append("Performance degradation keywords found")
            return 30, '; '.join(reasons)
        elif any(word in desc for word in ['critical', 'down', 'outage', 'stopped', 'crash', 'data loss']):
            # But if service is actually OK (just reporting issue), it's not critical
            if service_is_ok:
                reasons.append("Critical keywords found but service is functioning (P4)")
                return 16, '; '.join(reasons)
            reasons.append("Critical keywords found in description")
            return 38, '; '.join(reasons)
        elif any(word in desc for word in ['error', 'bug', 'issue', 'problem']):
            # For monitoring/metrics issues with no service impact
            if is_monitoring_issue and service_is_ok:
                reasons.append("Issue keywords found but monitoring-only (P4)")
                return 16, '; '.join(reasons)
            reasons.append("General issue keywords found")
            return 22, '; '.join(reasons)
        
        # Default to medium
        reasons.append("No clear severity indicators, defaulting to P3")
        return 22, '; '.join(reasons)
    
    def estimate_customer_arr(self) -> Tuple[int, str]:
        """
        Estimate Customer ARR score (0-15 points).

        Official Confluence Scoring:
        - ARR > $1M: 15 points
        - $500K < ARR <= $1M: 13 points
        - $100K < ARR <= $500K: 10 points
        - >10 low ARR customers: 8 points
        - <10 low ARR customers: 5 points
        - Single low ARR customer: 0 points

        IMPORTANT: Support tier (Premium Enterprise, Enterprise, Standard)
        is a contract-level classification and is NOT equivalent to ARR dollar
        amount. A Premium Enterprise customer can sit anywhere in the ARR
        bands. This estimator will only return a non-zero score when ARR is
        explicitly stated (manual override, explicit $X M / $X K mention, or
        multi-customer keywords). Support-tier hints are surfaced in the
        reason string but do not drive the score. Pass --arr to set the
        correct band when ARR is not in the ticket body.
        """
        import re
        reasons = []

        # 1. Manual ARR override wins over everything
        if self.manual_arr:
            arr_scores = {
                '100k-500k': 10,    # $100K < ARR <= $500K
                '500k-1M': 13,      # $500K < ARR <= $1M
                '1M-5M': 15,        # ARR > $1M
                '5M-10M': 15,       # ARR > $1M
                '10M+': 15,         # ARR > $1M
                'unknown': 0
            }
            score = arr_scores.get(self.manual_arr, 0)
            reasons.append(f"Manual ARR override: {self.manual_arr} → {score} points")
            return score, '; '.join(reasons)

        customer = (self.ticket_data.get('customer_name') or '').lower()
        desc = ((self.ticket_data.get('description') or '') + ' ' +
                (self.ticket_data.get('summary') or '')).lower()

        # 2. Explicit ARR dollar amounts in description
        for pattern, unit in self.ARR_PATTERNS:
            match = re.search(pattern, desc, re.IGNORECASE)
            if not match:
                continue
            # Extract the primary value (first capture group is the low/only end)
            try:
                primary = float(match.group(1))
            except (ValueError, IndexError):
                continue
            # Convert to dollars
            if unit == 'K':
                dollars = primary * 1_000
            else:  # 'M' or 'M-M' (use lower bound for ranges to be conservative)
                dollars = primary * 1_000_000
            # Map to band
            if dollars > 1_000_000:
                reasons.append(f"Explicit ARR ~${primary}{unit} detected (> $1M band)")
                return 15, '; '.join(reasons)
            elif dollars > 500_000:
                reasons.append(f"Explicit ARR ~${primary}{unit} detected ($500K-$1M band)")
                return 13, '; '.join(reasons)
            elif dollars > 100_000:
                reasons.append(f"Explicit ARR ~${primary}{unit} detected ($100K-$500K band)")
                return 10, '; '.join(reasons)
            else:
                reasons.append(f"Explicit ARR ~${primary}{unit} detected (low ARR band)")
                return 0, '; '.join(reasons)

        # 3. Multiple customers heuristic
        multiple_customers_keywords = [
            'multiple customers', 'several customers', 'many customers',
            'numerous customers', 'various customers'
        ]
        if any(keyword in desc for keyword in multiple_customers_keywords):
            if any(word in desc for word in ['>10', 'more than 10', 'over 10', 'numerous']):
                reasons.append(">10 low ARR customers mentioned")
                return 8, '; '.join(reasons)
            else:
                reasons.append("<10 low ARR customers mentioned")
                return 5, '; '.join(reasons)

        # 4. Support tier / label hints — surface as context only, do NOT score.
        tier_hint = None
        support_tier = (self.ticket_data.get('support_tier') or '').lower()
        if support_tier:
            tier_hint = support_tier
        else:
            for tier, keywords in self.SUPPORT_TIER_KEYWORDS.items():
                for kw in keywords:
                    if kw in desc:
                        tier_hint = tier
                        break
                if tier_hint:
                    break
            if not tier_hint:
                labels_str = ' '.join(self.ticket_data.get('labels', [])).lower()
                if 'enterprise' in labels_str or 'premium' in labels_str:
                    tier_hint = 'enterprise_or_premium (from labels)'

        if tier_hint:
            reasons.append(
                f"Support tier hint: '{tier_hint}'. Tier does not imply an ARR band; "
                f"pass --arr to set the correct band. Defaulting to 0."
            )
            return 0, '; '.join(reasons)

        # 5. Default: no ARR signal
        if customer or 'customer' in desc:
            reasons.append("Customer mentioned but ARR unknown; pass --arr for correct scoring")
        else:
            reasons.append("No customer information found")
        return 0, '; '.join(reasons)
    
    def estimate_sla_breach(self) -> Tuple[int, str]:
        """Estimate SLA Breach score (0 or 8 points).

        IMPORTANT: This component ONLY applies to Redis Cloud.
        For ACRE (Azure Cache for Redis Enterprise), always return 0.
        """
        reasons = []

        desc = ((self.ticket_data.get('description') or '') + ' ' +
                (self.ticket_data.get('summary') or '') + ' ' +
                (self.ticket_data.get('rca') or '')).lower()

        # Check for ACRE - always score 0 for ACRE tickets
        acre_indicators = ['acre', 'azure cache for redis', 'azure redis']
        if any(indicator in desc for indicator in acre_indicators):
            reasons.append("ACRE detected - Azure owns SLA (always 0 points)")
            return 0, '; '.join(reasons)

        # Check for explicit "no SLA breach" or "no downtime" statements first
        no_breach_indicators = [
            'no sla breach', 'no downtime', 'no shard downtime',
            'no actual', 'shards stable', 'service is fine',
            'fully functional', 'no service impact'
        ]

        if any(indicator in desc for indicator in no_breach_indicators):
            reasons.append("No SLA breach (service confirmed stable/functional)")
            return 0, '; '.join(reasons)
        
        # Check for SLA breach keywords
        for keyword in self.SLA_KEYWORDS:
            if keyword in desc:
                reasons.append(f"SLA breach keyword '{keyword}' found")
                return 8, '; '.join(reasons)
        
        # Check for downtime duration (but not if it's in a negative context)
        if re.search(r'(\d+)\s*(hour|hr|minute|min).*down', desc) and 'no' not in desc[:desc.find('down')] if 'down' in desc else False:
            reasons.append("Downtime duration mentioned, potential SLA impact")
            return 8, '; '.join(reasons)
        
        # Check status/labels for severity
        priority = self.ticket_data.get('priority') or ''
        if priority and priority.lower() in ['blocker', 'critical', 'highest']:
            reasons.append("Critical priority suggests potential SLA breach")
            return 8, '; '.join(reasons)
        
        reasons.append("No SLA breach indicators found")
        return 0, '; '.join(reasons)
    
    def estimate_frequency(self) -> Tuple[int, str]:
        """Estimate Frequency score (0-16 points)."""
        reasons = []

        desc = ((self.ticket_data.get('description') or '') + ' ' +
                (self.ticket_data.get('summary') or '')).lower()

        # Check for systemic issues affecting all users/instances
        systemic_indicators = [
            'all users', 'everyone', 'every user', 'all instances',
            'all deployments', 'affects version', 'affects all',
            'every deployment', 'all environments', 'every instance',
            'systemic', 'widespread', 'global issue', 'affects everyone'
        ]

        # Check for version-specific issues (e.g., "v8.0.X", "version 8.0")
        version_pattern = r'v\d+\.\d+|version \d+\.\d+'

        # If it's a systemic issue or version-specific bug, it affects multiple users
        if any(indicator in desc for indicator in systemic_indicators) or re.search(version_pattern, desc):
            reasons.append("Systemic issue affecting all users/instances of a version")
            return 16, '; '.join(reasons)

        # Check for explicit frequency mentions
        if re.search(r'(\d+)\s*times', desc) or re.search(r'(\d+)\s*occurrences', desc):
            match = re.search(r'(\d+)\s*(times|occurrences)', desc)
            if match:
                count = int(match.group(1))
                if count > 4:
                    reasons.append(f"{count} occurrences mentioned")
                    return 16, '; '.join(reasons)
                elif count >= 2:
                    reasons.append(f"{count} occurrences mentioned")
                    return 8, '; '.join(reasons)

        # Check for frequency keywords (check 'always' first, then 'multiple', then 'single')
        for keyword in self.FREQUENCY_KEYWORDS['always']:
            if keyword in desc:
                reasons.append(f"Always/persistent keyword '{keyword}' found")
                return 16, '; '.join(reasons)

        for keyword in self.FREQUENCY_KEYWORDS['multiple']:
            if keyword in desc:
                reasons.append(f"Multiple occurrence keyword '{keyword}' found")
                return 16, '; '.join(reasons)

        for keyword in self.FREQUENCY_KEYWORDS['single']:
            if keyword in desc:
                reasons.append(f"Single occurrence keyword '{keyword}' found")
                return 0, '; '.join(reasons)

        # Check for "similar to" or references to other tickets
        if 'similar to' in desc or 'same as' in desc or re.search(r'RED-\d+', desc):
            reasons.append("References to similar issues found")
            return 8, '; '.join(reasons)

        reasons.append("No clear frequency indicators, assuming single occurrence")
        return 0, '; '.join(reasons)
    
    def estimate_workaround(self) -> Tuple[int, str]:
        """
        Estimate Workaround score (5-15 points).

        WORKAROUND ACCEPTANCE PRINCIPLE:
        The score depends not just on workaround availability, but on whether the customer
        has ACCEPTED the workaround. Conservative scoring philosophy: "err on the side of 15
        if workaround has not been accepted by the customer."

        Scoring Tiers (Official Confluence):
        - 15 points: No workaround exists OR workaround suggested but NOT accepted
        - 12 points: Workaround accepted, but has performance/operational impact
        - 10 points: Workaround accepted, complex but no business impact
        - 5 points:  Workaround accepted, simple with no business impact

        Workaround States:
        1. Suggested but unaccepted: Treat as "no workaround" (15 points)
           - Engineer proposed solution in comments
           - Customer has not confirmed they will use it
           - Customer concerned about risks/side effects

        2. Accepted with impact: Score 12 points
           - Customer agreed to use workaround
           - Causes performance degradation, operational burden, or data limitations
           - Examples: manual data cleanup, reduced performance, operational complexity

        3. Accepted, complex, no impact: Score 10 points
           - Customer agreed to use workaround
           - Requires significant effort but no ongoing impact
           - Examples: configuration changes, code refactoring, migration steps

        4. Accepted, simple, no impact: Score 5 points
           - Customer agreed to use workaround
           - Easy to implement, no drawbacks
           - Examples: UI alternative, simple config change, feature toggle

        Real-World Example (RED-174782):
        - Issue: Terraform provider swaps regionId and TgwId in PUT requests
        - Suggested workaround: Flip values in TF script (against best practices, could break things)
        - Customer response: None (workaround not accepted)
        - Score: 15 points (treated as "no workaround")
        - Rationale: Workaround suggested but customer hasn't explicitly accepted it,
                     and they expressed concerns about it breaking other things

        NOTE: This method uses keyword detection from ticket description and workaround
        field. Manual review may be needed for edge cases where acceptance is unclear.
        """
        reasons = []

        workaround_text = self.ticket_data.get('workaround') or ''
        desc = (self.ticket_data.get('description') or '') + ' ' + (self.ticket_data.get('summary') or '')
        combined = (workaround_text + ' ' + desc).lower()

        # Check for no workaround first (15 points)
        # This includes cases where workaround is explicitly stated as not available
        if any(kw in combined for kw in self.WORKAROUND_KEYWORDS['none']):
            reasons.append("No workaround available, fix required")
            return 15, '; '.join(reasons)

        # Check if fix/patch is the only solution (15 points)
        # If fix/patch mentioned without workaround, assume no workaround exists
        if 'fix' in combined or 'patch' in combined or 'requires version' in combined:
            if 'workaround' not in combined:
                reasons.append("Fix/patch required, no workaround")
                return 15, '; '.join(reasons)

        # If workaround is explicitly mentioned, analyze acceptance and characteristics
        has_workaround = 'workaround' in combined or 'use instead' in combined or 'alternative' in combined

        if has_workaround:
            # Check for performance/operational impact (12 points)
            # Keywords indicate workaround exists but causes degradation or burden
            if any(kw in combined for kw in self.WORKAROUND_KEYWORDS['with_impact']):
                reasons.append("Workaround with performance/operational impact detected")
                return 12, '; '.join(reasons)

            # Check for complexity (10 points)
            # Keywords indicate workaround exists, is complex, but no ongoing impact
            elif any(kw in combined for kw in self.WORKAROUND_KEYWORDS['complex']):
                reasons.append("Complex workaround found")
                return 10, '; '.join(reasons)

            # Simple workaround (5 points)
            # Workaround mentioned without complexity/impact indicators
            else:
                reasons.append("Simple workaround found")
                return 5, '; '.join(reasons)

        # Check if workaround field is explicitly filled (but keyword not in description)
        # This handles structured Jira fields where workaround documented separately
        if workaround_text and workaround_text.strip() and workaround_text.lower() not in ['nan', 'none', 'n/a']:
            # Analyze workaround field content
            if any(kw in workaround_text.lower() for kw in self.WORKAROUND_KEYWORDS['with_impact']):
                reasons.append("Workaround field shows performance/operational impact")
                return 12, '; '.join(reasons)
            elif any(kw in workaround_text.lower() for kw in self.WORKAROUND_KEYWORDS['complex']):
                reasons.append("Workaround field shows complex workaround")
                return 10, '; '.join(reasons)
            else:
                reasons.append("Workaround field populated")
                return 10, '; '.join(reasons)

        # Default: unclear if workaround exists (conservative scoring = 10 points)
        # When detection is uncertain, assume moderate complexity rather than scoring extremes
        reasons.append("No clear workaround information, assuming complex workaround needed")
        return 10, '; '.join(reasons)
    
    def estimate_rca_action_item(self) -> Tuple[int, str]:
        """Estimate RCA Action Item score (0 or 8 points).

        IMPORTANT:
        - 8 points: Ticket is a follow-up action item from a PAST, *formal* RCA
          Jira (i.e. a Cloud production incident that already has an RCA ticket).
        - 0 points: Everything else — including tickets that *mention* RCA,
          request an RCA, or contain RCA-related keywords without a confirmed
          formal RCA Jira.

        Rule: Generating RCA = 0 points, Generated BY RCA = 8 points.

        The score is determined by asking the operator, not by keyword detection,
        because false positives (e.g. "RCA needed" in the ticket body) would
        inflate scores for issues that do not yet have a completed RCA.
        """
        # If the answer was pre-set (e.g. passed as a CLI flag or by the caller),
        # use it directly without prompting.
        if self.rca_jira_exists is True:
            return 8, "Formal RCA Jira confirmed by operator — follow-up action item"
        if self.rca_jira_exists is False:
            return 0, "No formal RCA Jira — operator confirmed"

        # Interactive prompt: ask the operator at runtime.
        print()
        print("─" * 60)
        print("RCA ACTION ITEM — MANUAL CONFIRMATION REQUIRED")
        print("─" * 60)
        print("Score is 8 points ONLY if a formal RCA Jira already exists")
        print("for this issue (i.e. it was a Cloud production incident that")
        print("completed an RCA and this ticket is a follow-up action item).")
        print()
        print("Do NOT score 8 just because the ticket body mentions 'RCA'.")
        print()

        while True:
            answer = input("Does a formal RCA Jira exist for this issue? [y/n]: ").strip().lower()
            if answer in ('y', 'yes'):
                self.rca_jira_exists = True
                return 8, "Formal RCA Jira confirmed by operator — follow-up action item"
            elif answer in ('n', 'no'):
                self.rca_jira_exists = False
                return 0, "No formal RCA Jira — operator confirmed"
            else:
                print("  Please enter y or n.")
    
    def estimate_all_components(self) -> Dict:
        """Estimate all impact score components."""
        impact_severity, severity_reason = self.estimate_impact_severity()
        customer_arr, arr_reason = self.estimate_customer_arr()
        sla_breach, sla_reason = self.estimate_sla_breach()
        frequency, freq_reason = self.estimate_frequency()
        workaround, work_reason = self.estimate_workaround()
        rca_action_item, rca_reason = self.estimate_rca_action_item()
        
        # For now, multipliers are 0 (could be enhanced with more analysis)
        support_multiplier = 0.0
        account_multiplier = 0.0
        
        components = {
            'impact_severity': {
                'score': impact_severity,
                'reason': severity_reason
            },
            'customer_arr': {
                'score': customer_arr,
                'reason': arr_reason
            },
            'sla_breach': {
                'score': sla_breach,
                'reason': sla_reason
            },
            'frequency': {
                'score': frequency,
                'reason': freq_reason
            },
            'workaround': {
                'score': workaround,
                'reason': work_reason
            },
            'rca_action_item': {
                'score': rca_action_item,
                'reason': rca_reason
            },
            'support_multiplier': support_multiplier,
            'account_multiplier': account_multiplier
        }
        
        return components
    
    def calculate_impact_score(self, components: Dict) -> Tuple[float, float, str]:
        """Calculate final impact score from components."""
        base_score = (
            components['impact_severity']['score'] +
            components['customer_arr']['score'] +
            components['sla_breach']['score'] +
            components['frequency']['score'] +
            components['workaround']['score'] +
            components['rca_action_item']['score']
        )
        
        total_multiplier = 1 + components['support_multiplier'] + components['account_multiplier']
        final_score = base_score * total_multiplier
        
        # Classify priority
        if final_score >= 90:
            priority = 'CRITICAL'
        elif final_score >= 70:
            priority = 'HIGH'
        elif final_score >= 50:
            priority = 'MEDIUM'
        elif final_score >= 30:
            priority = 'LOW'
        else:
            priority = 'MINIMAL'
        
        return base_score, round(final_score, 1), priority
    
    def display_results(self, components: Dict, base_score: float, final_score: float, priority: str):
        """Display estimation results."""
        print("\n" + "="*80)
        print("INTELLIGENT IMPACT SCORE ESTIMATION")
        print("="*80)
        
        issue_key = self.ticket_data.get('issue_key') or self.ticket_data.get('ticket_id') or 'Unknown'
        summary = self.ticket_data.get('summary') or ''

        print(f"\nTicket: {issue_key}")
        print(f"Summary: {summary[:70]}..." if summary and len(summary) > 70 else f"Summary: {summary}")
        
        print("\n" + "-"*80)
        print("COMPONENT BREAKDOWN")
        print("-"*80)
        
        print(f"\n1. Impact & Severity: {components['impact_severity']['score']:2d} points")
        print(f"   → {components['impact_severity']['reason']}")
        
        print(f"\n2. Customer ARR: {components['customer_arr']['score']:2d} points")
        print(f"   → {components['customer_arr']['reason']}")
        
        print(f"\n3. SLA Breach: {components['sla_breach']['score']:2d} points")
        print(f"   → {components['sla_breach']['reason']}")
        
        print(f"\n4. Frequency: {components['frequency']['score']:2d} points")
        print(f"   → {components['frequency']['reason']}")
        
        print(f"\n5. Workaround: {components['workaround']['score']:2d} points")
        print(f"   → {components['workaround']['reason']}")
        
        print(f"\n6. RCA Action Item: {components['rca_action_item']['score']:2d} points")
        print(f"   → {components['rca_action_item']['reason']}")
        
        print("\n" + "-"*80)
        print(f"BASE SCORE: {base_score:.0f} points")
        
        if components['support_multiplier'] > 0 or components['account_multiplier'] > 0:
            print(f"\nMultipliers:")
            print(f"  Support: {components['support_multiplier']:.0%}")
            print(f"  Account: {components['account_multiplier']:.0%}")
        
        print("\n" + "="*80)
        print(f"FINAL IMPACT SCORE: {final_score} points")
        print(f"PRIORITY LEVEL: {priority}")
        print("="*80)


def main():
    parser = argparse.ArgumentParser(
        description='Intelligently estimate impact scores from Jira/Zendesk ticket exports',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Supported formats:
  Jira:     PDF, Excel (.xlsx), XML, Word (.docx)
  Zendesk:  PDF

Examples:
  %(prog)s RED-12345.pdf
  %(prog)s zendesk_ticket_789.pdf --output scores.json
  %(prog)s jira_export.xlsx --verbose
        """
    )

    parser.add_argument(
        'file',
        help='Path to ticket export file (PDF/Excel/XML/Word)'
    )
    
    parser.add_argument(
        '-o', '--output',
        help='Output JSON file for results',
        default=None
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show detailed ticket information'
    )

    parser.add_argument(
        '--arr',
        choices=['100k-500k', '500k-1M', '1M-5M', '5M-10M', '10M+', 'unknown'],
        help='Customer ARR range (if not detected from ticket export). Use this when Zendesk PDF exports do not include ARR tags.'
    )

    args = parser.parse_args()
    
    # Validate file exists
    if not Path(args.file).exists():
        print(f"Error: File not found: {args.file}")
        sys.exit(1)
    
    print("="*80)
    print("INTELLIGENT IMPACT SCORE ESTIMATOR")
    print("="*80)
    print(f"\nAnalyzing: {args.file}")
    print(f"Format: {Path(args.file).suffix.upper()}\n")
    
    try:
        # Initialize estimator (without ARR for now)
        estimator = IntelligentImpactEstimator(args.file)

        # Load data
        estimator.load_data()

        # Extract ticket info
        print("\nExtracting ticket information...")
        ticket_info = estimator.extract_ticket_info()

        if args.verbose:
            print("\nTicket Data:")
            for key, value in ticket_info.items():
                if value:
                    display_val = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
                    print(f"  {key}: {display_val}")

        # Handle ARR - check if provided via CLI or prompt user
        arr_value = args.arr
        if not arr_value:
            # Check if customer info exists in ticket
            customer = ticket_info.get('customer_name') or ticket_info.get('customer')
            if customer and customer not in ['None', 'N/A', '-', '']:
                print(f"\n⚠️  Customer detected: {customer}")
                print("⚠️  ARR information may not be available in PDF exports.")
                print("    If you know the customer ARR range, please provide it for accurate scoring.")
                print("\nAvailable ARR ranges:")
                print("  1) 100k-500k")
                print("  2) 500k-1M")
                print("  3) 1M-5M")
                print("  4) 5M-10M")
                print("  5) 10M+")
                print("  6) unknown (skip)")

                choice = input("\nEnter number (1-6) or press Enter to skip: ").strip()
                arr_map = {
                    '1': '100k-500k',
                    '2': '500k-1M',
                    '3': '1M-5M',
                    '4': '5M-10M',
                    '5': '10M+',
                    '6': 'unknown'
                }
                arr_value = arr_map.get(choice)
                if arr_value:
                    print(f"✓ Using ARR: {arr_value}\n")

        # Set manual ARR on estimator
        estimator.manual_arr = arr_value

        # Estimate components
        print("\nEstimating impact score components...")
        components = estimator.estimate_all_components()
        
        # Calculate final score
        base_score, final_score, priority = estimator.calculate_impact_score(components)
        
        # Display results
        estimator.display_results(components, base_score, final_score, priority)
        
        # Save to JSON if requested
        if args.output:
            result_data = {
                'ticket': ticket_info.get('issue_key', 'Unknown'),
                'summary': ticket_info.get('summary', ''),
                'components': {
                    'impact_severity': components['impact_severity']['score'],
                    'customer_arr': components['customer_arr']['score'],
                    'sla_breach': components['sla_breach']['score'],
                    'frequency': components['frequency']['score'],
                    'workaround': components['workaround']['score'],
                    'rca_action_item': components['rca_action_item']['score'],
                    'support_multiplier': components['support_multiplier'],
                    'account_multiplier': components['account_multiplier'],
                },
                'reasoning': {
                    'impact_severity': components['impact_severity']['reason'],
                    'customer_arr': components['customer_arr']['reason'],
                    'sla_breach': components['sla_breach']['reason'],
                    'frequency': components['frequency']['reason'],
                    'workaround': components['workaround']['reason'],
                    'rca_action_item': components['rca_action_item']['reason'],
                },
                'scores': {
                    'base_score': base_score,
                    'final_score': final_score,
                    'priority': priority
                }
            }
            
            with open(args.output, 'w') as f:
                json.dump(result_data, f, indent=2)
            
            print(f"\n✓ Results saved to {args.output}")
        
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
