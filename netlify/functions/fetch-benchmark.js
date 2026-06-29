function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': 'https://news-digest-ag1.pages.dev',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Content-Type': 'application/json'
  };
}

function resp(statusCode, body) {
  return { statusCode: statusCode, headers: corsHeaders(), body: JSON.stringify(body) };
}

exports.handler = async function(event) {
  try {
    if (event.httpMethod === 'OPTIONS') {
      return { statusCode: 200, headers: corsHeaders(), body: '' };
    }
    if (event.httpMethod !== 'POST') {
      return resp(405, { error: 'Method not allowed' });
    }

    let apiKey, stage, quarter, year, companies;
    try {
      ({ apiKey, stage, quarter, year, companies } = JSON.parse(event.body || '{}'));
    } catch {
      return resp(400, { error: 'Invalid JSON body' });
    }

    if (!apiKey) return resp(400, { error: 'apiKey is required' });
    if (!stage || !['macro', 'strategic'].includes(stage)) {
      return resp(400, { error: 'stage must be "macro" or "strategic"' });
    }
    if (!quarter || !year) return resp(400, { error: 'quarter and year are required' });
    if (!companies || !Array.isArray(companies) || !companies.length) {
      return resp(400, { error: 'companies array is required' });
    }

    const QUARTER = quarter;
    const YEAR = year;

    const cpg = companies.filter(c => c.group !== 'Appliances').map(c => c.name).join(', ');
    const appliances = companies.filter(c => c.group === 'Appliances').map(c => c.name).join(', ');

    const COMPANY_SOURCES = companies.map(function(c) {
      const parts = [];
      if (c.earningsCallUrl)  parts.push('earningsCall: ' + c.earningsCallUrl);
      if (c.presentationUrl)  parts.push('presentation: ' + c.presentationUrl);
      if (c.filingUrl)        parts.push('filing: ' + c.filingUrl);
      if (!parts.length) return c.name + ': [NO URLS PROVIDED — SKIP THIS COMPANY]';
      return c.name + ': [' + parts.join('], [') + ']';
    }).join('\n');

    const macroPrompt =
`You are an expert equity research analyst. Synthesize ${QUARTER} ${YEAR} macro themes across:

CPG companies: ${cpg}
Appliances companies: ${appliances}

### Allowed Sources
ONLY the following pre-fetched documents. Do NOT search for any additional sources.
${COMPANY_SOURCES}
(format: "CompanyName: [earningsCall: url], [presentation: url], [filing: url]" — null = not available)

### Focus of Analysis (Strict)
Extract only macro environment themes:
- Consumer demand, affordability, and consumer sentiment
- Input cost inflation and commodity price outlook (cocoa, sugar, coffee, packaging, oil, energy)
- FX pressures and geographic exposure
- Trade policy, tariffs, and geopolitical risk
- Supply chain resilience, logistics stability, and inventory strategy
- Labor markets and wage inflation
- Guidance language referencing macro assumptions
- Developed vs emerging markets

Exclude: brand launches, marketing stories, sustainability messaging, product-level updates
— unless directly linked to macro cost, volume, pricing, or supply chain context.

### Synthesis Rule (Frequency-Driven)
Identify patterns across companies. Include a theme ONLY if it appears in multiple cases.
- 7+ companies mention a theme → Key Cross-Sector Theme
- 4–6 companies mention a theme → Supporting Insight
- 1–3 companies mention a theme → Ignore, unless "weak but notable outlier" (max 3 bullets total)

### Citations (Non-Negotiable)
Every claim: [CompanyCode SourceType YYYY-MM-DD locator]
SourceType: CALL, PRES, FILING
Locator: CALL = timestamp or Q&A number; PRES/FILING = p.X or slide Y
No speculation. No fabrication. Flag conflicting data explicitly.

### Output — return ONLY valid JSON:
{
  "executive_synthesis": [
    { "theme": "...", "citation": "...", "action": "1-2 line recommendation for decision makers" }
  ],
  "theme_frequency_table": [
    {
      "theme": "...",
      "mention_count": 0,
      "companies": ["UL", "KHC"],
      "summary": "1-2 line strategic synthesis",
      "evidence_citations": ["[UL CALL 2026-04-30 Q&A-3]"]
    }
  ],
  "source_log": [
    {
      "ref_code": "UL CALL 2026-04-30",
      "company": "Unilever",
      "source_type": "CALL",
      "title": "Q1 2026 Trading Statement Transcript",
      "publisher": "Unilever IR",
      "date": "2026-04-30",
      "locator": "Q&A-3",
      "url": "https://...",
      "quote": "verbatim quote max 25 words",
      "notes": "why this citation matters",
      "group": "CPG"
    }
  ],
  "verification_status": {
    "Unilever": "VERIFIED",
    "SomeCompany": "NOT VERIFIED - all URLs null"
  }
}`;

    const strategicPrompt =
`You are an expert equity research analyst. Synthesize ${QUARTER} ${YEAR} Strategic themes across:

CPG companies: ${cpg}
Appliances companies: ${appliances}
Audience: senior leadership. Tone: formal, decision-oriented.

### Allowed Sources
ONLY the following pre-fetched documents. Do NOT search for any additional sources.
${COMPANY_SOURCES}

### Focus of Analysis (Strict)
Extract only strategic and competitive themes:
- M&A, divestitures, separations/spin-offs
- Rebranding/restructuring/operating-model changes
- Geographic expansion or exit
- Notable launches and innovation platforms
- Portfolio adjustments (premiumization, health & wellness, value tiers)
- Digital/data/D2C initiatives
- Pricing strategy and pack/price architecture (volume vs. pricing growth balance)
- Competitive landscape (private label, consumer fatigue, retailer dynamics, share gains/losses)
- Guidance language linking macro assumptions to strategic choices

Exclude: pure macro commentary (FX, interest rates, tariffs, generic consumer demand, ESG)
unless explicitly tied to a strategic pivot or competitive move.

### Synthesis Rule (Frequency-Driven)
- 7+ companies mention a theme → Key Cross-Sector Theme
- 4–6 companies mention a theme → Supporting Insight
- 1–3 companies mention a theme → Ignore, unless "weak but notable outlier" (max 3 bullets total)

### Citations (same format as macro stage)
Every claim: [CompanyCode SourceType YYYY-MM-DD locator]

### Deep-Dive Cases (~20 cases)
Select the ~20 most material and well-documented strategic initiatives.
Cover multiple initiative types and multiple companies.
Each case must be evidenced in the provided sources only — no inference from outside.

### Output — return ONLY valid JSON:
{
  "executive_synthesis": [
    { "theme": "...", "citation": "...", "action": "...", "regional_nuance": "..." }
  ],
  "theme_frequency_table": [
    {
      "theme": "...",
      "company_count": 0,
      "companies": ["UL", "MDLZ"],
      "summary": "...",
      "evidence_citations": ["..."]
    }
  ],
  "deep_dive_cases": [
    {
      "company": "Unilever",
      "initiative_type": "Separation",
      "title": "Foods-McCormick Separation",
      "what_announced": "... [UL CALL 2026-04-30 Q&A-1]",
      "strategic_rationale": "... [UL PRES 2026-04-30 slide 8]",
      "financial_impact": "... [UL FILING 2026-04-30 p.12]",
      "execution_status": "announced | regulatory review | in-progress | completed",
      "execution_risks": "..."
    }
  ],
  "source_log": [
    {
      "ref_code": "UL CALL 2026-04-30",
      "company": "Unilever",
      "source_type": "CALL",
      "title": "Q1 2026 Trading Statement Transcript",
      "publisher": "Unilever IR",
      "date": "2026-04-30",
      "locator": "Q&A-3",
      "url": "https://...",
      "quote": "verbatim quote max 25 words",
      "notes": "why this citation matters",
      "group": "CPG"
    }
  ],
  "verification_status": {
    "Unilever": "VERIFIED",
    "SomeCompany": "NOT VERIFIED - all URLs null"
  }
}`;

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
          tools: [{ type: 'web_fetch_20250910', name: 'web_fetch' }],
          messages: [{ role: 'user', content: prompt }]
        })
      });
    } catch (err) {
      return resp(502, { error: 'Failed to reach Anthropic API: ' + err.message });
    }

    if (!upstream.ok) {
      const err = await upstream.json().catch(() => ({}));
      return resp(upstream.status, { error: (err && err.error && err.error.message) || ('Anthropic API error ' + upstream.status) });
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
            return resp(200, result);
          }
        } catch (_) {}
      }
    }

    return resp(500, { error: 'Could not parse structured JSON from the Claude response. Try again.' });

  } catch (err) {
    return resp(500, { error: 'Unhandled error: ' + err.message });
  }
};
