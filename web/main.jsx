import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

const examples = {
  en: ['What does the safe water appeal fund?', 'What belongs in a donor update?', 'How should we document image consent?'],
  es: ['¿Qué financia la campaña de agua segura?', '¿Qué debe incluir un informe a donantes?', '¿Cómo se documenta el consentimiento para imágenes?'],
};
const modes = {llm: 'LLM-selected answer', excerpts: 'Source excerpts · no model configured', fallback: 'Source excerpts · model unavailable or output rejected', insufficient: 'Insufficient evidence'};

function Source({source}) {
  return <article className="source" id={source.id}>
    <span className="tag">{source.status} · {source.locale.toUpperCase()} · v{source.version}</span>
    <h3>{source.title}</h3>
    <code>{source.id}</code>
    {source.text && <p lang={source.locale}>{source.text}</p>}
  </article>;
}

function App() {
  const [locale, setLocale] = useState('en');
  const [question, setQuestion] = useState('');
  const [tab, setTab] = useState('ask');
  const [library, setLibrary] = useState([]);
  const [libraryError, setLibraryError] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch('/api/sources').then(r => {
      if (!r.ok) throw Error();
      return r.json();
    }).then(setLibrary).catch(() => setLibraryError(true));
  }, []);

  async function ask(event) {
    event.preventDefault();
    setBusy(true); setError(''); setResult(null);
    try {
      const response = await fetch('/api/ask', {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({question, locale}),
        signal: AbortSignal.timeout(35000)});
      if (!response.ok) throw Error();
      setResult(await response.json());
    } catch {
      setError('The request could not be completed. Check that the local server is running and try again.');
    } finally {
      setBusy(false);
    }
  }

  return <>
    <header><div className="wrap top"><span className="brand">FIELDNOTES <b>/</b> AI HUB</span><span className="tag">INDEPENDENT MVP · 2026</span></div></header>
    <main className="wrap">
      <div className="hero"><div className="eyebrow">FUNDRAISING KNOWLEDGE WORKSPACE</div>
        <h1>Humanitarian<br/>Fundraising AI Hub</h1>
        <p>Explore a fictional campaign library and draft answers with citations you can check.</p>
      </div>
      <nav aria-label="Workspace">
        <button aria-pressed={tab === 'ask'} onClick={() => setTab('ask')}>Ask the library</button>
        <button aria-pressed={tab === 'library'} onClick={() => setTab('library')}>Source library</button>
      </nav>
      <section className="panel">
        <div className="panel-head"><h2>{tab === 'ask' ? 'Ask a question' : 'Browse sources'}</h2>
          <label>Source language <select value={locale} disabled={busy} onChange={e => {
            setLocale(e.target.value); setQuestion(''); setResult(null); setError('');
          }}><option value="en">English</option><option value="es">Español</option></select></label>
        </div>
        {tab === 'ask' ? <>
          <form onSubmit={ask}>
            <label htmlFor="question">Question</label>
            <textarea id="question" value={question} disabled={busy} onChange={e => setQuestion(e.target.value)} maxLength={400} placeholder={examples[locale][0]} required />
            <div className="examples">{examples[locale].map(example => <button type="button" key={example} disabled={busy} onClick={() => setQuestion(example)}>{example}</button>)}</div>
            <button className="primary" disabled={busy || question.trim().length < 4}>{busy ? 'Working…' : 'Find an answer →'}</button>
          </form>
          <div role="status">{busy && <p>Checking published sources…</p>}{error && <p>{error}</p>}
            {result && <div className="answer">
              <span className="tag">{modes[result.mode]}{result.model && ' · ' + result.model}</span>
              <p className="response" lang={locale}>{result.answer}</p>
              {result.sources.length > 0 && <><h2>Supporting sources</h2><div className="sources">{result.sources.map(source => <Source key={source.id} source={source}/>)}</div></>}
            </div>}
          </div>
        </> : <>
          <p>Published entries can support answers. Drafts appear here as metadata only.</p>
          {libraryError && <p role="alert">The library could not be loaded. Reload to try again.</p>}
          {!libraryError && library.length === 0 && <p role="status">Loading sources…</p>}
          <div className="sources">{library.filter(s => s.locale === locale).map(source => <Source key={source.id} source={source}/>)}</div>
        </>}
      </section>
      <aside>Review any generated draft before reuse. Do not enter donor or beneficiary information.</aside>
    </main>
    <footer className="wrap">An independent project by Alessio D’Amico. Fictional data. No affiliation with or endorsement by UNICEF.</footer>
  </>;
}

createRoot(document.getElementById('root')).render(<App />);
