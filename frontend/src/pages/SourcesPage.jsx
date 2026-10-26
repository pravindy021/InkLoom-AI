import { useEffect, useState } from "react";
import { FileCheck2, LibraryBig, Plus, Trash2 } from "lucide-react";
import { api, errorMessage, unwrapList } from "../services/api";
import { EmptyState, ErrorMessage, ErrorState, LoadingState, PageHeader, SuccessMessage } from "../components/common/UI";
import { useAuth } from "../contexts/AuthContext";

const initialForm = { name: "", content: "", guideline_id: "", url: "", source_date: "", expiry_date: "" };
const MAX_SOURCE_SIZE = 10 * 1024 * 1024;

export default function SourcesPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [sources, setSources] = useState([]);
  const [guidelines, setGuidelines] = useState([]);
  const [form, setForm] = useState(initialForm);
  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [sourceResponse, guidelineResponse] = await Promise.all([api.sources(), api.guidelines()]);
      setSources(unwrapList(sourceResponse));
      setGuidelines(unwrapList(guidelineResponse));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const create = async (event) => {
    event.preventDefault();
    setError("");
    setNotice("");
    if ((!form.name.trim() && !file) || (!form.content.trim() && !file)) {
      setError("Add a source name and either reference text or a supported source file.");
      return;
    }
    setSaving(true);
    try {
      if (file) {
        await api.uploadSource({ ...form, file });
      } else {
        await api.createSource({
          ...form,
          guideline_id: form.guideline_id ? Number(form.guideline_id) : null,
          source_date: form.source_date || null,
          expiry_date: form.expiry_date || null,
        });
      }
      setNotice("Approved evidence source saved.");
      setForm(initialForm);
      setFile(null);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (source) => {
    if (!window.confirm(`Delete the evidence source “${source.name}”?`)) return;
    setError("");
    try {
      await api.deleteSource(source.id);
      setSources((current) => current.filter((item) => item.id !== source.id));
      setNotice("Evidence source deleted.");
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  const chooseFile = (selected) => {
    setFileError("");
    if (!selected) {
      setFile(null);
      return;
    }
    if (!/\.(txt|md|pdf)$/i.test(selected.name)) {
      setFileError("Choose a UTF-8 TXT, Markdown, or PDF file.");
      setFile(null);
      return;
    }
    if (selected.size > MAX_SOURCE_SIZE) {
      setFileError("Source files must be 10 MB or smaller.");
      setFile(null);
      return;
    }
    setFile(selected);
  };

  return <>
    <PageHeader eyebrow="Evidence library" title="Approved sources" description="Add trusted source text for freshness-aware analysis. Retrieved excerpts are candidate evidence only; the analysis never marks claims as verified." action={<span className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-600"><FileCheck2 size={14} />Source-backed review</span>} />
    {notice && <div className="mb-4"><SuccessMessage>{notice}</SuccessMessage></div>}
    {error && <div className="mb-4"><ErrorMessage>{error}</ErrorMessage></div>}
    <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section className="card">
        <div className="border-b border-slate-100 px-5 py-4"><h2 className="font-semibold text-ink-900">Reference library</h2><p className="mt-1 text-xs text-slate-500">Text is stored in the project database and used only for local candidate retrieval.</p></div>
        {loading ? <LoadingState /> : error && !sources.length ? <div className="p-4"><ErrorState message={error} onRetry={load} /></div> : sources.length ? <div className="divide-y divide-slate-100">{sources.map((source) => <article key={source.id} className="flex items-start gap-3 p-5"><div className="rounded-lg bg-ink-50 p-2.5 text-ink-700"><LibraryBig size={18} /></div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold text-slate-800">{source.name}</h3>{source.expiry_date && <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${new Date(`${source.expiry_date}T23:59:59`) < new Date() ? "bg-rose-50 text-rose-700" : "bg-emerald-50 text-emerald-700"}`}>{new Date(`${source.expiry_date}T23:59:59`) < new Date() ? "Expired" : "Expires"} {source.expiry_date}</span>}</div><p className="mt-1 text-xs text-slate-500">{source.guideline_id ? `Linked guideline #${source.guideline_id}` : "Available to all guidelines"}{source.source_date ? ` · Source date ${source.source_date}` : ""}{source.url ? ` · ${source.url}` : ""}</p><p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-600">{source.content}</p></div>{isAdmin && <button type="button" aria-label={`Delete ${source.name}`} className="rounded-lg p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-600" onClick={() => remove(source)}><Trash2 size={16} /></button>}</article>)}</div> : <EmptyState icon={LibraryBig} title="No approved sources yet" description="Add reference text such as an approved product fact sheet, policy excerpt, or disclosure." />}
      </section>
      {isAdmin ? <form className="card p-5" onSubmit={create}>
        <div className="mb-2 flex items-center gap-2"><Plus size={18} className="text-ink-600" /><h2 className="font-semibold text-ink-900">Add approved source</h2></div>
        <p className="mb-5 text-xs leading-5 text-slate-500">Only add material your organization has approved for this purpose. Do not paste secrets or sensitive personal data. Uploads are parsed in memory; extracted text is stored in the database.</p>
        <label className="mb-1.5 block text-sm font-medium" htmlFor="source-name">Source name</label><input id="source-name" className="field mb-4" maxLength={160} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Approved product fact sheet" />
        <label className="mb-1.5 block text-sm font-medium" htmlFor="source-file">Upload reference file <span className="font-normal text-slate-400">(optional)</span></label><input id="source-file" type="file" accept=".txt,.md,.pdf,text/plain,text/markdown,application/pdf" className="field mb-2" onChange={(e) => chooseFile(e.target.files?.[0])} /><p className="mb-4 text-xs text-slate-400">{file ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB` : "UTF-8 TXT, Markdown or PDF · up to 10 MB · 100 PDF pages maximum. DOCX and Figma files are not supported."}</p>{fileError && <p role="alert" className="mb-3 text-sm text-rose-700">{fileError}</p>}
        {!file && <><label className="mb-1.5 block text-sm font-medium" htmlFor="source-content">Or paste approved reference text</label><textarea id="source-content" className="field mb-4 resize-y" rows={7} maxLength={200000} value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} placeholder="Paste the approved statement or evidence excerpt…" /></>}
        <label className="mb-1.5 block text-sm font-medium" htmlFor="source-guideline">Related guideline</label><select id="source-guideline" className="field mb-4" value={form.guideline_id} onChange={(e) => setForm({ ...form, guideline_id: e.target.value })}><option value="">Available to all guidelines</option>{guidelines.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
        <label className="mb-1.5 block text-sm font-medium" htmlFor="source-url">Reference URL <span className="font-normal text-slate-400">(optional)</span></label><input id="source-url" type="url" className="field mb-4" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://…" />
        <div className="grid grid-cols-2 gap-3"><div><label className="mb-1.5 block text-sm font-medium" htmlFor="source-date">Source date</label><input id="source-date" type="date" className="field" value={form.source_date} onChange={(e) => setForm({ ...form, source_date: e.target.value })} /></div><div><label className="mb-1.5 block text-sm font-medium" htmlFor="source-expiry">Expiry date</label><input id="source-expiry" type="date" className="field" value={form.expiry_date} onChange={(e) => setForm({ ...form, expiry_date: e.target.value })} /></div></div>
        {file && <button type="button" className="btn-secondary mt-2 w-full" onClick={() => setFile(null)}>Remove selected file</button>}<button className="btn-primary mt-5 w-full" type="submit" disabled={saving || Boolean(fileError)}>{saving ? "Saving…" : "Save source"}</button>
      </form> : <section className="card p-5"><h2 className="font-semibold text-ink-900">Source management</h2><p className="mt-2 text-sm leading-6 text-slate-500">Only workspace administrators can add, upload, or delete approved evidence sources.</p></section>}
    </div>
  </>;
}
