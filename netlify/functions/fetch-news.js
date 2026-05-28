exports.handler = async function(event) {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: JSON.stringify({ error: 'Method not allowed' }) };
  }

  let apiKey, topic;
  try {
    ({ apiKey, topic } = JSON.parse(event.body || '{}'));
  } catch {
    return { statusCode: 400, body: JSON.stringify({ error: 'Invalid JSON body' }) };
  }

  if (!apiKey || !topic) {
    return { statusCode: 400, body: JSON.stringify({ error: 'apiKey and topic are required' }) };
  }

  const prompt =
    `Search the web for the 8 most important and recent news articles about: "${topic}".\n` +
    `Return a JSON array where each item has:\n` +
    `- title: headline in English\n` +
    `- summary: 2-3 sentence summary in English\n` +
    `- source: publication name\n` +
    `- date: publication date\n` +
    `- url: link to original article\n\n` +
    `Return only valid JSON, no markdown, no extra text.`;

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
        model: 'claude-sonnet-4-20250514',
        max_tokens: 4096,
        tools: [{ type: 'web_search_20250305', name: 'web_search', max_uses: 5 }],
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
    const start = raw.indexOf('['), end = raw.lastIndexOf(']');
    if (start !== -1 && end > start) {
      try {
        const articles = JSON.parse(raw.slice(start, end + 1));
        if (Array.isArray(articles) && articles.length > 0) {
          return {
            statusCode: 200,
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(articles)
          };
        }
      } catch (_) {}
    }
  }

  return { statusCode: 500, body: JSON.stringify({ error: 'Could not parse articles from the Claude response. Try again.' }) };
};
