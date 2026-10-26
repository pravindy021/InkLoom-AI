import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, Search } from "lucide-react";
import { Link } from "react-router-dom";
import { api, errorMessage, unwrapList } from "../services/api";
import { Badge, EmptyState, ErrorState, LoadingState, PageHeader } from "../components/common/UI";

export default function ReviewQueuePage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const load = async () => { setLoading(true); setError(""); try { setItems(unwrapList(await api.reviews())); } catch (e) { setError(errorMessage(e)); } finally { setLoading(false); } };
  useEffect(() => { load(); }, []);
  const visible = useMemo(() => items.filter((item) => (filter === "all" || item.status === filter) && (item.title || item.name || "").toLowerCase().includes(query.toLowerCase())), [items, filter, query]);
  return <>
    <PageHeader eyebrow="Human review" title="Review queue" description="Make the final call on content. AI findings are advisory; each item needs a human decision." />
    <div className="card overflow-hidden">
      <div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <div className="relative w-full sm:max-w-xs"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><input className="field pl-9" aria-label="Search reviews" placeholder="Search by title..." value={query} onChange={(e) => setQuery(e.target.value)} /></div>
        <div className="flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1">{["all", "pending", "in_review", "changes_requested", "approved"].map((value) => <button key={value} onClick={() => setFilter(value)} className={`rounded-md px-2.5 py-1.5 text-xs font-medium capitalize ${filter === value ? "bg-white text-ink-700 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}>{value.replaceAll("_", " ")}</button>)}</div>
      </div>
      {loading ? <LoadingState label="Loading review queue..." /> : error ? <div className="p-4"><ErrorState message={error} onRetry={load} /></div> : visible.length ? <div className="overflow-x-auto"><table className="w-full min-w-[680px] text-left"><thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-400"><tr><th className="px-5 py-3">Content</th><th className="px-5 py-3">Submitted</th><th className="px-5 py-3">Issues</th><th className="px-5 py-3">Reviewer</th><th className="px-5 py-3">Status</th><th className="px-5 py-3"><span className="sr-only">Open review</span></th></tr></thead><tbody className="divide-y divide-slate-100">{visible.map((item) => <tr key={item.id} className="hover:bg-slate-50/70"><td className="px-5 py-4"><p className="font-semibold text-slate-800">{item.title || item.name || "Untitled content"}</p><p className="mt-1 text-xs text-slate-400">{item.content_type || item.type || "Content"}</p></td><td className="px-5 py-4 text-sm text-slate-500">{item.submitted_at ? new Date(item.submitted_at).toLocaleDateString() : "—"}</td><td className="px-5 py-4 text-sm text-slate-600">{item.issue_count ?? item.findings?.length ?? "—"}</td><td className="px-5 py-4 text-sm text-slate-500">{item.reviewer || item.reviewer_name || "Unassigned"}</td><td className="px-5 py-4"><Badge tone="status">{item.status || "pending"}</Badge></td><td className="px-5 py-4"><Link aria-label={`Open ${item.title || "review"}`} to={`/reviews/${item.id}`} className="inline-flex rounded-lg p-2 text-slate-400 hover:bg-ink-50 hover:text-ink-700"><ArrowUpRight size={17} /></Link></td></tr>)}</tbody></table></div> : <EmptyState title="No reviews match this view" description="Try another status filter or submit new content for review." />}
    </div>
  </>;
}
