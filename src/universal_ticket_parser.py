#!/usr/bin/env python3
"""
Universal Ticket Parser - Multi-Format Support

Handles Jira and Zendesk ticket exports in multiple formats:
- Jira: PDF, Excel (.xlsx), XML, Word (.docx)
- Zendesk: PDF

Extracts ticket data and normalizes it into a standard dictionary format
for use by the intelligent estimator.
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Union
import pandas as pd

# PDF support
try:
    import fitz  # PyMuPDF
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# Word document support
try:
    import docx
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

# XML support
try:
    from lxml import etree
    XML_AVAILABLE = True
except ImportError:
    XML_AVAILABLE = False


class UniversalTicketParser:
    """Parse ticket exports from multiple formats (Jira/Zendesk)."""

    SUPPORTED_FORMATS = {
        'jira': ['.pdf', '.xlsx', '.xml', '.docx'],
        'zendesk': ['.pdf']
    }

    # Minimum image dimensions to extract (filters out logos/icons)
    MIN_IMAGE_WIDTH = 500
    MIN_IMAGE_HEIGHT = 100

    def __init__(self, file_path: Union[str, Path]):
        """Initialize parser with file path."""
        self.file_path = Path(file_path)
        self.file_ext = self.file_path.suffix.lower()
        self.source_type = None  # 'jira' or 'zendesk'
        self.raw_text = ""
        self.ticket_data = {}
        self.extracted_images = []  # List of extracted image info

    def parse(self) -> Dict:
        """Parse the ticket file and return normalized data."""
        if not self.file_path.exists():
            raise FileNotFoundError(f"File not found: {self.file_path}")

        # Route to appropriate parser based on extension
        if self.file_ext == '.pdf':
            self.ticket_data = self._parse_pdf()
        elif self.file_ext == '.xlsx':
            self.ticket_data = self._parse_excel()
        elif self.file_ext == '.xml':
            self.ticket_data = self._parse_xml()
        elif self.file_ext == '.docx':
            self.ticket_data = self._parse_docx()
        else:
            raise ValueError(f"Unsupported file format: {self.file_ext}")

        return self.ticket_data

    def _parse_pdf(self) -> Dict:
        """Parse PDF export (Jira or Zendesk)."""
        if not PDF_AVAILABLE:
            raise ImportError("PyMuPDF (pymupdf) required for PDF support. Install: pip install pymupdf")

        # Extract text from PDF
        doc = fitz.open(self.file_path)
        self.raw_text = ""

        for page in doc:
            self.raw_text += page.get_text()

        doc.close()

        # Detect source type (Jira vs Zendesk)
        if self._is_zendesk_pdf():
            return self._parse_zendesk_pdf()
        else:
            return self._parse_jira_pdf()

    def extract_images(self, output_dir: Optional[Union[str, Path]] = None) -> List[Dict]:
        """
        Extract meaningful images from PDF (filters out logos/icons).

        Args:
            output_dir: Directory to save images. If None, uses output/images_<ticket_id>/

        Returns:
            List of dicts with image info: {path, filename, width, height, page, description}
        """
        if not PDF_AVAILABLE:
            raise ImportError("PyMuPDF (pymupdf) required for image extraction")

        if self.file_ext != '.pdf':
            return []

        # Determine ticket ID for output folder
        ticket_id = self.ticket_data.get('ticket_id') or self.ticket_data.get('issue_key') or 'unknown'
        if ticket_id == 'unknown':
            # Try to extract from filename
            import re
            match = re.search(r'(\d{5,7})', self.file_path.name)
            if match:
                ticket_id = match.group(1)

        # Set up output directory
        if output_dir is None:
            output_dir = Path('output') / f'images_{ticket_id}'
        else:
            output_dir = Path(output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)

        # Extract images
        doc = fitz.open(self.file_path)
        extracted = []

        for page_num, page in enumerate(doc):
            images = page.get_images()

            for img_idx, img in enumerate(images):
                xref = img[0]
                try:
                    base_image = doc.extract_image(xref)
                    width = base_image['width']
                    height = base_image['height']

                    # Filter out small images (logos, icons, etc.)
                    if width < self.MIN_IMAGE_WIDTH or height < self.MIN_IMAGE_HEIGHT:
                        continue

                    # Save image
                    ext = base_image['ext']
                    filename = f'page{page_num + 1}_img{img_idx + 1}_{width}x{height}.{ext}'
                    filepath = output_dir / filename

                    with open(filepath, 'wb') as f:
                        f.write(base_image['image'])

                    # Store image info
                    img_info = {
                        'path': str(filepath),
                        'relative_path': f'images_{ticket_id}/{filename}',
                        'filename': filename,
                        'width': width,
                        'height': height,
                        'page': page_num + 1,
                        'description': ''  # To be filled by Claude analysis
                    }
                    extracted.append(img_info)

                except Exception as e:
                    # Skip images that can't be extracted
                    continue

        doc.close()
        self.extracted_images = extracted
        return extracted

    def _is_zendesk_pdf(self) -> bool:
        """Detect if PDF is from Zendesk."""
        # FIRST: Check filename - most reliable indicator
        filename_lower = self.file_path.name.lower()
        if 'zendesk' in filename_lower:
            return True

        text_lower = self.raw_text.lower()

        # SECOND: Check for zendesk.com URL in content
        if 'zendesk.com' in text_lower:
            return True

        # Check for strong Jira indicators first (to avoid false positives)
        jira_indicators = [
            'project:', 'issue type:', 'fix versions:', 'affects versions:',
            'resolution:', 'components:', 'sprint:'
        ]
        jira_matches = sum(1 for indicator in jira_indicators if indicator in text_lower)

        # If we find 3+ Jira indicators, it's definitely Jira
        if jira_matches >= 3:
            return False

        # Check for Zendesk-specific indicators (relaxed - now only need 2)
        zendesk_indicators = [
            'ticket #', 'requester', 'submitted', 'received via',
            'sla package', 'zendesk'
        ]
        zendesk_matches = sum(1 for indicator in zendesk_indicators if indicator in text_lower)

        # If 2+ Zendesk indicators match, likely Zendesk
        return zendesk_matches >= 2

    def _parse_zendesk_pdf(self) -> Dict:
        """Parse Zendesk PDF export."""
        self.source_type = 'zendesk'
        data = {
            'source': 'zendesk',
            'ticket_id': self._extract_zendesk_ticket_id(),
            'summary': self._extract_zendesk_summary(),
            'description': self._extract_zendesk_description(),
            'priority': self._extract_zendesk_field(r'Priority:\s*(\w+)'),
            'status': self._extract_zendesk_field(r'Status:\s*(\w+)'),
            'requester': self._extract_zendesk_field(r'Requester:\s*(.+)'),
            'assignee': self._extract_zendesk_field(r'Assignee:\s*(.+)'),
            'created': self._extract_zendesk_field(r'Created:\s*(.+)'),
            'updated': self._extract_zendesk_field(r'Updated:\s*(.+)'),
            'labels': self._extract_zendesk_tags(),
            'support_tier': self._extract_support_tier(),  # Extract support tier for ARR estimation
            'raw_text': self.raw_text,
            'extracted_images': []  # Will be populated by extract_images()
        }

        return data

    def _extract_zendesk_ticket_id(self) -> Optional[str]:
        """
        Extract Zendesk ticket ID with improved logic.

        Priority order:
        1. Filename (most reliable): redislabs.zendesk.com_tickets_149320_print.pdf
        2. First line of PDF (primary ticket): #149320 Customer - Summary
        3. Fallback to any "Ticket #" reference
        """
        # Method 1: Extract from filename (most reliable)
        filename = self.file_path.name
        filename_match = re.search(r'tickets?_(\d+)', filename, re.IGNORECASE)
        if filename_match:
            return filename_match.group(1)

        # Method 2: Look for #XXXXXX pattern in first 2000 chars (primary ticket)
        first_section = self.raw_text[:2000]
        primary_match = re.search(r'#(\d{5,7})\s+[\w\s]+-', first_section)
        if primary_match:
            return primary_match.group(1)

        # Method 3: Fallback to "Ticket #" pattern anywhere
        fallback_match = re.search(r'Ticket #(\d+)', self.raw_text, re.IGNORECASE)
        return fallback_match.group(1) if fallback_match else None

    def _extract_zendesk_summary(self) -> Optional[str]:
        """
        Extract Zendesk ticket summary/subject.

        Try multiple patterns:
        1. First line: #149320 FedEx - Summary text
        2. Subject: field
        """
        # Method 1: Extract from first line (#TICKET_ID Customer - Summary)
        first_line_match = re.search(r'#\d{5,7}\s+(.+?)(?=\n|$)', self.raw_text[:500])
        if first_line_match:
            summary = first_line_match.group(1).strip()
            # Remove any trailing metadata
            summary = re.sub(r'\s+Submitted$', '', summary)
            return summary

        # Method 2: Look for "Subject:" field
        subject_match = self._extract_zendesk_field(r'Subject:\s*(.+)')
        if subject_match:
            return subject_match

        return None

    def _extract_zendesk_field(self, pattern: str) -> Optional[str]:
        """Extract a field from Zendesk PDF using regex."""
        match = re.search(pattern, self.raw_text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    def _extract_zendesk_description(self) -> str:
        """
        Extract ticket description and comments from Zendesk PDF.

        Captures the full ticket conversation including reproduction steps
        and technical details from comments, while filtering out Zendesk metadata noise.
        """
        # Simpler approach: find start of comments and extract everything after,
        # filtering out noise patterns

        # Find where comments start (after "Problem Summary" or first human name + timestamp)
        start_match = re.search(r'(Problem Summary|[\w\s]+ \w+ \d+, \d{4} at \d+:\d+)', self.raw_text, re.IGNORECASE)
        if not start_match:
            return self.raw_text[:1000]

        # Extract from start position to end
        content = self.raw_text[start_match.start():]
        lines = content.split('\n')

        # Patterns for noise/metadata to skip
        skip_patterns = [
            r'^Problem Summary \*SF',
            r'^Focus Score',
            r'^Ticket Location',
            r'^Ticket Clusters',
            r'^Redis Support Bot Agent',
            r'^Analyzer Bot',
            r'^File uploaded to SFTP',
            r'^Package.*successfully analyzed',
            r'^Parsed Logs',
            r'^Health check',
            r'^Total Open Tickets:',
            r'^Organization Notes:',
            r'^\*\*\*',
            r'^EOF',
            r'^Ticket ID$',
            r'^Status$',
            r'^Assignee$',
            r'^Subject$',
            r'^\d+/\d+$',  # Page numbers
            r'redislabs\.zendesk\.com',
            r'^https?://files\.cs\.redislabs',
            r'^@\w+$',  # Mentions like @exazen
            r'^\d{6}$',  # Standalone numbers
            r'^Support Software by Zendesk',
            # NOTE: Keep "SLA Package:" and account info for ARR detection
            # r'SLA Package:',  # REMOVED - needed for customer tier detection
            # r'Account Manager:',  # REMOVED - may contain useful context
            # r'Solution Architect'  # REMOVED - may contain useful context
        ]

        cleaned_lines = []
        skip_next_lines = 0
        prev_blank = False

        for i, line in enumerate(lines):
            line_stripped = line.strip()

            # Skip counted lines
            if skip_next_lines > 0:
                skip_next_lines -= 1
                continue

            # Skip if matches noise pattern
            if any(re.search(pattern, line_stripped) for pattern in skip_patterns):
                # If this is a bot agent line, skip until next human comment
                if 'Bot Agent' in line_stripped or 'Bot' in line_stripped:
                    skip_next_lines = 10  # Skip next few lines
                continue

            # Skip ticket list entries (#NNNNNN followed by status)
            if re.match(r'^#\d{5,7}$', line_stripped):
                skip_next_lines = 3  # Skip ticket list entry
                continue

            # Keep human comments (name + timestamp)
            if re.search(r'[\w\s]+ \w+ \d+, \d{4} at \d+:\d+', line_stripped):
                # Add separator before new comment
                if cleaned_lines and cleaned_lines[-1] != '':
                    cleaned_lines.append('')
                    cleaned_lines.append(f'**{line_stripped}**')
                    cleaned_lines.append('')
                else:
                    cleaned_lines.append(f'**{line_stripped}**')
                    cleaned_lines.append('')
                continue

            # Keep substantive content lines
            if line_stripped and len(line_stripped) > 2:
                cleaned_lines.append(line_stripped)
                prev_blank = False
            # Allow single blank line for paragraphs
            elif line_stripped == '' and not prev_blank and cleaned_lines:
                cleaned_lines.append('')
                prev_blank = True

        # Remove trailing blank lines
        while cleaned_lines and cleaned_lines[-1] == '':
            cleaned_lines.pop()

        return '\n'.join(cleaned_lines).strip() if cleaned_lines else self.raw_text[:1000]

    def _extract_zendesk_tags(self) -> List[str]:
        """Extract tags/labels from Zendesk PDF."""
        tags_match = re.search(r'Tags:\s*(.+)', self.raw_text, re.IGNORECASE)
        if tags_match:
            tags_str = tags_match.group(1).strip()
            return [tag.strip() for tag in tags_str.split(',')]
        return []

    def _extract_support_tier(self) -> Optional[str]:
        """
        Extract support tier from Zendesk organization notes.

        Looks for patterns like:
        - SLA Package: Premium Enterprise
        - SLA Package: Enterprise
        - VIP Support

        Returns the tier string (e.g., "Premium Enterprise") or None.
        """
        # Look for "SLA Package:" pattern in raw text
        sla_match = re.search(r'SLA Package:\s*(.+?)(?:\n|$)', self.raw_text, re.IGNORECASE)
        if sla_match:
            tier = sla_match.group(1).strip()
            # Clean up any trailing metadata
            tier = re.sub(r'\s+TAM:.*', '', tier, flags=re.IGNORECASE)
            return tier

        # Look for VIP support mentions
        if re.search(r'VIP\s+(?:Support|Package|Customer)', self.raw_text, re.IGNORECASE):
            return "VIP Support"

        return None

    def _parse_jira_pdf(self) -> Dict:
        """Parse Jira PDF export."""
        self.source_type = 'jira'
        data = {
            'source': 'jira',
            'issue_key': self._extract_jira_field(r'Issue Key:\s*([A-Z]+-\d+)') or self._extract_jira_issue_key_from_title(),
            'summary': self._extract_jira_field(r'Summary:\s*(.+)') or self._extract_jira_summary_from_title(),
            'description': self._extract_jira_description(),
            'priority': self._extract_jira_field(r'Priority:\s*(\w+)'),
            'severity': self._extract_jira_field(r'Severity:\s*(.+)'),
            'status': self._extract_jira_field(r'Status:\s*(\w+)'),
            'assignee': self._extract_jira_field(r'Assignee:\s*(.+)'),
            'reporter': self._extract_jira_field(r'Reporter:\s*(.+)'),
            'labels': self._extract_jira_labels(),
            'rca': self._extract_jira_field(r'RCA:\s*(.+)'),
            'customer': self._extract_jira_customer(),
            'raw_text': self.raw_text,
            'extracted_images': []  # Will be populated by extract_images()
        }

        return data

    def _extract_jira_field(self, pattern: str) -> Optional[str]:
        """Extract a field from Jira PDF using regex."""
        match = re.search(pattern, self.raw_text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    def _extract_jira_description(self) -> str:
        """Extract description from Jira PDF."""
        desc_match = re.search(r'Description:\s*(.+?)(?=\n[A-Z][a-z]+:|$)', self.raw_text, re.DOTALL | re.IGNORECASE)
        if desc_match:
            return desc_match.group(1).strip()

        return self.raw_text[:1000]  # Fallback

    def _extract_jira_labels(self) -> List[str]:
        """Extract labels from Jira PDF."""
        labels_match = re.search(r'Labels:\s*(.+)', self.raw_text, re.IGNORECASE)
        if labels_match:
            labels_str = labels_match.group(1).strip()
            return [label.strip() for label in labels_str.split(',')]
        return []

    def _extract_jira_customer(self) -> Optional[str]:
        """Extract customer name from Jira PDF."""
        # Common customer field names in Jira
        patterns = [
            r'Customer:\s*(.+)',
            r'Account:\s*(.+)',
            r'Organization:\s*(.+)',
            r'Company:\s*(.+)',
            r'Affected Organizations?:\s*(.+)',
            r'Seen by Customers?:\s*(.+)'
        ]

        for pattern in patterns:
            match = re.search(pattern, self.raw_text, re.IGNORECASE)
            if match:
                customer = match.group(1).strip()
                # Clean up common noise
                if customer and customer not in ['None', 'N/A', '-', '']:
                    return customer

        return None

    def _extract_jira_issue_key_from_title(self) -> Optional[str]:
        """
        Extract issue key from title line format.
        Format: [RED-174782] Title text Created: ...
        """
        # Match [KEY-NUMBER] at start of first line
        match = re.search(r'^\[?([A-Z]+-\d+)\]?', self.raw_text, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return None

    def _extract_jira_summary_from_title(self) -> Optional[str]:
        """
        Extract summary from title line format.
        Format: [RED-174782] Title text Created: ...
        """
        # Match text between [KEY-NUMBER] and 'Created:' (allow newlines in title)
        match = re.search(r'\[([A-Z]+-\d+)\]\s+(.+?)\s+Created:', self.raw_text, re.IGNORECASE | re.DOTALL)
        if match:
            summary = match.group(2).strip()
            # Remove newlines and multiple spaces
            summary = re.sub(r'\s+', ' ', summary)
            # Clean up common noise (Updated:, Status:, etc.)
            summary = re.sub(r'\s+(Updated|Status|Priority):.*$', '', summary, flags=re.IGNORECASE)
            return summary
        return None

    def _parse_excel(self) -> Dict:
        """Parse Excel export (Jira batch or single ticket)."""
        df = pd.read_excel(self.file_path)

        # Check if single ticket or batch
        if len(df) == 1:
            # Single ticket export - convert to dict
            row = df.iloc[0]
            return self._normalize_excel_row(row)
        else:
            # Batch export - return first ticket (or raise error)
            raise ValueError("Batch Excel exports not supported by this parser. Use calculate_jira_scores.py instead.")

    def _normalize_excel_row(self, row: pd.Series) -> Dict:
        """Normalize Excel row to standard format."""
        # Common Jira Excel column names (case-insensitive)
        data = {
            'source': 'jira',
            'issue_key': self._get_field(row, ['Issue key', 'Key', 'Jira']),
            'summary': self._get_field(row, ['Summary', 'Title']),
            'description': self._get_field(row, ['Description']),
            'priority': self._get_field(row, ['Priority']),
            'severity': self._get_field(row, ['Severity', 'Custom field (Severity)']),
            'status': self._get_field(row, ['Status']),
            'assignee': self._get_field(row, ['Assignee']),
            'labels': self._get_field(row, ['Labels'], as_list=True),
            'rca': self._get_field(row, ['RCA', 'Custom field (RCA)', 'Root Cause Analysis']),
            'customer': self._get_field(row, ['Customer', 'Account', 'Organization']),
        }

        return data

    def _get_field(self, row: pd.Series, field_names: List[str], as_list: bool = False) -> Optional[Union[str, List[str]]]:
        """Get field value from Excel row (case-insensitive)."""
        for field in field_names:
            for col in row.index:
                if field.lower() in col.lower():
                    value = row[col]
                    if pd.notna(value):
                        if as_list:
                            return str(value).split(',') if isinstance(value, str) else [str(value)]
                        return str(value)

        return [] if as_list else None

    def _parse_xml(self) -> Dict:
        """Parse Jira XML export."""
        if not XML_AVAILABLE:
            raise ImportError("lxml required for XML support. Install: pip install lxml")

        tree = etree.parse(str(self.file_path))
        root = tree.getroot()

        # Jira XML structure
        data = {
            'source': 'jira',
            'issue_key': self._get_xml_field(root, 'key'),
            'summary': self._get_xml_field(root, 'summary'),
            'description': self._get_xml_field(root, 'description'),
            'priority': self._get_xml_field(root, 'priority'),
            'status': self._get_xml_field(root, 'status'),
            'assignee': self._get_xml_field(root, 'assignee'),
            'labels': self._get_xml_field(root, 'labels', as_list=True),
        }

        return data

    def _get_xml_field(self, root, field_name: str, as_list: bool = False) -> Optional[Union[str, List[str]]]:
        """Extract field from XML."""
        elem = root.find(f'.//{field_name}')
        if elem is not None and elem.text:
            if as_list:
                return elem.text.split(',')
            return elem.text.strip()
        return [] if as_list else None

    def _parse_docx(self) -> Dict:
        """Parse Jira Word document export."""
        if not DOCX_AVAILABLE:
            raise ImportError("python-docx required for Word support. Install: pip install python-docx")

        doc = docx.Document(self.file_path)

        # Extract all text
        full_text = []
        for para in doc.paragraphs:
            full_text.append(para.text)

        self.raw_text = '\n'.join(full_text)

        # Parse similar to PDF (look for field patterns)
        data = {
            'source': 'jira',
            'issue_key': self._extract_jira_field(r'Issue Key:\s*([A-Z]+-\d+)'),
            'summary': self._extract_jira_field(r'Summary:\s*(.+)'),
            'description': self._extract_jira_description(),
            'priority': self._extract_jira_field(r'Priority:\s*(\w+)'),
            'status': self._extract_jira_field(r'Status:\s*(\w+)'),
            'labels': self._extract_jira_labels(),
            'raw_text': self.raw_text
        }

        return data


def parse_ticket_file(file_path: Union[str, Path]) -> Dict:
    """
    Convenience function to parse any supported ticket file.

    Args:
        file_path: Path to ticket export (PDF/Excel/XML/Word)

    Returns:
        Dictionary with normalized ticket data

    Examples:
        >>> data = parse_ticket_file('RED-12345.pdf')
        >>> data = parse_ticket_file('zendesk_ticket_789.pdf')
        >>> data = parse_ticket_file('jira_export.xlsx')
    """
    parser = UniversalTicketParser(file_path)
    return parser.parse()


if __name__ == '__main__':
    import sys
    import argparse

    arg_parser = argparse.ArgumentParser(
        description='Parse Jira/Zendesk ticket exports (PDF, Excel, XML, Word)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s zendesk_ticket.pdf
  %(prog)s zendesk_ticket.pdf --extract-images
  %(prog)s jira_export.xlsx
        """
    )

    arg_parser.add_argument('file', help='Path to ticket file')
    arg_parser.add_argument(
        '--extract-images',
        action='store_true',
        help='Extract images from PDF and save to output/images_<ticket_id>/'
    )
    arg_parser.add_argument(
        '--images-only',
        action='store_true',
        help='Only extract images, skip full parsing output'
    )

    args = arg_parser.parse_args()

    try:
        parser = UniversalTicketParser(args.file)
        data = parser.parse()

        # Extract images if requested
        if args.extract_images or args.images_only:
            images = parser.extract_images()
            data['extracted_images'] = images

            if images:
                print(f"Extracted {len(images)} images:", file=sys.stderr)
                for img in images:
                    print(f"  - {img['filename']} ({img['width']}x{img['height']}) from page {img['page']}", file=sys.stderr)
            else:
                print("No meaningful images found (min 500x100px)", file=sys.stderr)

        if not args.images_only:
            # Don't include raw_text in JSON output (too verbose)
            output_data = {k: v for k, v in data.items() if k != 'raw_text'}
            print(json.dumps(output_data, indent=2))

    except Exception as e:
        print(f"Error parsing file: {e}", file=sys.stderr)
        sys.exit(1)
