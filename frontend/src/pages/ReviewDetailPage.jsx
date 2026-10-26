import { useEffect, useRef, useState } from "react";
import { ArrowLeft, CheckCircle2, History, MessageSquare, Radio, Send } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { API_BASE_URL, api, errorMessage, unwrapList } from "../services/api";
import { Badge, EmptyState, ErrorMessage, ErrorState, LoadingState, PageHeader, SuccessMessage } from "../components/common/UI";

export default function ReviewDetailPage() {
  const { reviewId } = useParams();
  const [item, setItem] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [comment, setComment] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [showReviewerGuidance] = useState(() => window.localStorage.getItem("inkloom-review-options") !== "false");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [actionError, setActionError] = useState("");
  const [activity, setActivity] = useState([]);
  const [activityError, setActivityError] = useState("");
  const [liveState, setLiveState] = useState("connecting");
  const socketRef = useRef(null);
  const draftTimerRef = useRef(null);
  const load = async () => { setLoading(true); setError(""); try { const response = await api.review(reviewId); const data = response?.data || response; if (!data) throw new Error("Review was not found."); setItem(data); setDraftContent(data.content || data.text || ""); } catch (e) { setError(errorMessage(e)); } finally { setLoading(false); } };
  useEffect(() => { load(); }, [reviewId]);
  useEffect(() => {
    let active = true;
    api.reviewActivity(reviewId).then((response) => {
      if (active) {
        setActivity(unwrapList(response));
        setActivityError("");
      }
    }).catch((err) => {
      if (active) setActivityError(errorMessage(err));
    });
    const socketUrl = `${API_BASE_URL.replace(/^http/, "ws")}/api/reviews/${encodeURIComponent(reviewId)}/collaboration`;
    const socket = new WebSocket(socketUrl);
    socketRef.current = socket;
    socket.onopen = () => setLiveState("connected");
    socket.onclose = () => setLiveState("disconnected");
    socket.onerror = () => setLiveState("unavailable");
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === "comment_created" && message.payload) {
          setItem((current) => current ? { ...current, comments: [...(current.comments || []), message.payload] } : current);
        } else if (message.type === "status_changed" && message.payload?.status) {
          setItem((current) => current ? { ...current, status: message.payload.status, reviewer: message.payload.reviewer || current.reviewer } : current);
        } else if (message.type === "revision_created" && message.payload) {
          setItem((current) => current ? { ...current, content: message.payload.content || current.content, revisions: [...(current.revisions || []), message.payload] } : current);
          if (message.payload.content) setDraftContent(message.payload.content);
        } else if (message.type === "draft_changed" && typeof message.payload?.content === "string") {
          setDraftContent(message.payload.content);
          setLiveState("connected");
        } else if (message.type === "presence" || message.type === "typing") {
          setLiveState("connected");
        }
        if (["comment_created", "status_changed", "revision_created"].includes(message.type)) refreshActivity();
      } catch {
        setLiveState("unavailable");
      }
    };
    return () => {
      active = false;
      if (socketRef.current === socket) socketRef.current = null;
      window.clearTimeout(draftTimerRef.current);
      socket.close();
    };
  }, [reviewId]);
  const refreshActivity = () => {
    api.reviewActivity(reviewId).then((response) => {
      setActivity(unwrapList(response));
      setActivityError("");
    }).catch((err) => setActivityError(errorMessage(err)));
  };
  const updateDraft = (value) => {
    setDraftContent(value);
    window.clearTimeout(draftTimerRef.current);
    draftTimerRef.current = window.setTimeout(() => {
      if (socketRef.current?.readyState === WebSocket.OPEN) {
        socketRef.current.send(JSON.stringify({ type: "draft_changed", content: value, user: item?.reviewer || "Anonymous reviewer" }));
      }
    }, 180);
  };
  const updateStatus = async (status) => {
    if (status === "approved" && !window.confirm("Approve this content for publication? Approval is a human decision and cannot be undone here.")) return;
    if (status === "changes_requested" && !window.confirm("Request changes for this content?")) return;
    setBusy(true); setActionError(""); setNotice("");
    try { const response = await api.updateStatus(reviewId, status); setItem((current) => ({ ...current, ...(response?.data || response || {}), status })); setNotice(status === "approved" ? "Content marked approved." : "Changes requested."); }
    catch (e) { setActionError(errorMessage(e)); }
    finally { setBusy(false); }
  };
  const addComment = async (event) => { event.preventDefault(); if (!comment.trim()) return; setBusy(true); setActionError(""); try { await api.addComment(reviewId, comment.trim()); setComment(""); setNotice("Comment added."); await load(); } catch (e) { setActionError(errorMessage(e)); } finally { setBusy(false); } };
  const saveRevision = async (event) => {
    event.preventDefault();
    if (!draftContent.trim()) return;
    setBusy(true); setActionError(""); setNotice("");
    try {
      await api.addRevision(reviewId, { content: draftContent.trim() });
      setNotice("Revision saved.");
      await load();
    } catch (e) { setActionError(errorMessage(e)); }
    finally { setBusy(false); }
  };
  const findings = unwrapList(item?.findings || item?.issues);
  const comments = unwrapList(item?.comments);
  const revisions = unwrapList(item?.revisions);
  if (loading) return <LoadingState label="Loading review..." />;
  if (error || !item) return <><Link to="/reviews" className="mb-5 inline-flex items-center gap-2 text-sm text-slate-500 hover:text-ink-700"><ArrowLeft size={16} />Review queue</Link><ErrorState message={error || "Review not found."} onRetry={load} /></>;
  return <>
    <Link to="/reviews" className="mb-5 inline-flex items-center gap-2 text-sm text-slate-500 hover:text-ink-700"><ArrowLeft size={16} />Review queue</Link>
    <PageHeader eyebrow={item.content_type || item.type || "Content review"} title={item.title || "Untitled review"} description={`Submitted ${item.submitted_at ? new Date(item.submitted_at).toLocaleString() : "date unavailable"} · ${item.reviewer || item.reviewer_name || "No reviewer assigned"}`} action={<Badge tone="status">{item.status || "pending"}</Badge>} />
    {showReviewerGuidance && <div className="mb-5 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900"><strong>Human decision required.</strong> AI findings are advisory and do not approve or reject content. Review the draft and evidence before taking action.</div>}
    {notice && <div className="mb-4"><SuccessMessage>{notice}</SuccessMessage></div>}{actionError && <div className="mb-4"><ErrorMessage>{actionError}</ErrorMessage></div>}
    <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(350px,.8fr)]">
      <div className="space-y-5">
        <section className="card p-5"><div className="flex items-center justify-between gap-3"><h2 className="font-semibold text-ink-900">Collaborative editing canvas</h2><span className={`text-xs ${liveState === "connected" ? "text-emerald-700" : "text-slate-400"}`}>{liveState === "connected" ? "Draft changes sync live" : "Live sync unavailable"}</span></div><p className="mt-1 text-xs leading-5 text-slate-500">Changes are shared with currently connected reviewers. Save a revision to persist edits.</p><label className="sr-only" htmlFor="shared-review-draft">Collaboratively edit content</label><textarea id="shared-review-draft" className="field mt-4 resize-y leading-7" rows={12} value={draftContent} onChange={(event) => updateDraft(event.target.value)} /><div className="mt-3 flex items-center justify-between gap-3"><span className="text-xs text-slate-400">{draftContent.length.toLocaleString()} characters · not saved until you add a revision</span><button className="btn-secondary shrink-0" type="button" onClick={saveRevision} disabled={busy || !draftContent.trim()}>Save revision</button></div></section>
        <section className="card"><div className="flex items-center justify-between border-b border-slate-100 px-5 py-4"><div><h2 className="font-semibold text-ink-900">Flagged findings</h2><p className="mt-1 text-xs text-slate-500">{findings.length} advisory items</p></div></div>{findings.length ? <div className="divide-y divide-slate-100">{findings.map((finding, index) => <article className="p-5" key={finding.id || index}><div className="flex flex-wrap items-center gap-2"><Badge>{finding.category || finding.type || "Finding"}</Badge><Badge tone="severity">{finding.severity || "medium"}</Badge><Badge tone="status">{finding.status || "open"}</Badge></div>{finding.matched_text && <p className="mt-3 rounded bg-rose-50 px-3 py-2 text-sm text-rose-800">“{finding.matched_text}”</p>}<p className="mt-3 text-sm leading-6 text-slate-600">{finding.explanation || finding.description || finding.message}</p>{finding.suggestion && <p className="mt-2 text-sm text-emerald-800"><strong>Suggestion:</strong> {finding.suggestion}</p>}<p className="mt-2 text-xs text-slate-400">Guideline: {finding.guideline || finding.source || "Not provided"}</p></article>)}</div> : <EmptyState title="No findings supplied" description="This review has no analysis findings to display." />}</section>
      </div>
      <div className="space-y-5">
        <section className="card p-5"><h2 className="font-semibold text-ink-900">Reviewer decision</h2><p className="mt-1 text-xs leading-5 text-slate-500">Use your judgment. These actions record review status; they are not access-control permissions.</p><div className="mt-4 grid gap-2"><button className="btn-primary w-full" onClick={() => updateStatus("approved")} disabled={busy || item.status === "approved"}><CheckCircle2 size={16} />Approve content</button><button className="btn-secondary w-full" onClick={() => updateStatus("changes_requested")} disabled={busy || item.status === "changes_requested"}>Request changes</button><button className="btn-secondary w-full" onClick={() => updateStatus("in_review")} disabled={busy || item.status === "in_review"}>Mark in review</button></div></section>
        <section className="card p-5"><div className="flex items-center justify-between gap-2"><div className="flex items-center gap-2"><MessageSquare size={17} className="text-ink-600" /><h2 className="font-semibold text-ink-900">Review comments</h2></div><span className={`inline-flex items-center gap-1.5 text-xs ${liveState === "connected" ? "text-emerald-700" : "text-slate-400"}`}><Radio size={13} />{liveState === "connected" ? "Live" : liveState === "connecting" ? "Connecting…" : "Offline"}</span></div><form className="mt-4" onSubmit={addComment}><label className="sr-only" htmlFor="review-comment">Add a comment</label><textarea id="review-comment" className="field resize-y" rows={3} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Share context or feedback..." /><button className="btn-secondary mt-2 w-full" type="submit" disabled={busy || !comment.trim()}><Send size={15} />Add comment</button></form><div className="mt-4 space-y-3">{comments.length ? comments.map((entry, index) => <div key={entry.id || index} className="rounded-lg bg-slate-50 p-3"><div className="flex justify-between gap-2 text-xs"><span className="font-semibold text-slate-700">{entry.author || entry.user || "Reviewer"}</span><span className="text-slate-400">{entry.created_at ? new Date(entry.created_at).toLocaleString() : ""}</span></div><p className="mt-2 whitespace-pre-wrap text-sm leading-5 text-slate-600">{entry.comment || entry.text}</p></div>) : <p className="text-xs text-slate-400">No comments yet.</p>}</div></section>
        <section className="card p-5"><div className="flex items-center gap-2"><History size={17} className="text-ink-600" /><h2 className="font-semibold text-ink-900">Revision history</h2></div>
          {revisions.length ? <div className="mt-4 space-y-3">{revisions.map((revision, index) => <div key={revision.id || index} className="border-l-2 border-ink-200 pl-3"><p className="text-sm font-medium text-slate-700">{revision.title || revision.summary || `Revision ${revisions.length - index}`}</p><p className="mt-1 text-xs text-slate-400">{revision.created_at ? new Date(revision.created_at).toLocaleString() : "Date unavailable"}</p></div>)}</div> : <p className="mt-4 text-xs text-slate-400">No revisions yet.</p>}
        </section>
        <section className="card p-5"><div className="flex items-center gap-2"><History size={17} className="text-ink-600" /><h2 className="font-semibold text-ink-900">Activity & audit trail</h2></div><p className="mt-1 text-xs leading-5 text-slate-500">Append-only application activity log; not a cryptographic or tamper-proof audit system.</p>{activityError ? <p role="alert" className="mt-3 text-sm text-rose-700">{activityError}</p> : activity.length ? <div className="mt-4 space-y-3">{activity.map((entry) => <div key={entry.id} className="border-l-2 border-ink-200 pl-3"><p className="text-sm font-medium capitalize text-slate-700">{entry.action.replaceAll("_", " ")}</p><p className="mt-1 text-xs text-slate-400">{entry.actor || "System"} · {entry.created_at ? new Date(entry.created_at).toLocaleString() : ""}{entry.details?.status ? ` · ${entry.details.status}` : ""}{entry.details?.issue_count != null ? ` · ${entry.details.issue_count} finding(s)` : ""}</p></div>)}</div> : <p className="mt-4 text-xs text-slate-400">No activity has been recorded yet.</p>}</section>
      </div>
    </div>
  </>;
}
