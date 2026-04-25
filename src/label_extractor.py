#!/usr/bin/env python3
"""
Label Keyword Extraction for Jira Tickets

Extracts short, searchable keywords from ticket content instead of generic labels.
Examples: "fedex", "crdb", "ovc", "replication"
"""

import re
from typing import List, Set


class LabelExtractor:
    """Extract keyword-based labels from ticket content."""

    # Technical keywords to extract (lowercase)
    # NOTE: Keep this focused on specific, actionable labels for R&D filtering
    # Avoid overly generic terms (master, slave, cluster, database, etc.)
    TECHNICAL_KEYWORDS = {
        # Redis components (specific)
        'crdb', 'active-active', 'aa', 'sentinel', 'proxy', 'dmcproxy',

        # CRDB-specific (actionable)
        'ovc', 'vector-clock',

        # Redis Cloud / Infrastructure (specific)
        'acre', 'azure', 'aws', 'gcp', 'kubernetes', 'k8s',
        'rlec',

        # Security (specific)
        'acl', 'rbac', 'ssl', 'tls', 'certificate',

        # Features (specific enough to be useful as labels)
        'lua', 'rdb', 'aof',
        'streams', 'pubsub', 'search', 'json', 'timeseries', 'graph', 'bloom',

        # RDI / CDC
        'rdi', 'debezium', 'cdc', 'oracle', 'poc',
    }

    # Generic keywords to EXCLUDE (too common, not useful for filtering)
    EXCLUDED_KEYWORDS = {
        'redis', 'cluster', 'database', 'shard', 'replica', 'slave', 'master',
        'replication', 'sync', 'synchronization', 'conflict', 'resolution', 'merge',
        'memory', 'cpu', 'disk', 'network', 'latency',
        'connection', 'authentication', 'auth', 'encryption', 'cloud', 'enterprise',
        'backup', 'restore', 'recovery', 'restart', 'deployment', 'scaling', 'sharding',
        'scripts', 'persistence',
        'crash', 'timeout', 'upgrade', 'migration', 'failover', 'performance', 'modules',
    }

    # Module names that appear in version strings (e.g., "search:8.2.8").
    # These should only be extracted as labels if they appear as substantive
    # topic references, not just as part of an installed-modules list.
    MODULE_VERSION_PATTERN = re.compile(
        r'\b(search|rejson|redisjson|redisearch|bf|bloom|timeseries|graph|redisai)'
        r'[:\s]*\d+\.\d+',
        re.IGNORECASE
    )

    # Customer name patterns (extract from summary)
    CUSTOMER_PATTERN = re.compile(r'^([A-Za-z0-9]+(?:\s+[A-Za-z0-9]+)?)\s*-', re.IGNORECASE)

    def __init__(self):
        self.technical_keywords = self.TECHNICAL_KEYWORDS

    def extract_labels(
        self,
        summary: str,
        description: str = "",
        customer_name: str = None,
        source: str = None,
        max_labels: int = 5
    ) -> List[str]:
        """
        Extract keyword-based labels from ticket content.

        Args:
            summary: Jira ticket summary/title
            description: Jira ticket description
            customer_name: Customer name (optional, will be extracted from summary if not provided)
            source: Source system (e.g., "zendesk") - typically omitted for R&D tickets
            max_labels: Maximum number of labels to return (default: 5)

        Returns:
            List of keyword labels (e.g., ["fedex", "crdb", "ovc"])
        """
        labels: Set[str] = set()

        # Include source only if explicitly requested (not needed for R&D tickets)
        if source:
            labels.add(source.lower())

        # Extract customer name
        customer = self._extract_customer(summary, customer_name)
        if customer:
            labels.add(customer)

        # Extract technical keywords from summary
        summary_keywords = self._extract_technical_keywords(summary)
        labels.update(summary_keywords)

        # Extract technical keywords from description (if needed)
        if len(labels) < max_labels and description:
            description_keywords = self._extract_technical_keywords(description)
            labels.update(description_keywords)

        # Convert to list and prioritize: source first, customer second, then alphabetical
        labels_list = list(labels)

        # Separate priority labels from others
        priority_labels = []
        other_labels = []

        for label in labels_list:
            if source and label == source.lower():
                priority_labels.insert(0, label)  # Source is highest priority
            elif label == customer:
                if len(priority_labels) > 0:
                    priority_labels.insert(1, label)  # Customer is second priority
                else:
                    priority_labels.append(label)
            else:
                other_labels.append(label)

        # Sort other labels alphabetically
        other_labels.sort()

        # Combine priority labels with other labels, limit to max_labels
        return (priority_labels + other_labels)[:max_labels]

    def _extract_customer(self, summary: str, customer_name: str = None) -> str:
        """
        Extract customer name from summary or use provided name.

        Args:
            summary: Jira ticket summary
            customer_name: Explicit customer name (optional)

        Returns:
            Lowercase customer name (e.g., "fedex", "wells-fargo")
        """
        if customer_name:
            # Use provided name, normalize to lowercase and replace spaces with hyphens
            return customer_name.lower().replace(' ', '-')

        # Extract from summary pattern: "Customer - Issue description"
        match = self.CUSTOMER_PATTERN.match(summary)
        if match:
            customer = match.group(1).strip()
            # Normalize: lowercase, replace spaces with hyphens
            return customer.lower().replace(' ', '-')

        return None

    # Keywords that overlap with Redis module names — only label them if they
    # appear outside of a "module:version" context (e.g., as a topic in the
    # summary or as a command prefix like FT.SEARCH).
    _MODULE_NAME_KEYWORDS = {
        'search', 'json', 'timeseries', 'graph', 'bloom', 'modules',
    }

    def _extract_technical_keywords(self, text: str) -> Set[str]:
        """
        Extract technical keywords from text.

        Args:
            text: Text to analyze

        Returns:
            Set of lowercase technical keywords found in text
        """
        if not text:
            return set()

        text_lower = text.lower()
        found_keywords = set()

        # Strip out module version strings so "search:8.2.8" doesn't match "search"
        text_without_versions = self.MODULE_VERSION_PATTERN.sub('', text_lower)

        for keyword in self.technical_keywords:
            pattern = r'\b' + re.escape(keyword) + r'\b'

            if keyword in self._MODULE_NAME_KEYWORDS:
                # For module-overlapping keywords, only match in the version-stripped text
                if re.search(pattern, text_without_versions):
                    found_keywords.add(keyword)
            else:
                if re.search(pattern, text_lower):
                    found_keywords.add(keyword)

        return found_keywords


def extract_labels(
    summary: str,
    description: str = "",
    customer_name: str = None,
    source: str = None,
    max_labels: int = 5
) -> List[str]:
    """
    Convenience function to extract labels without instantiating class.

    Args:
        summary: Jira ticket summary/title
        description: Jira ticket description
        customer_name: Customer name (optional)
        source: Source system (e.g., "zendesk") - typically omitted for R&D tickets
        max_labels: Maximum number of labels to return (default: 5)

    Returns:
        List of keyword labels (focused, technical labels only)

    Examples:
        >>> extract_labels("FedEx - CRDB slave OVC higher than master causing replication failure")
        ['crdb', 'fedex', 'ovc']

        >>> extract_labels("Wells Fargo - Azure ACRE deployment timeout")
        ['acre', 'azure', 'timeout', 'wells-fargo']
    """
    extractor = LabelExtractor()
    return extractor.extract_labels(summary, description, customer_name, source, max_labels)


if __name__ == "__main__":
    # Test cases
    print("Testing Label Extractor\n" + "="*80)

    # Test 1: FedEx CRDB OVC issue
    summary1 = "FedEx - CRDB slave OVC higher than master causing local and inter-CRDB replication failure"
    labels1 = extract_labels(summary1)
    print(f"\nTest 1: {summary1}")
    print(f"Labels: {labels1}")

    # Test 2: Wells Fargo Azure issue
    summary2 = "Wells Fargo - node_mgr crash due to missing system_user_password after upgrade"
    labels2 = extract_labels(summary2)
    print(f"\nTest 2: {summary2}")
    print(f"Labels: {labels2}")

    # Test 3: With description
    summary3 = "ABC Corp - Database connection timeout"
    description3 = "Customer experiencing SSL certificate validation errors with CRDB replication"
    labels3 = extract_labels(summary3, description3)
    print(f"\nTest 3: {summary3}")
    print(f"Description: {description3}")
    print(f"Labels: {labels3}")

    # Test 4: Azure ACRE
    summary4 = "XYZ Inc - ACRE deployment failure on Azure"
    labels4 = extract_labels(summary4)
    print(f"\nTest 4: {summary4}")
    print(f"Labels: {labels4}")
