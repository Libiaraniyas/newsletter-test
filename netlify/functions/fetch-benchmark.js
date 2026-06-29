exports.handler = async function(event) {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: JSON.stringify({ error: 'Method not allowed' }) };
  }

  let apiKey, stage, quarter, year, sourceLinks, companies;
  try {
    ({ apiKey, stage, quarter, year, sourceLinks, companies } = JSON.parse(event.body || '{}'));
  } catch {
    return { statusCode: 400, body: JSON.stringify({ error: 'Invalid JSON body' }) };
  }

  if (!apiKey) return { statusCode: 400, body: JSON.stringify({ error: 'apiKey is required' }) };
  if (!stage || !['macro', 'strategic'].includes(stage)) {
    return { statusCode: 400, body: JSON.stringify({ error: 'stage must be "macro" or "strategic"' }) };
  }
  if (!quarter || !year) return { statusCode: 400, body: JSON.stringify({ error: 'quarter and year are required' }) };

  const QUARTER = quarter;
  const YEAR = year;

  const DEFAULT_CPG = ['Unilever', 'Mondelez', 'Nestlé', 'PepsiCo', 'Coca-Cola Company', 'Danone', 'Barry Callebaut', 'Keurig Dr Pepper', 'General Mills', 'Hershey Company', 'Kraft Heinz'];
  const DEFAULT_APPLIANCES = ['SharkNinja', 'Haier'];

  const CPG_LIST = (companies && companies.cpg && companies.cpg.length) ? companies.cpg : DEFAULT_CPG;
  const APPLIANCES_LIST = (companies && companies.appliances && companies.appliances.length) ? companies.appliances : DEFAULT_APPLIANCES;
  const ALL_COMPANIES = CPG_LIST.concat(APPLIANCES_LIST);

  function buildSourceSection(links) {
    if (!links || !Object.keys(links).length) return { section: '', hasLinks: false };

    const withUrlEntries = [];
    const companiesWithUrls = [];
    const companiesWithoutUrls = [];

    ALL_COMPANIES.forEach(function(co) {
      const s = (links[co]) || {};
      const parts = [];
      if (s.earningsCall)         parts.push('  - Earnings Call: ' + s.earningsCall);
      if (s.investorPresentation) parts.push('  - Investor Presentation: ' + s.investorPresentation);
      if (s.filing)               parts.push('  - 10-Q/Filing: ' + s.filing);
      if (s.barclays)             parts.push('  - Barclays Report: ' + s.barclays);
      if (s.jefferies)            parts.push('  - Jefferies Report: ' + s.jefferies);
      if (s.goldman)              parts.push('  - Goldman Sachs Report: ' + s.goldman);
      // backward compat with old 3-field schema
      if (!s.barclays && !s.jefferies && !s.goldman && s.analystReport) {
        parts.push('  - Analyst Report: ' + s.analystReport);
      }
      if (parts.length) {
        companiesWithUrls.push(co);
        withUrlEntries.push(co + ':\n' + parts.join('\n'));
      } else {
        companiesWithoutUrls.push(co);
      }
    });

    if (!companiesWithUrls.length) return { section: '', hasLinks: false };

    var section = '### SOURCE URL INSTRUCTIONS — READ CAREFULLY BEFORE STARTING\n\n';
    section += '**MANDATORY: Companies with pre-approved source URLs**\n';
    section += 'For the companies listed below, you MUST web_fetch the provided URLs and base your analysis SOLELY on what those documents contain. ';
    section += 'Do NOT use web_search for these companies — do not search for alternative or supplementary sources. ';
    section += 'If a provided URL fails to load, mark that company as "NOT VERIFIED - URL failed to load" and exclude it from the analysis.\n\n';
    section += withUrlEntries.join('\n\n') + '\n\n';

    if (companiesWithoutUrls.length) {
      section += '**Companies without pre-provided URLs — use web_search to find ' + QUARTER + ' ' + YEAR + ' sources**\n';
      section += companiesWithoutUrls.join(', ') + '\n\n';
    }

    return { section: section, hasLinks: true, companiesWithUrls: companiesWithUrls, companiesWithoutUrls: companiesWithoutUrls };
  }

  var built = buildSourceSection(sourceLinks || {});
  var sourceSection = built.section;
  var hasLinks = built.hasLinks;
  var companiesWithUrls = built.companiesWithUrls || [];
  var companiesWithoutUrls = built.companiesWithoutUrls || [];

  var criticalInstruction = hasLinks
    ? '### CRITICAL SOURCE RULES\n' +
      '- **Companies with pre-approved URLs** (' + companiesWithUrls.join(', ') + '): web_fetch ONLY the provided URLs. Do NOT use web_search for these companies under any circumstances.\n' +
      '- **Companies without pre-provided URLs** (' + companiesWithoutUrls.join(', ') + '): use web_search to find their ' + QUARTER + ' ' + YEAR + ' earnings call transcripts, investor presentations, 10-Q filings, and analyst reports (Barclays, Jefferies, Goldman Sachs).\n' +
      '- For any company where a provided URL fails to load: mark "NOT VERIFIED - URL failed to load" and exclude from analysis. Do NOT fall back to web_search.\n' +
      '- For any company where web_search yields no verifiable ' + QUARTER + ' ' + YEAR + ' source: mark "NOT VERIFIED - no source found" and exclude.\n' +
      '- NEVER fabricate or draw on model memory. Every claim must trace to a document fetched in this session.'
    : '### CRITICAL: You must use web_search and web_fetch to find and READ the actual source documents for each company before making any claim. Do NOT rely on general knowledge about these companies. If you cannot find or access a verifiable ' + QUARTER + ' ' + YEAR + ' source for a company, explicitly state "NOT VERIFIED" for that company and exclude it from the analysis rather than guessing.';

  var CPG_STR = CPG_LIST.join(', ');
  var APPLIANCES_STR = APPLIANCES_LIST.join(', ');

  var macroJsonSchema =
    '{\n' +
    '  "executive_synthesis": [\n' +
    '    {\n' +
    '      "theme": "Clear statement of the macro theme",\n' +
    '      "citation": "[CompanyCode SourceType YYYY-MM-DD locator; ...]",\n' +
    '      "recommended_action": "1-2 lines recommended action for senior leadership"\n' +
    '    }\n' +
    '  ],\n' +
    '  "theme_frequency_table": [\n' +
    '    {\n' +
    '      "theme": "Theme name",\n' +
    '      "mention_count": 0,\n' +
    '      "companies": ["UL", "KHC"],\n' +
    '      "summary": "1-2 line synthesis of what the theme means",\n' +
    '      "evidence_citations": ["[citation1]", "[citation2]", "[citation3]"]\n' +
    '    }\n' +
    '  ],\n' +
    '  "source_log": [\n' +
    '    {\n' +
    '      "ref_code": "UL CALL 2026-04-24 00:12:33",\n' +
    '      "company": "Unilever",\n' +
    '      "source_type": "CALL",\n' +
    '      "title": "Document title",\n' +
    '      "publisher": "Company or bank name",\n' +
    '      "date": "YYYY-MM-DD",\n' +
    '      "locator": "00:12:33 or p.X",\n' +
    '      "url": "https://...",\n' +
    '      "quote": "Verbatim quote max 25 words",\n' +
    '      "notes": "Why this citation matters",\n' +
    '      "group": "CPG or Appliances"\n' +
    '    }\n' +
    '  ],\n' +
    '  "bibliography": [\n' +
    '    {\n' +
    '      "company": "Unilever",\n' +
    '      "ticker": "UL",\n' +
    '      "sources": [\n' +
    '        { "type": "CALL", "title": "...", "publisher": "...", "url": "...", "access_date": "YYYY-MM-DD" }\n' +
    '      ]\n' +
    '    }\n' +
    '  ],\n' +
    '  "verification_status": {\n' +
    '    "Unilever": "VERIFIED",\n' +
    '    "SomeCompany": "NOT VERIFIED - reason"\n' +
    '  }\n' +
    '}';

  var strategicJsonSchema =
    '{\n' +
    '  "executive_synthesis": [\n' +
    '    {\n' +
    '      "theme": "Clear strategic theme statement",\n' +
    '      "citation": "[CompanyCode SourceType YYYY-MM-DD locator; ...]",\n' +
    '      "recommended_action": "1-2 lines recommended action",\n' +
    '      "regional_nuance": "Regional distinctions if applicable, empty string if none"\n' +
    '    }\n' +
    '  ],\n' +
    '  "theme_frequency_table": [\n' +
    '    {\n' +
    '      "theme": "Theme name",\n' +
    '      "company_count": 0,\n' +
    '      "companies": ["UL", "MDLZ"],\n' +
    '      "summary": "1-2 line strategic synthesis",\n' +
    '      "evidence_citations": ["[citation1]", "[citation2]"]\n' +
    '    }\n' +
    '  ],\n' +
    '  "deep_dive_cases": [\n' +
    '    {\n' +
    '      "company": "Company name",\n' +
    '      "initiative_type": "M&A | Separation | Divestiture | Rebranding | Restructuring | Digital | Pricing Pivot | Portfolio Optimization | Innovation | Channel Mix | Geographic Expansion | Notable Launch",\n' +
    '      "title": "Initiative title",\n' +
    '      "what_announced": "Description with structure, timing, perimeter, key terms. Include inline citations.",\n' +
    '      "strategic_rationale": "Stated rationale and strategic logic. Distinguish explicit statements from interpretation. All source-backed.",\n' +
    '      "financial_impact": "Order of magnitude figures only from sources, with citations. Empty string if none disclosed.",\n' +
    '      "execution_status": "announced | regulatory review | in-progress | completed",\n' +
    '      "execution_risks": "Key execution risks or dependencies flagged by management or analysts"\n' +
    '    }\n' +
    '  ],\n' +
    '  "source_log": [\n' +
    '    {\n' +
    '      "ref_code": "UL CALL 2026-04-24 00:12:33",\n' +
    '      "company": "Unilever",\n' +
    '      "source_type": "CALL",\n' +
    '      "title": "Document title",\n' +
    '      "publisher": "Company or bank name",\n' +
    '      "date": "YYYY-MM-DD",\n' +
    '      "locator": "00:12:33 or p.X",\n' +
    '      "url": "https://...",\n' +
    '      "quote": "Verbatim quote max 25 words",\n' +
    '      "notes": "Why this citation matters",\n' +
    '      "group": "CPG or Appliances"\n' +
    '    }\n' +
    '  ],\n' +
    '  "bibliography": [\n' +
    '    {\n' +
    '      "company": "Unilever",\n' +
    '      "ticker": "UL",\n' +
    '      "sources": [\n' +
    '        { "type": "CALL", "title": "...", "publisher": "...", "url": "...", "access_date": "YYYY-MM-DD" }\n' +
    '      ]\n' +
    '    }\n' +
    '  ],\n' +
    '  "verification_status": {\n' +
    '    "Unilever": "VERIFIED",\n' +
    '    "SomeCompany": "NOT VERIFIED - reason"\n' +
    '  }\n' +
    '}';

  var macroPrompt =
    'You are an expert equity research analyst. Synthesize ' + QUARTER + ' ' + YEAR + ' *macro* themes across:\n\n' +
    '**CPG companies:** ' + CPG_STR + '\n' +
    '**Appliances companies:** ' + APPLIANCES_STR + '\n\n' +
    '---\n' +
    '### Allowed Sources\n' +
    'Use only the following sources (and URLs / links contained in them). Do not introduce any additional external sources.\n' +
    '- ' + QUARTER + ' ' + YEAR + ' earnings call transcripts (with timestamps)\n' +
    '- ' + QUARTER + ' ' + YEAR + ' investor presentations (with slide/page numbers)\n' +
    '- ' + QUARTER + ' ' + YEAR + ' filings (10-Q/annual report excerpts; page numbers)\n' +
    '- Analyst reports from Barclays, Jefferies, and Goldman Sachs (page/section numbers)\n' +
    '- Any links or exhibits that are part of the above documents (e.g., appendices or fact sheets hosted on the same IR platforms)\n' +
    '- Additional relevant and reliable sources that provide verifiable macroeconomic commentary (e.g., broker research, credible financial media summaries)\n\n' +
    sourceSection + criticalInstruction + '\n\n' +
    '---\n' +
    '### Focus of Analysis (Strict)\n' +
    'Extract only macro environment themes, such as:\n' +
    '- Consumer demand, affordability, and consumer sentiment\n' +
    '- Input cost inflation and commodity price outlook (e.g., cocoa, sugar, coffee, packaging, oil, energy)\n' +
    '- FX pressures and geographic exposure\n' +
    '- Trade policy, tariffs, and geopolitical risk\n' +
    '- Supply chain resilience, logistics stability, and inventory strategy\n' +
    '- Labor markets and wage inflation\n' +
    '- Guidance language referencing FY' + YEAR + ' macro assumptions\n' +
    '- Differences and outlooks in developed vs emerging markets\n\n' +
    'Exclude: brand launches, marketing stories, sustainability messaging, and product-level updates — unless directly linked to macro cost, volume, pricing, or supply chain context.\n\n' +
    '---\n' +
    '### Synthesis Rule (Frequency-Driven)\n' +
    'Do not merely restate what each company said. Identify patterns across companies and include a theme only if it appears in multiple cases.\n' +
    '- If 7+ companies mention a theme → Key Cross-Sector Theme\n' +
    '- If 4–6 companies mention a theme → Supporting Insight\n' +
    '- If 1–3 companies mention a theme → Ignore, unless a "weak but notable outlier" (max 3 bullets total)\n\n' +
    '---\n' +
    '### Citations & Traceability (Non-Negotiable)\n' +
    'Every claim must have inline citations: [CompanyCode SourceType YYYY-MM-DD locator]\n' +
    'SourceType: CALL, PRES, FILING, BARCLAYS, JEFFERIES, GOLDMAN, or OTHER\n' +
    'Locator: CALL = hh:mm:ss timestamp (or Q&A number); PRES/FILING/Analyst = p.X or slide Y\n\n' +
    '---\n' +
    '### Style & Quality\n' +
    'Synthesize; be crisp. No filler. Use quotes sparingly, always with locators. No speculation; only source-backed statements. Flag conflicting data explicitly with both citations. Maintain clarity, comparability, and decision usefulness throughout.\n\n' +
    '### Output Structure (return as JSON)\n' +
    macroJsonSchema + '\n\n' +
    'Return ONLY valid JSON, no markdown formatting, no extra text.';

  var strategicPrompt =
    'You are an expert equity research analyst. Synthesize ' + QUARTER + ' ' + YEAR + ' strategic themes across:\n\n' +
    '**CPG companies:** ' + CPG_STR + '\n' +
    '**Appliances companies:** ' + APPLIANCES_STR + '\n\n' +
    'Audience: senior leadership. Tone: formal, decision-oriented.\n\n' +
    '---\n' +
    '### Allowed Sources\n' +
    'Use only the following sources (and URLs contained in them). Do not introduce any additional external sources.\n' +
    '- ' + QUARTER + ' ' + YEAR + ' earnings call transcripts (with timestamps)\n' +
    '- ' + QUARTER + ' ' + YEAR + ' investor presentations (with slide/page numbers)\n' +
    '- ' + QUARTER + ' ' + YEAR + ' filings (10-Q/annual report excerpts; page numbers)\n' +
    '- Analyst reports from Barclays, Jefferies, and Goldman Sachs (page/section numbers)\n' +
    '- Any links or exhibits that are part of the above documents (e.g., appendices or fact sheets hosted on the same IR platforms)\n\n' +
    sourceSection + criticalInstruction + '\n\n' +
    '---\n' +
    '### Focus of Analysis (Strict)\n' +
    'Extract only strategic and competitive themes, such as:\n' +
    '- M&A, divestitures, separations/spin-offs\n' +
    '- Rebranding/restructuring/operating-model changes\n' +
    '- Geographic expansion or exit\n' +
    '- Notable launches and innovation platforms\n' +
    '- Portfolio adjustments (premiumization, health & wellness, value tiers)\n' +
    '- Digital/data/D2C initiatives\n' +
    '- Pricing strategy and pack/price architecture (including volume vs. pricing growth balance)\n' +
    '- Competitive landscape (private label, consumer fatigue, retailer dynamics, share gains/losses)\n' +
    '- Guidance language that clearly links FY' + YEAR + ' macro assumptions to strategic choices (not just to P&L)\n\n' +
    'Exclude: pure macro commentary (FX, interest rates, tariffs, generic consumer demand, ESG/sustainability) unless explicitly tied to a strategic pivot or competitive move.\n\n' +
    '---\n' +
    '### Synthesis Rule (Frequency-Driven)\n' +
    '- 7+ companies mention a theme → Key Cross-Sector Theme\n' +
    '- 4–6 companies mention a theme → Supporting Insight\n' +
    '- 1–3 companies mention a theme → Ignore, unless a "weak but notable outlier" (max 3 bullets total)\n\n' +
    '---\n' +
    '### Citations & Traceability (Non-Negotiable)\n' +
    'Every claim must have inline citations: [CompanyCode SourceType YYYY-MM-DD locator]\n' +
    'SourceType: CALL, PRES, FILING, BARCLAYS, JEFFERIES, GOLDMAN, or OTHER\n' +
    'Locator: CALL = hh:mm:ss timestamp (or Q&A number); PRES/FILING/Analyst = p.X or slide Y\n\n' +
    '---\n' +
    '### Strategic Initiative Deep-Dive Cases (~20 cases)\n' +
    'Produce approximately 20 deep-dive case studies of specific strategic initiatives drawn only from the Allowed Sources.\n\n' +
    'Initiative types to cover:\n' +
    'M&A (acquisitions, mergers, JVs) | Separations/spin-offs/demergers | Divestitures and asset sales | Rebranding (corporate or major brand) | Restructuring (headcount reduction, operating-model changes) | Digital initiatives (AI, data platforms, D2C, e-commerce, smart/connected products) | Volume vs. pricing growth strategy (pivot from price-led to volume-led, pack-price architecture, promo strategy) | Portfolio optimization (category exits/entries, premiumization, health & wellness repositioning, value tiers) | Product innovation and premiumization platforms | Channel mix changes (modern trade, discounters, e-commerce, away-from-home, D2C) | Geographic expansion or exit | Notable launches aimed at category penetration\n\n' +
    'Selection rules:\n' +
    '- ~20 most material and well-documented initiatives across the company set\n' +
    '- Cover multiple initiative types (not all M&A)\n' +
    '- Cover multiple companies including at least some Appliances cases\n' +
    '- Each initiative must be clearly evidenced in ' + QUARTER + ' ' + YEAR + ' sources only\n\n' +
    '---\n' +
    '### Style & Quality\n' +
    'Be crisp, analytical, and formal. No filler. Use quotes sparingly, always with locators. No speculation: all statements must be source-backed. Explicitly flag conflicting data or guidance with citations for both sides. Maintain clarity, comparability, and decision usefulness throughout, with particular focus on portfolio strategy, capital allocation, geographic focus, and competitive positioning.\n\n' +
    '### Output Structure (return as JSON)\n' +
    strategicJsonSchema + '\n\n' +
    'Return ONLY valid JSON, no markdown formatting, no extra text.';

  var prompt = stage === 'macro' ? macroPrompt : strategicPrompt;

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
