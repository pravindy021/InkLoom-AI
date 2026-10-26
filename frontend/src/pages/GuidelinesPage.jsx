import { useEffect, useState } from "react";
import { BookOpenText, Plus, Trash2 } from "lucide-react";
import { api, errorMessage, unwrapList } from "../services/api";
import { Badge, EmptyState, ErrorMessage, ErrorState, LoadingState, PageHeader, SuccessMessage } from "../components/common/UI";
import { useAuth } from "../contexts/AuthContext";

export default function GuidelinesPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ name: "", category: "Tone of voice", severity: "medium", description: "" });
  const load = async () => { setLoading(true); setError(""); try { setItems(unwrapList(await api.guidelines())); } catch (e) { setError(errorMessage(e)); } finally { setLoading(false); } };
  useEffect(() => { load(); }, []);
  const create = async (event) => {
    event.preventDefault(); setFormError(""); setNotice("");
    if (!form.name.trim() || !form.description.trim()) { setFormError("Enter both a guideline name and description."); return; }
    setSaving(true);
    try { await api.createGuideline(form); setNotice("Guideline created."); setForm({ name: "", category: "Tone of voice", severity: "medium", description: "" }); await load(); }
    catch (e) { setFormError(errorMessage(e)); }
    finally { setSaving(false); }
  };
  const remove = async (item) => {
    if (!window.confirm(`Delete “${item.name || item.title}”? This cannot be undone.`)) return;
    setError("");
    try { await api.deleteGuideline(item.id); setItems((current) => current.filter((entry) => entry.id !== item.id)); setNotice("Guideline deleted."); }
    catch (e) { setError(errorMessage(e)); }
  };
  return <>
    <PageHeader eyebrow="Brand system" title="Brand guidelines" description="Your standards help reviewers and analysis stay consistent." action={<span className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-600"><span className="h-1.5 w-1.5 rounded-full bg-slate-500" />Guidelines from API</span>} />
    {notice && <div className="mb-4"><SuccessMessage>{notice}</SuccessMessage></div>}
    {error && <div className="mb-4"><ErrorMessage>{error}</ErrorMessage></div>}
    <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <section className="card">
        <div className="border-b border-slate-100 px-5 py-4"><h2 className="font-semibold text-ink-900">Active guidelines</h2><p className="mt-1 text-xs text-slate-500">Only rules returned by the connected API are shown as approved.</p></div>
        {loading ? <LoadingState /> : error && !items.length ? <div className="p-4"><ErrorState message={error} onRetry={load} /></div> : items.length ? <div className="divide-y divide-slate-100">{items.map((item) => <article key={item.id} className="flex items-start gap-4 p-5"><div className="rounded-lg bg-ink-50 p-2.5 text-ink-700"><BookOpenText size={18} /></div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold text-slate-800">{item.name || item.title || "Untitled guideline"}</h3><Badge>{item.status || "status unavailable"}</Badge><Badge tone="severity">{item.severity || "medium"}</Badge></div><p className="mt-1 text-xs font-medium text-ink-600">{item.category || "Uncategorized"}</p><p className="mt-2 text-sm leading-6 text-slate-500">{item.description || item.rule || "No description provided."}</p></div>{isAdmin && <button aria-label={`Delete ${item.name || item.title}`} onClick={() => remove(item)} className="rounded-lg p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-600"><Trash2 size={16} /></button>}</article>)}</div> : <EmptyState title="No guidelines found" description="Create your first guideline to give reviews a clear standard." /> }
      </section>
      {isAdmin ? <form className="card p-5" onSubmit={create}>
        <div className="mb-4 flex items-center gap-2"><Plus size={18} className="text-ink-600" /><h2 className="font-semibold text-ink-900">Add a guideline</h2></div>
        <p className="mb-5 text-xs leading-5 text-slate-500">Create rules through the connected API. Edit support is not part of the current API contract.</p>
        <label className="mb-1.5 block text-sm font-medium" htmlFor="rule-name">Guideline name</label><input id="rule-name" className="field mb-4" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Plain language" />
        <label className="mb-1.5 block text-sm font-medium" htmlFor="rule-category">Category</label><select id="rule-category" className="field mb-4" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>{["Tone of voice", "Terminology", "Claims", "Accessibility", "Visual identity", "Other"].map((value) => <option key={value}>{value}</option>)}</select>
        <label className="mb-1.5 block text-sm font-medium" htmlFor="rule-severity">Severity</label><select id="rule-severity" className="field mb-4" value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>{["low", "medium", "high"].map((value) => <option key={value}>{value}</option>)}</select>
        <label className="mb-1.5 block text-sm font-medium" htmlFor="rule-description">Rule description</label><textarea id="rule-description" rows={4} className="field mb-4 resize-y" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Describe what writers and reviewers should follow." />
        {formError && <div className="mb-3"><ErrorMessage>{formError}</ErrorMessage></div>}
        <button className="btn-primary w-full" type="submit" disabled={saving}>{saving ? "Saving…" : "Create guideline"}</button>
      </form> : <section className="card p-5"><h2 className="font-semibold text-ink-900">Guideline management</h2><p className="mt-2 text-sm leading-6 text-slate-500">Only workspace administrators can create or delete guidelines.</p></section>}
    </div>
  </>;
}
