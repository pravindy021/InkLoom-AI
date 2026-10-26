import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, Clipboard, FileImage, FilePlus2, LoaderCircle, Sparkles, X } from "lucide-react";
import { api, errorMessage, MOCK_MODE, unwrapList } from "../services/api";
import { Badge, EmptyState, ErrorMessage, PageHeader, SuccessMessage } from "../components/common/UI";

const MAX_FILE_SIZE = 10 * 1024 * 1024;
const ACCEPTED = ["image/png", "image/jpeg", "image/webp"];
const field = (finding, ...keys) => keys.map((key) => finding?.[key]).find((value) => value !== undefined && value !== null);

export default function ContentReviewPage() {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [contentType, setContentType] = useState("Campaign");
  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [result, setResult] = useState(null);
  const [category, setCategory] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [guidelines, setGuidelines] = useState([]);
  const [selectedGuidelines, setSelectedGuidelines] = useState([]);
  const [guidelineError, setGuidelineError] = useState("");
  const [sources, setSources] = useState([]);
  const [selectedSources, setSelectedSources] = useState([]);
  const [altText, setAltText] = useState("");
  const [externalCheck, setExternalCheck] = useState({ configured: false, provider: null, domains: [], llm: false, embeddings: false });
  const [useExternalCheck, setUseExternalCheck] = useState(false);
  const [copied, setCopied] = useState("");
  const navigate = useNavigate();
  const fileInput = useRef(null);
  const findings = unwrapList(result?.findings || result?.issues);
  const filtered = useMemo(() => findings.filter((item) => (category === "all" || String(field(item, "category", "type") || "").toLowerCase() === category) && (severity === "all" || String(item.severity || "").toLowerCase() === severity)), [findings, category, severity]);
  const categories = [...new Set(findings.map((item) => String(field(item, "category", "type") || "").toLowerCase()).filter(Boolean))];
  useEffect(() => {
    Promise.all([api.guidelines(), api.sources()])
      .then(([guidelineResponse, sourceResponse]) => {
        setGuidelines(unwrapList(guidelineResponse));
        setSources(unwrapList(sourceResponse));
      })
      .catch((err) => setGuidelineError(errorMessage(err)));
    api.health()
      .then((health) => setExternalCheck({
        configured: Boolean(health?.external_fact_check_configured),
        provider: health?.external_fact_check_provider || null,
        domains: health?.trusted_source_domains || [],
        llm: health?.analysis_mode === "rules+configured_llm",
        embeddings: Boolean(health?.embedding_model_configured),
      }))
      .catch(() => setExternalCheck({ configured: false, provider: null, domains: [], llm: false, embeddings: false }));
  }, []);

  const chooseFile = (selected) => {
    setFileError("");
    if (!selected) return;
    if (!ACCEPTED.includes(selected.type)) { setFileError("Choose a PNG, JPG or WEBP image."); return; }
    if (selected.size > MAX_FILE_SIZE) { setFileError("Image must be 10 MB or smaller."); return; }
    setFile(selected);
  };
  const submit = async (event) => {
    event.preventDefault(); setError(""); setSuccess("");
    if (!content.trim()) { setError("Add content before running an analysis."); return; }
    setLoading(true); setResult(null);
    try {
      const response = await api.analyze({ title: title.trim() || "Untitled content", content: content.trim(), content_type: contentType, file, guideline_ids: selectedGuidelines, source_ids: selectedSources, alt_text: altText, allow_external_verification: useExternalCheck });
      setResult(response?.data || response);
      const externalStatus = response?.external_verification?.status;
      const externalNotice = useExternalCheck
        ? externalStatus === "provider_error"
          ? " External lookup failed safely; claims remain unverified."
          : externalStatus === "completed"
            ? " External results are candidate evidence, not proof."
            : externalStatus === "partial"
              ? " Some claims were not sent for external lookup; those remain unverified unless local evidence matched."
            : " External fact lookup is not configured, so it was not used."
        : "";
      setSuccess(MOCK_MODE ? "Mock analysis complete. These illustrative findings are not AI-generated." : `${response?.analysis_engine === "rules+configured_llm" ? "Rules and configured LLM analysis" : "Local rules analysis"} completed. Review findings before deciding what to change.${externalNotice}`);
    } catch (err) { setError(errorMessage(err)); }
    finally { setLoading(false); }
  };
  const applySuggestion = (finding) => {
    const matched = field(finding, "matched_text", "matchedText", "text");
    const suggestion = field(finding, "suggestion", "suggested_correction", "correction");
    if (!matched || !suggestion) return;
    const index = content.indexOf(matched);
    if (index < 0) { setError(`Couldn't find “${matched}” in the current text. Copy the suggestion and edit manually.`); return; }
    setContent(`${content.slice(0, index)}${suggestion}${content.slice(index + matched.length)}`);
    setSuccess("Suggestion applied to the matching phrase. Your full text remains editable.");
  };
  const copySuggestion = async (finding) => {
    const suggestion = field(finding, "suggestion", "suggested_correction", "correction");
    try { await navigator.clipboard.writeText(String(suggestion || "")); setCopied(finding.id); window.setTimeout(() => setCopied(""), 1500); }
    catch { setError("Clipboard access is unavailable. Select and copy the suggested text instead."); }
  };
  const reviewId = result?.id ?? result?.review_id;
  return <>
    <PageHeader eyebrow="Content workspace" title="Review content" description="Check text and supported imagery against your brand standards. Every recommendation is advisory." />
    <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.12fr)_minmax(390px,.88fr)]">
      <form onSubmit={submit} className="card p-5 sm:p-6">
        <div className="mb-5 flex items-center gap-3"><div className="rounded-lg bg-ink-50 p-2 text-ink-700"><FilePlus2 size={18} /></div><div><h2 className="font-semibold text-ink-900">Content to review</h2><p className="mt-1 text-xs text-slate-500">Add the draft you want checked</p></div></div>
        <label className="mb-1.5 block text-sm font-medium text-slate-700" htmlFor="content-title">Content title <span className="text-slate-400">(optional)</span></label>
        <input id="content-title" value={title} onChange={(e) => setTitle(e.target.value)} className="field mb-4" placeholder="e.g. Spring campaign landing page" />
        <div className="mb-1.5 flex items-center justify-between"><label htmlFor="content-type" className="text-sm font-medium text-slate-700">Content type</label><span className="text-xs text-slate-400">{content.length.toLocaleString()} characters</span></div>
        <select id="content-type" value={contentType} onChange={(e) => setContentType(e.target.value)} className="field mb-4"><option>Campaign</option><option>Social post</option><option>Email</option><option>Product page</option><option>Blog article</option><option>Other</option></select>
        <div className="mb-4">
          <p className="mb-2 text-sm font-medium text-slate-700">Guidelines <span className="font-normal text-slate-400">(optional)</span></p>
          {guidelines.length ? <div className="max-h-36 space-y-2 overflow-y-auto rounded-lg border border-slate-200 p-3">{guidelines.map((guideline) => <label key={guideline.id} className="flex cursor-pointer items-start gap-2 text-sm text-slate-600"><input type="checkbox" className="mt-1 accent-ink-700" checked={selectedGuidelines.includes(guideline.id)} onChange={(event) => setSelectedGuidelines((current) => event.target.checked ? [...current, guideline.id] : current.filter((id) => id !== guideline.id))} /><span>{guideline.name || guideline.title || "Guideline"}<span className="ml-2 text-xs text-slate-400">{guideline.category || ""}</span></span></label>)}</div> : <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">{guidelineError ? `Guidelines unavailable: ${guidelineError}` : "No guidelines returned by the API."}</p>}
        </div>
        {sources.length > 0 && <div className="mb-4">
          <p className="mb-2 text-sm font-medium text-slate-700">Evidence sources <span className="font-normal text-slate-400">(optional)</span></p>
          <div className="max-h-36 space-y-2 overflow-y-auto rounded-lg border border-slate-200 p-3">{sources.map((source) => <label key={source.id} className="flex cursor-pointer items-start gap-2 text-sm text-slate-600"><input type="checkbox" className="mt-1 accent-ink-700" checked={selectedSources.includes(source.id)} onChange={(event) => setSelectedSources((current) => event.target.checked ? [...current, source.id] : current.filter((id) => id !== source.id))} /><span>{source.name}<span className="ml-2 text-xs text-slate-400">{source.expiry_date ? `expires ${source.expiry_date}` : "no expiry date"}</span></span></label>)}</div>
          <p className="mt-1.5 text-xs text-slate-400">Retrieved excerpts are candidate evidence for a human to verify, not automatic proof.</p>
        </div>}
        {(externalCheck.llm || externalCheck.embeddings) && <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-950">This workspace has configured remote analysis services: {externalCheck.llm && "the LLM receives submitted text and guideline context"}{externalCheck.llm && externalCheck.embeddings && "; "}{externalCheck.embeddings && "the embedding provider receives claim excerpts and selected approved-source chunks"}. Review provider data-handling terms and do not submit confidential material unless your organization permits it.</p>}
        {externalCheck.configured ? <label className="mb-4 flex cursor-pointer items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
          <input className="mt-1 h-4 w-4 accent-ink-700" type="checkbox" checked={useExternalCheck} onChange={(event) => setUseExternalCheck(event.target.checked)} />
          <span><span className="font-semibold">Check trusted external sources with {externalCheck.provider === "brave" ? "Brave Search" : externalCheck.provider}</span><span className="mt-1 block text-xs leading-5">Only detected claim excerpts (not the full draft or image) are sent to this provider. Claims may still be confidential; opt in only when permitted. Results are limited to {externalCheck.domains.join(", ")} and remain advisory.</span></span>
        </label> : <p className="mb-4 rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-500">External fact checking is not configured. This analysis uses only local approved sources; no external fact-checking service will receive content.</p>}
        <label htmlFor="content-text" className="mb-1.5 block text-sm font-medium text-slate-700">Draft content</label>
        <textarea id="content-text" value={content} onChange={(e) => setContent(e.target.value)} rows={12} className="field resize-y leading-6" placeholder="Paste or write your content here..." />
        <div className="mt-5">
          <div className="mb-2 text-sm font-medium text-slate-700">Visual asset <span className="font-normal text-slate-400">(optional)</span></div>
          <input ref={fileInput} type="file" accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" className="sr-only" onChange={(e) => { chooseFile(e.target.files?.[0]); e.target.value = ""; }} aria-label="Upload image" />
          {file ? <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3"><FileImage size={18} className="text-ink-600" /><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium text-slate-700">{file.name}</p><p className="text-xs text-slate-400">{(file.size / 1024 / 1024).toFixed(2)} MB · Ready to submit</p></div><button type="button" className="rounded p-1.5 text-slate-400 hover:bg-white hover:text-rose-600" aria-label="Remove image" onClick={() => setFile(null)}><X size={17} /></button></div> : <button type="button" onClick={() => fileInput.current?.click()} className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 px-4 py-4 text-sm text-slate-500 hover:border-ink-400 hover:bg-ink-50/40"><FileImage size={17} />Upload an image<span className="text-xs text-slate-400">PNG, JPG, WEBP · up to 10 MB</span></button>}
          {file && <div className="mt-3"><label className="mb-1.5 block text-sm font-medium text-slate-700" htmlFor="asset-alt-text">Image alternative text <span className="font-normal text-slate-400">(optional)</span></label><input id="asset-alt-text" className="field" maxLength={1000} value={altText} onChange={(e) => setAltText(e.target.value)} placeholder="Describe the image’s purpose for screen-reader users" /></div>}
          {fileError && <p className="mt-2 text-sm text-rose-700">{fileError}</p>}
          <p className="mt-2 text-xs leading-5 text-slate-400">Images are sent only with this analysis request. Document and design-file formats are not supported.</p>
        </div>
        {error && <div className="mt-4"><ErrorMessage>{error}</ErrorMessage></div>}
        {success && <div className="mt-4"><SuccessMessage>{success}</SuccessMessage></div>}
        <button type="submit" className="btn-primary mt-5 w-full" disabled={loading || Boolean(fileError)}>{loading ? <><LoaderCircle size={17} className="animate-spin" />Analysing content…</> : <><Sparkles size={17} />Analyse content</>}</button>
        {loading && <p className="mt-3 text-center text-xs text-slate-400" role="status">Waiting for the analysis service. This may take a moment.</p>}
      </form>
      <section className="card min-h-[400px]" aria-live="polite">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4"><div><h2 className="font-semibold text-ink-900">Analysis findings</h2><p className="mt-1 text-xs text-slate-500">Review each recommendation before applying</p></div>{findings.length > 0 && <Badge>{findings.length} findings</Badge>}</div>
        {!result ? <EmptyState icon={Sparkles} title="Your findings will appear here" description="Submit your draft to receive guideline-based feedback. Nothing is approved automatically." /> : <>
          <div className="flex flex-wrap gap-2 border-b border-slate-100 px-5 py-3">
            <select aria-label="Filter by category" className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-600" value={category} onChange={(e) => setCategory(e.target.value)}><option value="all">All categories</option>{categories.map((c) => <option value={c} key={c}>{c}</option>)}</select>
            <select aria-label="Filter by severity" className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-600" value={severity} onChange={(e) => setSeverity(e.target.value)}><option value="all">All severity</option>{["high", "medium", "low", "critical"].map((v) => <option key={v}>{v}</option>)}</select>
          </div>
          {filtered.length ? <div className="space-y-4 p-4">{filtered.map((item, index) => {
            const matched = field(item, "matched_text", "matchedText", "text");
            const suggestion = field(item, "suggestion", "suggested_correction", "correction");
            return <article key={item.id || index} className="rounded-lg border border-slate-200 p-4">
              <div className="flex flex-wrap items-center gap-2"><span className="text-xs font-semibold text-ink-700">{field(item, "category", "type") || "Finding"}</span><Badge tone="severity">{item.severity || "medium"}</Badge><span className="ml-auto"><Badge tone="status">{item.status || "open"}</Badge></span></div>
              <p className="mt-3 text-sm leading-6 text-slate-700">{field(item, "explanation", "description", "message") || "Review this item against the applicable guideline."}</p>
              {item.verification_status && <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3"><div className="flex flex-wrap items-center gap-2"><span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Claim verification</span><Badge tone={item.verification_status === "verified" ? "approved" : item.verification_status === "contradicted" ? "severity" : "status"}>{item.verification_status}</Badge></div>{item.claim && <p className="mt-2 text-xs leading-5 text-slate-700"><strong>Claim assessed: </strong>{item.claim}</p>}<p className="mt-2 text-xs leading-5 text-slate-600">{item.verification_explanation || (item.verification_status === "unverified" ? "Lack of evidence is not proof that this claim is false." : "")}</p>{item.citations?.map((source, sourceIndex) => <div key={`${source.url || source.id || source.name}-${sourceIndex}`} className="mt-2 border-t border-slate-200 pt-2"><p className="text-xs font-medium text-slate-700">{source.name || "Evidence source"}{source.source_type === "external_trusted_source" ? " · external trusted source" : " · approved source"}</p>{source.excerpt && <p className="mt-1 text-xs leading-5 text-slate-600">{source.excerpt}</p>}{source.url && <a className="mt-1 inline-block text-xs font-medium text-ink-700 underline" href={source.url} target="_blank" rel="noreferrer">Open citation</a>}</div>)}</div>}
              {matched && <div className="mt-3 rounded-md bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-800"><span className="font-semibold">Flagged text: </span>“{matched}”</div>}
              {suggestion && <div className="mt-3 rounded-md border border-emerald-100 bg-emerald-50/60 p-3"><p className="text-[11px] font-bold uppercase tracking-wide text-emerald-800">Suggested correction</p><p className="mt-1 text-sm leading-5 text-emerald-900">{suggestion}</p><div className="mt-2 flex flex-wrap gap-2"><button className="btn-secondary !px-2.5 !py-1.5 !text-xs" onClick={() => applySuggestion(item)} type="button"><Check size={13} />Apply to text</button><button className="btn-secondary !px-2.5 !py-1.5 !text-xs" onClick={() => copySuggestion(item)} type="button">{copied === item.id ? <Check size={13} /> : <Clipboard size={13} />}{copied === item.id ? "Copied" : "Copy"}</button></div></div>}
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400"><span>Guideline: {field(item, "guideline", "source", "reference") || "Not supplied"}</span>{field(item, "confidence", "confidence_score") != null && <span>Confidence: {Math.round(Number(field(item, "confidence", "confidence_score")) * (Number(field(item, "confidence", "confidence_score")) <= 1 ? 100 : 1))}%</span>}</div>
            </article>;
          })}</div> : <EmptyState title="No findings match these filters" description="Try a different category or severity." />}
          {result.retrieved_evidence?.length > 0 && <div className="border-t border-slate-100 p-4"><h3 className="text-sm font-semibold text-slate-800">Candidate evidence excerpts</h3><p className="mt-1 text-xs text-slate-500">Approved sources are {result.evidence_retrieval_method === "embedding_cosine" ? "semantically ranked" : "lexically ranked with BM25"}; external results come from the configured search provider. A reviewer must verify every match.</p><div className="mt-3 space-y-3">{result.retrieved_evidence.map((evidence, index) => <article key={`${evidence.source_type || "approved"}-${evidence.id || evidence.url || evidence.name}-${evidence.excerpt}-${index}`} className="rounded-lg border border-slate-200 p-3"><div className="flex flex-wrap items-center gap-2"><span className="text-sm font-semibold text-slate-700">{evidence.name || "Source"}</span><Badge tone="status">{evidence.source_type === "external_trusted_source" ? "External trusted source" : (evidence.freshness || "date unknown").replaceAll("_", " ")}</Badge>{Number.isFinite(evidence.relevance_score) && <span className="text-xs text-slate-400">Match {Math.round(evidence.relevance_score * 100)}%</span>}</div><p className="mt-2 text-sm leading-6 text-slate-600">{evidence.excerpt}</p>{evidence.url && <a className="mt-2 inline-block text-xs font-medium text-ink-700 underline" href={evidence.url} target="_blank" rel="noreferrer">Open source</a>}</article>)}</div></div>}
          {result.image_analysis && <div className="border-t border-slate-100 p-4"><h3 className="text-sm font-semibold text-slate-800">Visual asset checks</h3><p className="mt-1 text-xs text-slate-500">{result.image_analysis.format?.toUpperCase()} · {result.image_analysis.width} × {result.image_analysis.height}px{result.image_analysis.ocr_available ? " · OCR available" : " · OCR unavailable"}</p>{result.image_analysis.layout_metrics && <div className="mt-3 rounded-lg border border-slate-200 p-3"><h4 className="text-xs font-semibold text-slate-700">Layout signals <span className="font-normal text-slate-400">(descriptive heuristics)</span></h4><div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-600"><span className="rounded bg-slate-50 px-2 py-1">{result.image_analysis.layout_metrics.orientation} · {result.image_analysis.layout_metrics.aspect_ratio}:1</span><span className="rounded bg-slate-50 px-2 py-1">Edge density {result.image_analysis.layout_metrics.edge_density_percent}%</span>{result.image_analysis.layout_metrics.has_transparency && <span className="rounded bg-slate-50 px-2 py-1">Transparent canvas · {result.image_analysis.layout_metrics.transparent_bounds?.content_occupancy_percent ?? "—"}% occupied</span>}{result.image_analysis.layout_metrics.small_for_large_display && <span className="rounded bg-amber-50 px-2 py-1 text-amber-800">Under 500px max dimension (inspect for intended use)</span>}</div><p className="mt-2 text-[11px] leading-5 text-slate-400">{result.image_analysis.layout_metrics.method}</p></div>}{result.image_analysis.brand_asset_similarity?.configured && <div className="mt-3 rounded-lg border border-slate-200 p-3"><h4 className="text-xs font-semibold text-slate-700">Configured asset references <span className="font-normal text-slate-400">(coarse image-hash similarity)</span></h4><div className="mt-2 space-y-1">{result.image_analysis.brand_asset_similarity.references.map((reference) => <p key={reference.name} className="flex justify-between gap-3 text-xs text-slate-600"><span className="truncate">{reference.name}</span><span className="shrink-0">{reference.similarity_percent}% similar</span></p>)}</div>{result.image_analysis.brand_asset_similarity.potential_mismatch && <p className="mt-2 text-xs leading-5 text-amber-800">This asset may be a different variant; confirm it against the approved asset library.</p>}</div>}{result.image_analysis.extracted_text && <div className="mt-3 rounded-md bg-slate-50 p-3"><p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Text extracted from image</p><p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{result.image_analysis.extracted_text}</p></div>}{result.image_analysis.dominant_colors?.length > 0 && <div className="mt-3"><p className="mb-2 text-xs font-medium text-slate-500">Dominant image colours</p><div className="flex flex-wrap gap-2">{result.image_analysis.dominant_colors.map((color) => <span key={color.hex} className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 px-2 py-1 text-xs text-slate-600"><span className="h-3 w-3 rounded-full border border-black/10" style={{ backgroundColor: color.hex }} />{color.hex}</span>)}</div></div>}{result.image_analysis.palette_comparison && <p className={`mt-3 text-xs font-medium ${result.image_analysis.palette_comparison.potential_mismatch ? "text-amber-700" : "text-emerald-700"}`}>{result.image_analysis.palette_comparison.potential_mismatch ? "Some image colours differ from the configured palette heuristic; check visually." : "Image colours are within the configured palette heuristic."}</p>}{result.image_analysis.limitations?.length > 0 && <ul className="mt-3 space-y-1 text-xs leading-5 text-slate-400">{result.image_analysis.limitations.map((limitation) => <li key={limitation}>• {limitation}</li>)}</ul>}</div>}
          {reviewId && <div className="border-t border-slate-100 p-4"><button type="button" className="btn-secondary w-full" onClick={() => navigate(`/reviews/${reviewId}`)}>Open human review <ArrowRightIcon /></button></div>}
        </>}
        {result?._source === "mock" && <div className="border-t border-amber-200 bg-amber-50 px-5 py-3 text-xs leading-5 text-amber-800">Illustrative mock response — not generated by an AI analysis engine.</div>}
      </section>
    </div>
  </>;
}

function ArrowRightIcon() { return <span aria-hidden="true">→</span>; }
