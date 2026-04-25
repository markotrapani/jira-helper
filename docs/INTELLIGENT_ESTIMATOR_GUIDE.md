# Intelligent Jira Impact Score Estimator

## 🎯 What This Tool Does

**The Intelligent Estimator analyzes any Jira XLSX export and automatically estimates impact scores using AI-powered text analysis.**

✅ Accepts any Jira Excel export  
✅ Analyzes priority, description, labels, customer data  
✅ Estimates all 6 components automatically  
✅ Shows reasoning for each estimate  
✅ No manual input required  

## 🚀 Quick Start

```bash
# Analyze a ticket
python intelligent_estimator.py RED-153478_Export.xlsx

# With verbose output
python intelligent_estimator.py ticket.xlsx --verbose

# Save results to JSON
python intelligent_estimator.py ticket.xlsx --output results.json
```

## 📊 Real Example: RED-153478

### What the Tool Analyzed:
```
Ticket: RED-153478  
Priority: Medium
Severity: 2 - Medium  
Description: "Similar to as observed by Monday.com..."
Labels: cluster, devops, support
RCA: "1. Bug Description: Issue caused by..."
```

### Intelligent Estimation Result:
```
COMPONENT BREAKDOWN
─────────────────────────────────────────────

1. Impact & Severity: 22 points
   → Priority 'medium' indicates 22 points

2. Customer ARR: 15 points
   → VIP customer 'monday.com' identified

3. SLA Breach: 0 points
   → No SLA breach indicators found

4. Frequency: 16 points
   → Multiple occurrence keyword 'again' found

5. Workaround: 10 points
   → No clear workaround information

6. RCA Action Item: 8 points
   → RCA field contains substantial content

─────────────────────────────────────────────
FINAL IMPACT SCORE: 71.0 points
PRIORITY LEVEL: HIGH
```

### Comparison with Manual Score:
- **Manual (from image):** 47 points
- **Intelligent estimate:** 71 points  
- **Difference:** The AI detected frequency indicators (+16) and RCA content (+8) that weren't in the manual score

## 🧠 How It Estimates

### 1. Impact & Severity (0-38)
**Checks:**
- Priority field (Blocker=38, High=30, Medium=22, Low=16)
- Severity field (Sev 1=38, Sev 2=30, Sev 3=22)
- Keywords: "critical", "outage", "degraded", "error"

### 2. Customer ARR (0-15)

**Scoring bands (official Confluence guidelines):**

| Score | Condition |
|-------|-----------|
| 15 | ARR > $1M |
| 13 | $500K < ARR ≤ $1M |
| 10 | $100K < ARR ≤ $500K |
| 8  | >10 low-ARR customers affected |
| 5  | <10 low-ARR customers affected |
| 0  | Single low-ARR customer, or ARR unknown |

**Automatic detection looks for:**
- Explicit dollar amounts in the ticket body (e.g. `$5M ARR`, `$750K ARR`, `ARR: $250K`)
- Multi-customer phrasings (`multiple customers`, `several customers`, etc.)

**Support tier is NOT ARR.** Contract-level tiers (Premium Enterprise, Enterprise, Standard, VIP) are *not* mapped to ARR bands, because a Premium Enterprise customer can sit anywhere in the ARR range. If a support tier is detected in the ticket, the estimator surfaces it as a hint in the reason string but returns **0** and prompts you to pass `--arr` manually.

**When in doubt, pass `--arr` explicitly:**

```bash
python src/intelligent_estimator.py ticket.pdf --arr 500k-1M
```

Valid values: `100k-500k`, `500k-1M`, `1M-5M`, `5M-10M`, `10M+`, `unknown`.

### 3. SLA Breach (0 or 8)
**Checks:**
- Keywords: "sla breach", "exceeded sla", "downtime"
- Time duration mentions
- Critical priority level

### 4. Frequency (0-16)
**Checks:**
- Explicit counts: "5 times", "3 occurrences"
- Keywords: "multiple", "recurring", "again", "repeated"
- References to similar tickets

### 5. Workaround (5-15)
**Checks:**
- Workaround field content
- Keywords: "no workaround", "requires fix", "patch"
- Complexity indicators

### 6. RCA Action Item (0 or 8)
**Checks:**
- RCA field content (>50 characters)
- Keywords: "rca", "root cause", "action item"
- RCA-related labels

## 💡 When to Use This Tool

| Scenario | Use This? |
|----------|-----------|
| Have Jira XLSX export | ✅ Yes |
| Want automated estimation | ✅ Yes |
| Need consistent scoring | ✅ Yes |
| Want to see reasoning | ✅ Yes |
| Batch processing | ⚠️ Use one at a time |
| Need 100% accuracy | ❌ Review estimates |

## 🔧 Customization

### Add Your VIP Customers

Edit `intelligent_estimator.py`:

```python
VIP_CUSTOMERS = [
    'monday.com', 'salesforce', 'twilio',
    # Add your VIP customers:
    'your-customer-name',
]
```

### Adjust Keywords

```python
WORKAROUND_KEYWORDS = {
    'none': ['no workaround', 'requires fix'],
    # Add your keywords
}
```

## 📝 Command Options

```bash
# Basic
python intelligent_estimator.py <file.xlsx>

# Verbose (show all extracted data)
python intelligent_estimator.py <file.xlsx> --verbose
python intelligent_estimator.py <file.xlsx> -v

# Save to JSON
python intelligent_estimator.py <file.xlsx> --output results.json
python intelligent_estimator.py <file.xlsx> -o results.json
```

## 📤 Output Formats

### Console
- Shows ticket summary
- Component breakdown with reasoning
- Final score and priority

### JSON (`--output`)
```json
{
  "ticket": "RED-153478",
  "components": {
    "impact_severity": 22,
    "customer_arr": 15,
    ...
  },
  "reasoning": {
    "impact_severity": "Priority 'medium' indicates 22 points",
    ...
  },
  "scores": {
    "final_score": 71.0,
    "priority": "HIGH"
  }
}
```

## ⚠️ Limitations

1. **Keyword-Based** - Relies on text patterns
2. **Single Ticket** - Processes one at a time
3. **No Images** - Can't read score screenshots
4. **Conservative** - May overestimate for safety
5. **English Only** - Works best with English text

## 🎯 Best Practices

1. ✅ **Review the reasoning** - Understand why each score was assigned
2. ✅ **Customize keywords** - Add domain-specific terms
3. ✅ **Update VIP list** - Keep customer list current
4. ✅ **Validate estimates** - Compare with manual scores
5. ✅ **Use as starting point** - Refine manually if needed

## 🔄 Typical Workflow

1. Export Jira ticket to Excel
2. Run intelligent estimator
3. Review component reasoning
4. Adjust scores if needed
5. Document final score in Jira

## 🆚 vs Other Tools

| Tool | Best For |
|------|----------|
| **intelligent_estimator.py** | Automatic analysis of any XLSX |
| calculate_jira_scores.py | Batch files with proper columns |
| estimate_impact_score.py | Manual/interactive input |

## 📊 Accuracy Tips

The estimator learns from patterns. To improve:

1. Compare estimates vs actual scores
2. Identify common mismatches
3. Add missing keywords
4. Adjust customer list
5. Fine-tune thresholds
