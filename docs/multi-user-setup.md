# Ergane Multi-User Setup Guide

## 🎯 Overview
Ergane now supports multiple users with personalized job matching! Each user gets notifications based on their own skills, salary requirements, and preferences.

## 👥 Current Users

### Mayte (You)
- **Profile:** `profiles/mayte.yaml`
- **Skills:** DevOps Jr, Cloud Engineer, MLOps, AI Builder
- **Focus:** Python, AWS, Terraform, LangChain, FastAPI, Docker
- **Min Salary:** 30,000 MXN bruto/mes
- **Telegram:** Uses default chat_id from `.env` file
- **Total Skills:** 58 weighted skills

### Jeaneth (Your Sister)
- **Profile:** `profiles/jeaneth.yaml`
- **Skills:** Software Development Engineer
- **Focus:** React, TypeScript, C#/.NET, AWS, Security, Testing
- **Min Salary:** 65,000 MXN bruto/mes
- **Telegram:** Chat ID `8736439805` (configured)
- **Total Skills:** 56 weighted skills

---

## 🚀 How It Works

### 1. Scraping (Same for Everyone)
The system scrapes jobs from 6 sources:
- Himalayas
- WeWorkRemotely
- GetOnBrd
- TechJobsMX
- OCC
- CompuTrabajo

**Every 6 hours automatically** (or run manually with `python3 main.py --once`)

### 2. Scoring (Per User)
Each job is scored INDIVIDUALLY for each user based on:

**60% CV Keyword Matching:**
- Matches job description against your skills
- Higher weight skills = higher score
- Example: "Python" (0.20) gives more points than "Git" (0.05)

**40% Ollama Semantic Scoring (optional):**
- AI analyzes job fit using qwen2.5-coder:7b
- Understands context beyond keywords
- Fallback to CV-only if Ollama is down

**Score threshold:** 0.15 for matching, 0.40 for notifications

### 3. Notifications (Per User)
**Each user receives ONLY their matches:**
- Mayte gets jobs matching DevOps/Cloud/MLOps/AI
- Jeaneth gets jobs matching React/TS/C#/.NET/AWS
- Same job can be sent to BOTH if it matches both profiles

**Notification format:**
```
🔔 New job match (score: 0.75)

DevOps Engineer Jr
Company XYZ | 45,000 MXN/mes | Remote
🏷️ Python, AWS, Terraform, Docker

[View Job](https://...)
```

---

## 📝 Customizing Your Profile

### Edit Your Skills
```bash
nano profiles/jeaneth.yaml  # or mayte.yaml
```

**Add/modify skills:**
```yaml
skills:
  # Higher weight (0.15-0.20) = most important
  react: 0.20
  typescript: 0.20
  
  # Medium weight (0.08-0.12) = nice to have
  docker: 0.10
  
  # Low weight (0.05) = bonus points
  git: 0.05
```

### Update Preferences
```yaml
preferences:
  min_salary_mxn: 65000        # Minimum acceptable salary
  remote_preferred: true        # Prefer remote jobs
  locations:                    # Acceptable locations
    - Mexico
    - CDMX
    - Remote
  exclude_companies:            # Skip these companies
    - Accenture                 # (currently empty)
    - HSBC
```

### Change Notification Threshold
```yaml
min_score: 0.15  # Lower = more jobs, Higher = fewer but better matches
```

**Recommended values:**
- `0.10` - Very permissive (lots of noise)
- `0.15` - Balanced (current setting)
- `0.20` - Strict (only strong matches)

---

## 🤖 Telegram Bot Commands

Both users can use these commands:

### `/review <job_url>`
Get detailed analysis of a specific job:
```
/review https://www.getonbrd.com/jobs/...
```

**Returns:**
- Match score with your profile
- Skill matches found
- Why it's a good/bad fit
- Salary analysis

### `/generate_cv <job_url>`
Generate a tailored CV + cover letter for a job:
```
/generate_cv https://www.getonbrd.com/jobs/...
```

**Creates:**
- Word document (.docx) with customized CV
- Highlights relevant experience
- Cover letter matched to job description
- Uses Claude API (requires ANTHROPIC_API_KEY in .env)

### `/help`
Show available commands

---

## 🛠️ Running the System

### Automatic Mode (Recommended)
```bash
cd ~/Vscode-projects/Ergane
python3 main.py
```
- Runs every 6 hours automatically
- Keeps running in background
- Press Ctrl+C to stop

### Manual Test Run
```bash
python3 main.py --once
```
- Runs pipeline once
- Shows detailed logs
- Good for testing after profile changes

### Check Statistics
```bash
python3 main.py --stats
```
Shows:
- Total jobs in database
- Jobs notified
- Jobs per source

---

## 🔧 Advanced Configuration

### Add a New User
1. Copy the template:
   ```bash
   cp profiles/template.yaml profiles/newuser.yaml
   ```

2. Edit the new profile:
   ```bash
   nano profiles/newuser.yaml
   ```

3. Get Telegram chat_id:
   - Message `@userinfobot` on Telegram
   - Copy the chat_id number
   - Update `telegram.chat_id` in profile

4. Restart Ergane:
   ```bash
   ./check_running.sh --stop-all
   python3 main.py
   ```

### Disable a User
Edit profile and set:
```yaml
enabled: false
```

### Use Different Telegram Accounts
Each profile can have its own `chat_id`:
```yaml
telegram:
  chat_id: "123456789"  # Unique for each user
```

---

## 📊 Understanding Scores

**Job Score Components:**

| Component | Weight | What It Measures |
|-----------|--------|------------------|
| CV Keywords | 60% | Skill matches in job description |
| Ollama Semantic | 40% | AI understanding of job fit |

**Final Score Examples:**
- `0.85` - Excellent match (dream job territory)
- `0.60` - Good match (worth applying)
- `0.40` - Acceptable match (notification threshold)
- `0.25` - Weak match (still in DB, no notification)
- `0.10` - Poor match (filtered out)

---

## 🐛 Troubleshooting

### "Not receiving notifications"

1. **Check if jobs match your profile:**
   ```bash
   python3 main.py --stats
   ```
   Look at "Pending" count - these are jobs below threshold.

2. **Lower your min_score:**
   ```yaml
   min_score: 0.10  # Was 0.15
   ```

3. **Check your Telegram chat_id:**
   ```bash
   grep -A2 "telegram:" profiles/yourname.yaml
   ```

4. **Verify bot is running:**
   ```bash
   ./check_running.sh
   ```

### "Getting too many notifications"

1. **Raise your min_score:**
   ```yaml
   min_score: 0.20  # Was 0.15
   ```

2. **Add excluded companies:**
   ```yaml
   exclude_companies:
     - Company1
     - Company2
   ```

3. **Raise min_salary:**
   ```yaml
   min_salary_mxn: 80000  # Was 65000
   ```

### "Duplicate instances running"
```bash
./check_running.sh --stop-all
python3 main.py
```

Ergane also creates a local polling lock at `~/.ergane/telegram_bot.lock` so only one local poller can run per token.

---

## 📈 Performance Metrics

**Typical run (6 hours):**
- 300-400 jobs scraped
- 80-100 new jobs
- 10-30 notifications per user (depends on market)

**Success rates:**
- Himalayas: ~20 jobs/run (stable)
- WeWorkRemotely: ~80 jobs/run (RSS)
- GetOnBrd: ~130 jobs/run (Mexico focus)
- TechJobsMX: ~50 jobs/run (Mexico)
- OCC: ~10 jobs/run (Mexico)
- CompuTrabajo: ~10 jobs/run (Mexico)

---

## 🎓 Tips for Better Matches

### For Mayte (DevOps/Cloud):
- Keep high weights on: Python, AWS, Terraform, Docker
- Add niche skills if you learn them: Kubernetes, Ansible, Prometheus
- Watch for "Jr" and "Semi-senior" titles

### For Jeaneth (Frontend/Full-Stack):
- Keep high weights on: React, TypeScript, C#, .NET
- Your security/testing skills are differentiators - keep them!
- Consider adding: Next.js, Redux, Azure (if learning)

### General:
- Update profiles as you learn new skills
- Check `/review` for jobs you're unsure about
- Lower min_score during job search season
- Raise min_score when job market is hot

---

## 📞 Support

**Check logs:**
```bash
tail -100 ~/Vscode-projects/Ergane/ergane.log
```

**Test profile loading:**
```bash
python3 -c "from profiles import load_all_profiles; print([p.name for p in load_all_profiles()])"
```

**Verify Telegram connection:**
```bash
# Send test message to bot on Telegram
/help
```

---

**Last updated:** 2026-04-05  
**Ergane version:** Multi-user  
**Configured users:** Mayte, Jeaneth
