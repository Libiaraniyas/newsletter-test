exports.handler = async function(event) {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: JSON.stringify({ error: 'Method not allowed' }) };
  }

  let apiKey, companies, quarter, year;
  try {
    ({ apiKey, companies, quarter, year } = JSON.parse(event.body || '{}'));
  } catch {
    return { statusCode: 400, body: JSON.stringify({ error: 'Invalid JSON body' }) };
  }

  if (!apiKey) return { statusCode: 400, body: JSON.stringify({ error: 'apiKey is required' }) };
  if (!companies || !Array.isArray(companies) || !companies.length) {
    return { statusCode: 400, body: JSON.stringify({ error: 'companies array is required' }) };
  }
  if (!quarter || !year) return { statusCode: 400, body: JSON.stringify({ error: 'quarter and year are required' }) };

  const companyList = companies.map(function(c) { return '- ' + c.name + ' (' + c.group + ')'; }).join('\n');

  const prompt =
    'You are a financial research assistant. For each company below, find their official ' + quarter + ' ' + year + ' investor relations source documents.\n\n' +
    'Companies to research:\n' + companyList + '\n\n' +
    'For EACH company, use web_search and web_fetch to find and verify:\n' +
    '1. ' + quarter + ' ' + year + ' earnings call transcript URL — check the company IR website, Seeking Alpha, or official transcript providers\n' +
    '2. ' + quarter + ' ' + year + ' investor presentation URL — official slides from the company IR website\n' +
    '3. ' + quarter + ' ' + year + ' 10-Q or annual report filing URL — SEC EDGAR for US companies, SEDAR for Canadian companies, or company IR page\n' +
    '4. Barclays equity research report for ' + quarter + ' ' + year + ' — include only if a publicly accessible URL is found (most are paywalled)\n' +
    '5. Jefferies equity research report for ' + quarter + ' ' + year + ' — include only if a publicly accessible URL is found\n' +
    '6. Goldman Sachs equity research report for ' + quarter + ' ' + year + ' — include only if a publicly accessible URL is found\n\n' +
    'If ' + quarter + ' ' + year + ' results are NOT yet published for a company:\n' +
    '- Search their investor relations page or IR calendar for the expected release date\n' +
    '- Set status to "EXPECTED: YYYY-MM-DD" with the actual expected date\n' +
    '- Cite the reliable source that confirmed this date in the notes field\n\n' +
    'Rules:\n' +
    '- ONLY return URLs you have actually verified by fetching — never guess or fabricate URLs\n' +
    '- Set a URL to null if you could not find or verify it\n' +
    '- Use the exact company names as given in the list above as the JSON keys\n\n' +
    'Return ONLY a valid JSON object, no markdown, no extra text:\n' +
    '{\n' +
    '  "ExactCompanyName": {\n' +
    '    "earningsCall": "verified_url_or_null",\n' +
    '    "investorPresentation": "verified_url_or_null",\n' +
    '    "filing": "verified_url_or_null",\n' +
    '    "barclays": "verified_url_or_null",\n' +
    '    "jefferies": "verified_url_or_null",\n' +
    '    "goldman": "verified_url_or_null",\n' +
    '    "status": "PUBLISHED or EXPECTED: YYYY-MM-DD",\n' +
    '    "notes": "brief note if expected date or anything unusual, empty string otherwise"\n' +
    '  }\n' +
    '}';

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
        max_tokens: 8000,
        tools: [{ type: 'web_search_20250305', name: 'web_search', max_uses: 40 }],
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

  return { statusCode: 500, body: JSON.stringify({ error: 'Could not parse links from Claude response. Try again.' }) };
};
