import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

const locales = {en: 'English', es: 'Español', fr: 'Français'};
const languageOptions = Object.entries(locales).map(([code, label]) => <option key={code} value={code}>{label}</option>);

async function request(path, method = 'GET', body) {
  const response = await fetch('/api/' + path, {method, signal: AbortSignal.timeout(120000),
    ...(body ? {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : {})});
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Check the form and try again.');
  return data;
}

function App() {
  const [tab, setTab] = useState('ask');
  const [locale, setLocale] = useState('en');
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState(null);
  const [library, setLibrary] = useState([]);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const refresh = () => request('sources').then(setLibrary);
  useEffect(() => {refresh().catch(e => setMessage(e.message));}, []);

  async function run(action) {
    setBusy(true); setMessage('');
    try { await action(); } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }

  return <>
    <header><div className="wrap top"><span className="brand">KNOWLEDGE <b>/</b> DECISION SUPPORT</span><span className="tag">LOCAL AI · 2026</span></div></header>
    <main className="wrap">
      <div className="hero">
        <h1>AI Knowledge &amp;<br/>Decision Support Platform</h1>
        <p>Index documents, review what gets published, and ask questions with inspectable sources.</p>
      </div>
      <nav aria-label="Workspace">{[['ask','Ask'],['ingest','Ingest'],['review','Review']].map(([id,label]) =>
        <button key={id} disabled={busy} aria-pressed={tab === id} onClick={() => {setTab(id);setMessage('');}}>{label}</button>)}</nav>
      <section className="panel" aria-busy={busy}>
        {tab === 'ask' && <>
          <div className="panel-head"><h2>Ask published documents</h2><label>Answer language <select value={locale}
            disabled={busy} onChange={e => {setLocale(e.target.value);setResult(null);}}>{languageOptions}</select></label></div>
          <form onSubmit={e => {e.preventDefault();setResult(null);run(async () => setResult(await request('ask','POST',{question,locale})));}}>
            <label htmlFor="question">Question</label>
            <textarea id="question" required minLength={4} maxLength={500} value={question} onChange={e => setQuestion(e.target.value)} disabled={busy}/>
            <button className="primary" disabled={busy || question.trim().length < 4}>Find an answer →</button>
          </form>
          {result && <div className="answer" role="status">
            <span className="tag">{result.mode === 'llm' ? 'Qwen · review before use' : 'Insufficient evidence'}</span>
            <p className="response" lang={locale}>{result.answer}</p>
            {result.sources.length > 0 && <><h2>Cited passages</h2><div className="sources">{result.sources.map(s =>
              <article className="source" key={s.citation}><span className="tag">{s.citation} · {s.locale.toUpperCase()} · v{s.version} · chunk {s.ordinal}</span>
                <h3>{s.title}</h3><p lang={s.locale}>{s.text}</p></article>)}</div></>}
            <p><small>Retrieval: {result.metrics.retrieval_ms} ms · Total: {result.metrics.total_ms} ms
              {result.metrics.generation_ms != null && <> · Generation: {result.metrics.generation_ms} ms · Tokens: {result.metrics.prompt_tokens} in / {result.metrics.generated_tokens} out · {result.metrics.device}</>}
            </small></p>
          </div>}
        </>}
        {tab === 'ingest' && <><h2>Ingest a text document</h2><p>Use the same slug to create a new version. Each upload starts as a draft.</p>
          <form onSubmit={e => {
            e.preventDefault(); const form = e.currentTarget; const data = Object.fromEntries(new FormData(form));
            run(async () => {const doc = await request('documents','POST',data); form.reset(); await refresh();
              setMessage('Indexed version ' + doc.version + ' as a draft (' + doc.chunks + ' chunks). Open Review to publish it.');});
          }}>
            <label>Document slug <input name="slug" required pattern="[a-z0-9][a-z0-9\-]{0,59}" placeholder="backup-policy"/></label>{' '}
            <label>Title <input name="title" required maxLength={120}/></label>{' '}
            <label>Language <select name="locale">{languageOptions}</select></label>
            <label htmlFor="text">Document text</label><textarea id="text" name="text" required minLength={20} maxLength={24000}/>
            <button className="primary" disabled={busy}>Index draft</button>
          </form></>}
        {tab === 'review' && <><h2>Review document versions</h2><p>Only published versions can support an answer.</p>
          {!library.length && <p>No documents yet. Ingest a text document to get started.</p>}
          <div className="sources">{library.map(doc => <article className="source" key={doc.id}>
            <span className="tag">{doc.status} · {doc.locale.toUpperCase()} · v{doc.version}</span><h3>{doc.title}</h3><p>{doc.slug}</p>
            <button disabled={busy} onClick={() => run(async () => setSelected(await request('documents/' + doc.id)))}>Inspect</button>
          </article>)}</div>
          {selected && <div className="answer">
            <h3>{selected.title} · version {selected.version}</h3>
            {selected.chunks.map(chunk => <p key={chunk.ordinal}><strong>Chunk {chunk.ordinal}: </strong>{chunk.text}</p>)}
            {selected.status !== 'archived' && (selected.status === 'draft' ? ['published','archived'] : ['archived']).map(status =>
              <button key={status} disabled={busy} onClick={() => run(async () => {
                await request('documents/' + selected.id,'PATCH',{status}); await refresh();
                setSelected(await request('documents/' + selected.id)); setMessage('Version ' + status + '.');
              })}>{status === 'published' ? 'Publish reviewed version' : 'Archive version'}</button>)}
          </div>}
        </>}
        <p role="status">{busy ? 'Working locally…' : message}</p>
      </section>
      <aside>Review generated answers against their sources. Use public or cleared documents only.</aside>
    </main>
    <footer className="wrap">© 2026 Alessio Maria D'Amico</footer>
  </>;
}
createRoot(document.getElementById('root')).render(<App />);
