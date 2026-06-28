exports.handler = async function(event) {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: JSON.stringify({ error: 'Method not allowed' }) };
  }

  let apiKey, stage, quarter, year;
  try {
    ({ apiKey, stage, quarter, year } = JSON.parse(event.body || '{}'));
  } catch {
    return { statusCode: 400, body: JSON.stringify({ error: 'Invalid JSON body' }) };
  }

  if (!apiKey) {
    return { statusCode: 400, body: JSON.stringify({ error: 'apiKey is required' }) };
  }
  if (!stage || !['macro', 'strategic'].includes(stage)) {
    return { statusCode: 400, body: JSON.stringify({ error: 'stage must be "macro" or "strategic"' }) };
  }
  if (!quarter || !year) {
    return { statusCode: 400, body: JSON.stringify({ error: 'quarter and year are required' }) };
  }

  const QUARTER = quarter; // e.g. "Q1"
  const YEAR = year;       // e.g. "2026"

  const macroPrompt = `You are an expert equity research analyst. Synthesize ${QUARTER} ${YEAR} *macro* themes across:

CPG companies: Unilever, Mondelez, Nestlé, PepsiCo, Coca-Cola Company, Danone, Barry Callebaut, Keurig Dr Pepper, General Mills, Hershey Company, Kraft Heinz
Appliances companies: SharkNinja, Haier

---
### Allowed Sources
- ${QUARTER} ${YEAR} earnings call transcripts (with timestamps)
- ${QUARTER} ${YEAR} investor presentations (slide/page numbers)
- ${QUARTER} ${YEAR} filings (10-Q/annual report excerpts; page numbers)
- Analyst reports from Barclays, Jefferies, and Goldman Sachs (page/section numbers)
- Additional relevant and reliable sources that provide verifiable macroeconomic commentary

### CRITICAL: You must use web_search and web_fetch to find and READ the actual source documents for each company before making any claim. Do NOT rely on general knowledge about these companies. If you cannot find or access a verifiable ${QUARTER} ${YEAR} source for a company, explicitly state "NOT VERIFIED" for that company and exclude it from the analysis rather than guessing.

### Focus of Analysis (Strict)
Extract only macro environment themes:
- Consumer demand, affordability, and consumer sentiment
- Input cost inflation and commodity price outlook (cocoa, sugar, coffee, packaging, oil, energy)
- FX pressures and geographic exposure
- Trade policy, tariffs, and geopolitical risk
- Supply chain resilience, logistics stability, inventory strategy
- Labor markets and wage inflation
- Guidance language referencing macro assumptions
- Developed vs emerging markets

Exclude: brand launches, marketing stories, sustainability messaging, product-level updates — unless directly linked to macro cost/volume/pricing/supply chain context.

### Synthesis Rule (Frequency-Driven)
Do not merely restate what each company said. Identify patterns and include a theme only if it appears in multiple cases.
- 7+ companies mention a theme → Key Cross-Sector Theme
- 4–6 companies mention a theme → Supporting Insight
- 1–3 companies mention a theme → Ignore, unless a "weak but notable outlier" (max 3 bullets total)

### Citations & Traceability (Non-Negotiable)
Every claim must have inline citations: [CompanyCode SourceType YYYY-MM-DD locator]
SourceType: CALL, PRES, FILING, BARCLAYS, JEFFERIES, GOLDMAN, or OTHER
Locator: CALL = timestamp or Q&A number; PRES/FILING/Analyst = p.X or slide Y

### Output Structure (return as JSON)
{
  "executive_synthesis": [ { "theme": "...", "citation": "...", "action": "..." } ],
  "theme_frequency_table": [ { "theme": "...", "mention_count": 0, "companies": ["UL","KHC"], "summary": "...", "evidence_citations": ["...", "..."] } ],
  "source_log": [ { "ref_code": "...", "company": "...", "source_type": "...", "title": "...", "publisher": "...", "date": "...", "locator": "...", "url": "...", "quote": "...", "notes": "...", "group": "CPG" } ],
  "verification_status": { "Unilever": "VERIFIED", "SomeCompany": "NOT VERIFIED - reason" }
}

Return ONLY valid JSON, no markdown formatting, no extra text.`;

  const strategicPrompt = `You are an expert equity research analyst. Synthesize ${QUARTER} ${YEAR} Strategic themes across:

CPG companies: Unilever, Mondelez, Nestlé, PepsiCo, General Mills, Coca-Cola Company, Danone, Keurig Dr Pepper, Hershey Company, Kraft Heinz, Barry Callebaut
Appliances companies: SharkNinja, Haier

Audience: senior leadership. Tone: formal, decision-oriented.

### CRITICAL: Use web_search and web_fetch to read actual ${QUARTER} ${YEAR} sources. Never fabricate. Mark "NOT VERIFIED" if a source cannot be found/accessed for a company.

### Allowed Sources
Same as macro stage (CALL/PRES/FILING/Analyst reports — Barclays, Jefferies, Goldman Sachs)

### Focus of Analysis (Strict)
Extract only strategic and competitive themes:
- M&A, divestitures, separations/spin-offs
- Rebranding/restructuring/operating-model changes
- Geographic expansion or exit
- Notable launches and innovation platforms
- Portfolio adjustments (premiumization, health & wellness, value tiers)
- Digital/data/D2C initiatives
- Pricing strategy and pack/price architecture
- Competitive landscape (private label, consumer fatigue, retailer dynamics, share gains/losses)
- Guidance language linking macro assumptions to strategic choices

Exclude: pure macro commentary (FX, interest rates, tariffs, generic consumer demand, ESG) unless explicitly tied to a strategic pivot.

### Synthesis Rule (Frequency-Driven)
- 7+ companies mention a theme → Key Cross-Sector Theme
- 4–6 companies mention a theme → Supporting Insight
- 1–3 companies mention a theme → Ignore, unless a "weak but notable outlier" (max 3 bullets total)

### Citations (same format as macro stage)
Every claim must have inline citations: [CompanyCode SourceType YYYY-MM-DD locator]

### Output Structure (return as JSON)
{
  "executive_synthesis": [ { "theme": "...", "citation": "...", "action": "...", "regional_nuance": "..." } ],
  "theme_frequency_table": [ { "theme": "...", "company_count": 0, "companies": ["UL","MDLZ"], "summary": "...", "evidence_citations": ["...", "..."] } ],
  "deep_dive_cases": [
    {
      "company": "...",
      "initiative_type": "M&A | Separation | Divestiture | Rebranding | Restructuring | Digital | Pricing Pivot | Portfolio Optimization | Innovation | Channel Mix | Geographic Expansion | Notable Launch",
      "title": "...",
      "what_announced": "... [with citations]",
      "strategic_rationale": "... [with citations]",
      "financial_impact": "... [only figures from sources, with citations]",
      "execution_status": "announced | regulatory review | in-progress | completed",
      "execution_risks": "..."
    }
  ],
  "source_log": [ { "ref_code": "...", "company": "...", "source_type": "...", "title": "...", "publisher": "...", "date": "...", "locator": "...", "url": "...", "quote": "...", "notes": "...", "group": "CPG" } ],
  "verification_status": { "Unilever": "VERIFIED", "SomeCompany": "NOT VERIFIED - reason" }
}

Return ONLY valid JSON, no markdown formatting, no extra text.`;

  const prompt = stage === 'macro' ? macroPrompt : strategicPrompt;

  let upstream;
  try {
    upstream = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'anthropic-beta': 'web-search-2025-03-05'
      },
      body: JSON.stringify({
        model: 'claude-opus-4-8',
        max_tokens: 16000,
        tools: [{ type: 'web_search_20250305', name: 'web_search', max_uses: 30 }],
        messages: [{ role: 'user', content: prompt }]
      })
    });
  } catch (err) {
    return { statusCode: 502, body: JSON.stringify({ error: 'Failed to reach Anthropic API: ' + err.message }) };
  }

  if (!upstream.ok) {
    const err = await upstream.json().catch(() => ({}));
    return {
      statusCode: upstream.status,
      body: JSON.stringify({ error: (err && err.error && err.error.message) || ('Anthropic API error ' + upstream.status) })
    };
  }

  const data = await upstream.json();
  const textBlocks = (data.content || []).filter(b => b.type === 'text' && b.text && b.text.trim());

  for (let i = textBlocks.length - 1; i >= 0; i--) {
    let raw = textBlocks[i].text.trim()
      .replace(/^```(?:json)?\s*/im, '').replace(/\s*```\s*$/im, '').trim();

    const start = raw.indexOf('{');
    const end = raw.lastIndexOf('}');
    if (start !== -1 && end > start) {
      try {
        const result = JSON.parse(raw.slice(start, end + 1));
        if (result && typeof result === 'object') {
          return {
            statusCode: 200,
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(result)
          };
        }
      } catch (_) {}
    }
  }

  return {
    statusCode: 500,
    body: JSON.stringify({ error: 'Could not parse structured JSON from the Claude response. Try again.' })
  };
};
