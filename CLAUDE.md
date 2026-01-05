# CLAUDE.md - Jira Helper Toolkit

## Project Overview

**Jira Helper** is a Python toolkit for Redis Cloud support operations. It provides:
1. **Impact Score Calculation** - Automated scoring of support tickets (0-100+ points)
2. **Zendesk-to-Jira Conversion** - AI-powered ticket analysis and Jira bug creation
3. **RCA Generation** - Root Cause Analysis form generation

**GitHub Repository**: [https://github.com/markotrapani/impact-score-calculator](https://github.com/markotrapani/impact-score-calculator)

**Parent Repository**: Part of [marko-projects](https://github.com/markotrapani/marko-projects) as a git submodule

---

## 🚨 CRITICAL: Output Format Rules

**NEVER mix markup formats in output files!**

| File Extension | Use This Format | NEVER Use |
|----------------|-----------------|-----------|
| `.md` | Markdown (`##`, `**bold**`, ``` ``` ```) | Jira wiki (`h2.`, `{code}`, `*bold*`) |
| `.txt` (for Jira) | Jira wiki markup (`h2.`, `{code:json}`, `*bold*`) | Markdown |

**Why this matters:**
- `.md` files are previewed in IDEs/GitHub - Jira markup renders as garbage
- Jira description fields expect Jira wiki markup - Markdown won't render

**When generating Jira tickets:**
- `output/JIRA-*.md` files → Use **Markdown** (for preview/review)
- Content pasted into Jira → Convert to **Jira wiki markup** if needed

---

## 🚨 CRITICAL: Impact Score Values are DISCRETE

**NEVER make up impact score numbers!** Each component has specific allowed values - not arbitrary numbers.

| Component | Allowed Values | NOT Allowed |
|-----------|---------------|-------------|
| Impact & Severity | **38, 30, 22, 16, 8** | 28, 25, 20, etc. |
| Customer ARR | **15, 13, 10, 8, 5, 0** | 12, 11, 7, etc. |
| SLA Breach | **8 or 0** | Any other number |
| Frequency | **16, 8, 0** | 12, 10, 4, etc. |
| Workaround | **15, 12, 10, 5** | 14, 11, 8, etc. |
| RCA Action Item | **8 or 0** | Any other number |

**When generating impact scores:**
1. Use `intelligent_estimator.py` to calculate scores from PDF
2. Or manually select from the discrete values above
3. **NEVER** eyeball a total and reverse-engineer fake component values

See [docs/IMPACT_SCORE_MODEL.md](docs/IMPACT_SCORE_MODEL.md) for full scoring criteria.

---

## 🤖 LLM Integration (Claude)

This toolkit integrates with Claude for intelligent ticket analysis. **Three modes available:**

### Mode 1: Claude Code Direct (No API Key) ✅ RECOMMENDED

When working inside a Claude Code session, Claude can handle the entire workflow automatically.

**Usage:** Simply ask Claude Code:
> "Generate a Jira from the PDF I dropped in the repo"

**What Claude Code does automatically:**

1. Finds and parses the Zendesk PDF using `universal_ticket_parser.py --extract-images`
2. **Views extracted images** to understand screenshots and visual evidence
3. Analyzes the ticket content directly (no API call needed - Claude IS the session)
4. Saves the analysis to `output/claude_response_<ticket_id>.txt`
5. Runs `create_jira_from_claude_response.py` to generate the Jira markdown
6. **Embeds relevant images inline** in the description where they provide context
7. Outputs the final Jira ticket ready for copy/paste

**Why this works:** Claude Code sessions ARE Claude - no need to call an external API or copy/paste prompts. The analysis happens inline.

---

## 📸 Image Extraction & Embedding

**CRITICAL:** When generating Jira tickets, images must be **embedded inline with context**, not just listed as attachments at the end.

### Image Extraction

The parser extracts meaningful images (>500px width) from PDFs:

```bash
python3 src/universal_ticket_parser.py <pdf_file> --extract-images
```

Images are saved to `output/images_<ticket_id>/` with descriptive filenames:
- `page3_img1_1212x799.png` - Page 3, image 1, 1212x799 pixels

### Viewing Images (Claude Code)

After extraction, **view each image** using the Read tool to understand what it shows:

```python
# Claude Code should read each image file to see its contents
Read("output/images_152561/page3_img1_1212x799.png")
```

### Embedding Images Inline

**DO NOT** just list images at the end as "Attachments". Instead, embed them **inline with the relevant description text**:

**❌ WRONG - Images as attachments only:**
```markdown
### Technical Details
Users get a 403 error when configuring MFA.

## Attachments
- page3_img1.png
- page9_img1.png
```

**✅ CORRECT - Images embedded inline with context:**
```markdown
### Technical Details

Users encounter the error on the MFA configuration page when attempting to set up SMS MFA:

![MFA Configuration Page](images_152561/page3_img1_1212x799.png)

The account logs show MFA enforcement was toggled on/off repeatedly, which may be related to the issue:

![MFA Enforcement Logs](images_152561/page9_img1_2966x1822.png)

Kibana search shows no MFA configuration logs for the affected user, indicating the request never reached the backend:

![Kibana No Results](images_152561/page10_img3_1788x493.png)
```

### Image Selection Guidelines

Not all extracted images are useful. Prioritize:
1. **Error screenshots** - UI showing the actual error
2. **Log screenshots** - Kibana, CloudWatch, or system logs
3. **Configuration screens** - Settings pages showing current state
4. **Evidence screenshots** - Proof of issue (metrics, dashboards)

Skip:
- Duplicate images (same screenshot appearing multiple times)
- Generic UI without relevant context
- Redacted/blurred images with no useful info

### Mode 2: Interactive Manual (No API Key)

For use outside Claude Code (e.g., terminal-only). Requires manual copy/paste.

**Workflow:**
```bash
# Step 1: Generate analysis prompt from Zendesk PDF
python3 src/claude_interactive.py <zendesk_pdf>

# Step 2: Copy the generated prompt and paste into Claude (web/app)
cat output/claude_prompt_XXXXX.txt

# Step 3: Claude analyzes and responds with SUMMARY: and DESCRIPTION:

# Step 4: Save Claude's response to the response file
# (copy Claude's output to output/claude_response_XXXXX.txt)

# Step 5: Create Jira ticket from Claude's response
python3 src/create_jira_from_claude_response.py output/claude_response_XXXXX.txt
```

**Key files:**

- `src/claude_interactive.py` - Generates prompts for Claude
- `src/create_jira_from_claude_response.py` - Processes Claude's response into Jira format

### Mode 3: Automatic API (Requires `ANTHROPIC_API_KEY`)

Direct API calls using the Anthropic SDK - fully automated but requires API access.

**Setup:**
```bash
export ANTHROPIC_API_KEY="your-api-key"
```

**Usage:**
```bash
python3 src/create_jira_from_zendesk.py <zendesk_pdf> --use-claude
```

**Key files:**
- `src/claude_analyzer.py` - Anthropic SDK integration (claude-sonnet-4-20250514)
- `src/create_jira_from_zendesk.py` - Main CLI with `--use-claude` flag

**API Details:**
| Setting | Value |
|---------|-------|
| SDK | `anthropic>=0.39.0` |
| Model | `claude-sonnet-4-20250514` |
| Temperature | 0 (deterministic) |
| Max tokens | 8000 |

---

## 🎯 Project Purpose

This toolkit helps prioritize Redis Cloud support tickets by:
- Automatically analyzing Jira ticket exports
- Calculating impact scores (0-100+ points) based on 6 key components
- Converting Zendesk tickets to structured Jira bugs using Claude AI
- Providing batch processing for multiple tickets
- Offering interactive estimation for single tickets

**Primary Use Case**: Redis Cloud Customer Success team ticket prioritization and Jira creation

---

## 📁 Project Structure

```
jira-helper/
├── README.md                           # Main project documentation
├── CLAUDE.md                          # This file - Claude Code instructions
├── requirements.txt                    # Python dependencies
├── .gitignore                         # Git ignore rules
│
├── src/                               # Python Scripts
│   ├── Claude Integration
│   │   ├── claude_interactive.py      # Interactive mode (no API key)
│   │   ├── claude_analyzer.py         # Anthropic SDK integration
│   │   └── create_jira_from_claude_response.py
│   │
│   ├── Zendesk-to-Jira
│   │   ├── create_jira_from_zendesk.py # Main CLI tool
│   │   ├── jira_creator.py            # Jira ticket data structures
│   │   ├── universal_ticket_parser.py # PDF/document parsing
│   │   └── label_extractor.py         # Keyword-based label extraction
│   │
│   ├── Impact Score Calculation
│   │   ├── intelligent_estimator.py   # AI-powered auto-estimation
│   │   ├── impact_score_calculator.py # Core calculation library
│   │   ├── calculate_jira_scores.py   # Batch processor
│   │   ├── estimate_impact_score.py   # Interactive estimator
│   │   └── jira_impact_score_processor.py
│   │
│   └── RCA Generation
│       ├── create_rca.py              # RCA form creation
│       ├── generate_rca_form.py       # Form generation
│       ├── generate_rca_summary.py    # Summary generation
│       └── generate_complete_rca.py   # Complete RCA workflow
│
├── docs/                              # Documentation
│   ├── ROADMAP.md
│   ├── IMPACT_SCORE_MODEL.md
│   ├── IMPACT_SCORE_VISUAL_GUIDE.md
│   ├── INTELLIGENT_ESTIMATOR_GUIDE.md
│   ├── JIRA_CREATION_GUIDE.md
│   ├── JIRA_PROCESSOR_USER_GUIDE.md
│   ├── TOOL_SELECTION_GUIDE.md
│   └── SCRIPT_ARCHITECTURE.md
│
└── output/                            # Generated files (gitignored)
```

---

## 🛠️ Technology Stack

- **Language**: Python 3.8+
- **Key Libraries**:
  - `pandas` (>= 2.0.0) - Data processing
  - `openpyxl` (>= 3.1.0) - Excel file handling
  - `pymupdf` (>= 1.23.0) - PDF extraction
  - `python-docx` (>= 1.1.0) - Word document support
  - `lxml` (>= 5.0.0) - XML parsing
  - `anthropic` (>= 0.39.0) - Claude API integration (optional)
- **Supported Input Formats**:
  - **Jira**: PDF, Excel (.xlsx), XML, Word (.docx)
  - **Zendesk**: PDF
- **Output Formats**: Console, JSON, Excel, Markdown

---

## 🎓 How It Works

### Impact Score Components (6 Total)

1. **Impact & Severity** (0-38 points): Based on Jira priority/severity
2. **Customer ARR** (0-15 points): Annual recurring revenue of affected customer
3. **SLA Breach** (0 or 8 points): Whether SLA was breached
4. **Frequency** (0-16 points): How often the issue occurs
5. **Workaround** (5-15 points): Availability and complexity of workarounds
6. **RCA Action Item** (0 or 8 points): Whether ticket is part of RCA follow-up

**Optional Multipliers**:
- Support blocking: 1.0-1.5x
- Account risk: 1.0-2.0x

**Total Score Range**: 0-100+ points

See [Impact_Score_Model.md](Impact_Score_Model.md) for complete details.

---

## 🚀 Common Development Tasks

### Adding New Features

When adding features, consider:
1. **Which script needs modification**: Most new features go in `intelligent_estimator.py`
2. **Update documentation**: Modify relevant .md files
3. **Update ROADMAP.md**: Mark features as completed
4. **Test with sample data**: Use real Jira exports (anonymized)

### Modifying Scoring Logic

Core scoring logic is in:
- `impact_score_calculator.py` - Core calculation functions
- `intelligent_estimator.py` - Automatic estimation logic (keywords, detection)

**Important**: Keep scoring logic consistent across all three tools!

**⚠️ CRITICAL: Scoring Model Documentation Sync**

When modifying scoring rules or clarifications:
1. **Update BOTH documentation files:**
   - `docs/IMPACT_SCORE_MODEL.md` - Complete scoring specification
   - `docs/IMPACT_SCORE_VISUAL_GUIDE.md` - Quick reference tables and examples
2. **Keep them in sync:** Any change to scoring logic, thresholds, or clarifications MUST be reflected in both files
3. **Recent example:** SLA Breach and RCA Action Item clarifications (Oct 2025)
   - Added ACRE exception to SLA Breach (always 0 for ACRE)
   - Clarified RCA Action Item definition (past RCA follow-up vs current incident)

### Adding New Keywords

Keywords are defined in `intelligent_estimator.py`:
```python
WORKAROUND_KEYWORDS = {
    'with_impact': [...],
    'no_workaround': [...],
    # etc.
}
```

Update these dictionaries when improving detection accuracy.

### Testing

Currently **no automated tests** (see ROADMAP.md). When testing:
1. Use real Jira exports (anonymized)
2. Test all three tools for consistency
3. Verify score breakdowns match expected values
4. Check edge cases (missing fields, unusual values)

---

## 📝 Documentation Guidelines

### When to Update Documentation

Update docs when:
- Adding/removing features
- Changing scoring logic
- Modifying keyword detection
- Adding new output formats
- Changing script behavior

### Key Documentation Files

- **README.md**: High-level overview, quick start, examples
- **INTELLIGENT_ESTIMATOR_GUIDE.md**: Detailed guide for main tool
- **Impact_Score_Model.md**: Scoring algorithm specification
- **ROADMAP.md**: Feature status, future plans
- **SCRIPT_UPDATE_LOG.md**: Recent changes and improvements

### Documentation Style

- Use clear, concise language
- Include code examples
- Add tables for comparisons
- Use emoji for visual hierarchy (✅ ⚠️ 🎯 etc.)
- Keep examples realistic and practical

---

## 🐛 Known Issues & Limitations

See [ROADMAP.md](ROADMAP.md) "Known Issues & Technical Debt" section.

**Key limitations**:
1. ARR detection is keyword-based (not always accurate)
2. RCA templates may be falsely detected as actual RCA content
3. Frequency relies on keywords (may miss contextual indicators)
4. Intelligent estimator processes one ticket at a time (no batch mode yet)

---

## 🎯 Current Development Priorities

See [ROADMAP.md](ROADMAP.md) for full roadmap.

**High Priority**:
1. Add unit tests and integration tests
2. Implement batch mode for intelligent estimator
3. Create configuration file support (YAML/JSON)
4. Improve ARR detection accuracy

**Medium Priority**:
1. Direct Jira API integration
2. Web-based UI
3. ML-based scoring improvements

---

## 🤝 Code Review Guidelines

When reviewing changes:
1. **Consistency**: Ensure scoring logic matches across all tools
2. **Documentation**: All new features should update relevant docs
3. **Testing**: Manually test with sample Jira exports
4. **Keywords**: Verify new keywords don't create false positives
5. **Edge cases**: Check behavior with missing/unusual data

---

## 📦 Dependencies

Current dependencies in `requirements.txt`:

```
pandas>=2.0.0
openpyxl>=3.1.0
pymupdf>=1.23.0
python-docx>=1.1.0
lxml>=5.0.0
anthropic>=0.39.0  # Optional - only needed for --use-claude API mode
```

**When adding dependencies**:

- Justify the need (avoid bloat)
- Update requirements.txt
- Update README.md if user-facing
- Test installation on fresh environment

---

## 🔄 Git Workflow

This project follows the parent repository's git workflow (see parent [CLAUDE.md](../CLAUDE.md)):
- Never commit/push without explicit user permission
- Use conventional commit format (feat:, fix:, docs:, etc.)
- Include Claude Code attribution footer
- Ask before creating PRs

---

## 🧪 Sample Data

**⚠️ IMPORTANT**: Never commit real customer data!

Sample Jira exports should:
- Use anonymized customer names
- Use realistic but fake ARR values
- Preserve field structure for testing
- Be added to `.gitignore` if they contain any real data

---

## 📚 Additional Resources

- [Jira Cloud API Documentation](https://developer.atlassian.com/cloud/jira/platform/rest/v3/)
- [pandas Documentation](https://pandas.pydata.org/docs/)
- [openpyxl Documentation](https://openpyxl.readthedocs.io/)

---

## 🎓 Claude Code Usage Tips

### Useful Prompts

**"Add a new keyword to workaround detection"**
→ Claude will update WORKAROUND_KEYWORDS dict in intelligent_estimator.py

**"Test the intelligent estimator with sample data"**
→ Claude will run the script and show results

**"Improve ARR detection accuracy"**
→ Claude will analyze keyword logic and suggest improvements

**"Add unit tests for core calculator"**
→ Claude will create test files and test cases

### What Claude Should Know

- This is a **production tool** used by Redis Cloud CS team
- Scoring accuracy is critical (affects ticket prioritization)
- Changes should be **backward compatible** with existing Jira exports
- Documentation is important (multiple users reference guides)

---

## 📧 Questions?

For questions about:
- **Scoring logic**: See [Impact_Score_Model.md](Impact_Score_Model.md)
- **Tool usage**: See individual guide files
- **Development**: See [ROADMAP.md](ROADMAP.md)
- **Project setup**: See [README.md](README.md)

---

**Last Updated**: December 15, 2025
