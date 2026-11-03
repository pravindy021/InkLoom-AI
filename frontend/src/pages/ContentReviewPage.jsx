import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Check,
  Clipboard,
  FileImage,
  FilePlus2,
  Film,
  LoaderCircle,
  Sparkles,
  X,
} from "lucide-react";
import { api, errorMessage, MOCK_MODE, unwrapList } from "../services/api";
import {
  Badge,
  EmptyState,
  ErrorMessage,
  PageHeader,
  SuccessMessage,
} from "../components/common/UI";
import VisualPaletteComparison from "../components/VisualPaletteComparison";
import {
  applySuggestionToContent,
  getSafeReplacement,
} from "../utils/applySuggestion";
import {
  formatVerificationMatchScore,
  getCitationSourceLabel,
  getEvidenceExcerptLabel,
} from "../utils/evidencePresentation";
import {
  getBrandVoiceFindingLabel,
  getBrandVoiceFindings,
} from "../utils/brandVoiceFindings";

const MAX_FILE_SIZE = 10 * 1024 * 1024;
const MAX_VIDEO_FILE_SIZE = 50 * 1024 * 1024;
const ACCEPTED = ["image/png", "image/jpeg", "image/webp", "application/pdf"];
const DOCX_TYPE =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const VIDEO_TYPES = {
  mp4: ["video/mp4"],
  mov: ["video/quicktime"],
  webm: ["video/webm"],
};

function isVideoFile(candidate) {
  return Boolean(candidate && /\.(mp4|mov|webm)$/i.test(candidate.name));
}

function isDocxFile(candidate) {
  return Boolean(candidate && /\.docx$/i.test(candidate.name));
}

function isPdfFile(candidate) {
  return Boolean(candidate && /\.pdf$/i.test(candidate.name));
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "Duration unavailable";
  const total = Math.floor(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

const field = (finding, ...keys) =>
  keys
    .map((key) => finding?.[key])
    .find((value) => value !== undefined && value !== null);

export default function ContentReviewPage() {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [contentType, setContentType] = useState("Campaign");
  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState("");
  const [videoPreviewUrl, setVideoPreviewUrl] = useState("");
  const [videoDuration, setVideoDuration] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(null);
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
  const [externalCheck, setExternalCheck] = useState({
    configured: false,
    provider: null,
    domains: [],
    llm: false,
    embeddings: false,
  });
  const [useExternalCheck, setUseExternalCheck] = useState(false);
  const [allowExternalAiProcessing, setAllowExternalAiProcessing] = useState(false);
  const [allowExternalTranscription, setAllowExternalTranscription] = useState(false);
  const [videoTranscriptionConfigured, setVideoTranscriptionConfigured] = useState(false);
  const [copied, setCopied] = useState("");

  const navigate = useNavigate();
  const fileInput = useRef(null);
  const videoFile = isVideoFile(file);

  useEffect(() => {
    if (!videoFile || !file) {
      setVideoPreviewUrl("");
      setVideoDuration(null);
      return undefined;
    }
    const url = URL.createObjectURL(file);
    setVideoPreviewUrl(url);
    setVideoDuration(null);
    return () => URL.revokeObjectURL(url);
  }, [file, videoFile]);

  const findings = unwrapList(result?.findings || result?.issues);

  const filtered = useMemo(
    () =>
      findings.filter(
        (item) =>
          (category === "all" ||
            String(field(item, "category", "type") || "").toLowerCase() ===
            category) &&
          (severity === "all" ||
            String(item.severity || "").toLowerCase() === severity)
      ),
    [findings, category, severity]
  );

  const categories = [
    ...new Set(
      findings
        .map((item) =>
          String(field(item, "category", "type") || "").toLowerCase()
        )
        .filter(Boolean)
    ),
  ];

  useEffect(() => {
    Promise.all([api.guidelines(), api.sources()])
      .then(([guidelineResponse, sourceResponse]) => {
        setGuidelines(unwrapList(guidelineResponse));
        setSources(
          unwrapList(sourceResponse).filter(
            (source) => source.approval_status === "approved"
          )
        );
      })
      .catch((err) => setGuidelineError(errorMessage(err)));

    api
      .health()
      .then((health) => {
        setExternalCheck({
          configured: Boolean(health?.external_fact_check_configured),
          provider: health?.external_fact_check_provider || null,
          domains: health?.trusted_source_domains || [],
          llm: health?.analysis_mode === "rules+configured_llm",
          embeddings: Boolean(health?.embedding_model_configured),
        });
        setVideoTranscriptionConfigured(
          Boolean(health?.video_transcription_configured),
        );
      })
      .catch(() =>
        setExternalCheck({
          configured: false,
          provider: null,
          domains: [],
          llm: false,
          embeddings: false,
        })
      );
  }, []);

  const chooseFile = (selected) => {
    setFileError("");

    if (!selected) {
      setFile(null);
      return;
    }

    const extension = selected.name.split(".").pop()?.toLowerCase();
    const videoMimeTypes = VIDEO_TYPES[extension];
    if (videoMimeTypes) {
      if (!videoMimeTypes.includes(selected.type)) {
        setFile(null);
        setFileError("The selected video extension and MIME type do not match.");
        return;
      }
      if (selected.size > MAX_VIDEO_FILE_SIZE) {
        setFile(null);
        setFileError("Video must be 50 MB or smaller.");
        return;
      }
      setContentType("Video");
      setAllowExternalTranscription(false);
      setFile(selected);
      return;
    }
    if (extension === "docx") {
      if (selected.type && ![DOCX_TYPE, "application/octet-stream"].includes(selected.type)) {
        setFile(null);
        setFileError("The DOCX extension and MIME type do not match.");
        return;
      }
      if (selected.size > MAX_FILE_SIZE) {
        setFile(null);
        setFileError("Document must be 10 MB or smaller.");
        return;
      }
      setContentType("Document");
      setFile(selected);
      return;
    }
    const validExtension = ["png", "jpg", "jpeg", "webp", "pdf"].includes(extension);
    if (!validExtension || (selected.type && !ACCEPTED.includes(selected.type))) {
      setFile(null);
      setFileError("Choose a PNG, JPG, WEBP, PDF, or DOCX file.");
      return;
    }

    if (selected.size > MAX_FILE_SIZE) {
      setFile(null);
      setFileError("File must be 10 MB or smaller.");
      return;
    }

    setFile(selected);
  };

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setSuccess("");

    if (!content.trim() && !videoFile && !isDocxFile(file) && !isPdfFile(file)) {
      setError("Add content or upload a document or video before running an analysis.");
      return;
    }

    setLoading(true);
    setUploadProgress(file ? 0 : null);
    setResult(null);

    try {
      const response = await api.analyze({
        title: title.trim() || "Untitled content",
        content: content.trim() || (videoFile ? `Video review: ${file.name}` : ""),
        content_type: contentType,
        file,
        guideline_ids: selectedGuidelines,
        source_ids: selectedSources,
        alt_text: altText,
        allow_external_verification: useExternalCheck,
        allow_external_transcription: allowExternalTranscription,
        allow_external_ai_processing: allowExternalAiProcessing,
        onUploadProgress: setUploadProgress,
      });

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

      setSuccess(
        MOCK_MODE
          ? "Mock analysis complete. These illustrative findings are not AI-generated."
          : `${response?.analysis_engine === "rules+configured_llm"
            ? "Rules and configured LLM analysis"
            : "Local rules analysis"
          } completed. Review findings before deciding what to change.${externalNotice}`
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
      setUploadProgress(null);
      setAllowExternalAiProcessing(false);
    }
  };

  const applySuggestion = (finding) => {
    const matched = field(finding, "matched_text", "matchedText", "text");
    const suggestion = field(
      finding,
      "suggestion",
      "suggested_correction",
      "correction"
    );
    const findingCategory = field(finding, "category", "type");

    if (!matched || !suggestion) {
      setError("This finding does not contain usable text and guidance.");
      return;
    }

    const safe = getSafeReplacement(
      String(matched),
      String(suggestion),
      findingCategory
    );

    if (!safe.ok) {
      setError(
        "This suggestion is guidance, not ready-to-insert replacement text. Edit the draft manually."
      );
      return;
    }

    const applied = applySuggestionToContent(
      content,
      String(matched),
      safe.replacement
    );

    if (!applied.ok) {
      const messages = {
        "not-found": `Couldn't find “${matched}” in the current text. Edit the draft manually.`,
        ambiguous: `“${matched}” appears more than once. Edit the intended occurrence manually.`,
        "missing-text": "The finding does not contain usable replacement text.",
        "invalid-input": "This suggestion cannot be applied automatically.",
      };

      setError(
        messages[applied.reason] ||
        "This suggestion cannot be applied automatically."
      );
      return;
    }

    setContent(applied.content);
    setSuccess(
      "Approved terminology replacement applied. Review the draft before saving."
    );
  };

  const copySuggestion = async (finding) => {
    const suggestion = field(
      finding,
      "suggestion",
      "suggested_correction",
      "correction"
    );

    try {
      await navigator.clipboard.writeText(String(suggestion || ""));
      setCopied(finding.id);
      window.setTimeout(() => setCopied(""), 1500);
    } catch {
      setError(
        "Clipboard access is unavailable. Select and copy the suggested text instead."
      );
    }
  };

  const reviewId = result?.id ?? result?.review_id;

  return (
    <>
      <PageHeader
        eyebrow="Content workspace"
        title="Review content"
        description="Check text and supported imagery against your brand standards. Every recommendation is advisory."
      />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.12fr)_minmax(390px,.88fr)]">
        <form onSubmit={submit} className="card p-5 sm:p-6">
          <div className="mb-5 flex items-center gap-3">
            <div className="rounded-lg bg-ink-50 p-2 text-ink-700">
              <FilePlus2 size={18} />
            </div>
            <div>
              <h2 className="font-semibold text-ink-900">
                Content to review
              </h2>
              <p className="mt-1 text-xs text-slate-500">
                Add the draft you want checked
              </p>
            </div>
          </div>

          <label
            className="mb-1.5 block text-sm font-medium text-slate-700"
            htmlFor="content-title"
          >
            Content title <span className="text-slate-400">(optional)</span>
          </label>

          <input
            id="content-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="field mb-4"
            placeholder="e.g. Spring campaign landing page"
          />

          <div className="mb-1.5 flex items-center justify-between">
            <label
              htmlFor="content-type"
              className="text-sm font-medium text-slate-700"
            >
              Content type
            </label>
            <span className="text-xs text-slate-400">
              {content.length.toLocaleString()} characters
            </span>
          </div>

          <select
            id="content-type"
            value={contentType}
            onChange={(e) => setContentType(e.target.value)}
            className="field mb-4"
          >
            <option>Campaign</option>
            <option>Social post</option>
            <option>Email</option>
            <option>Product page</option>
            <option>Blog article</option>
            <option>Video</option>
            <option>Other</option>
          </select>

          <div className="mb-4">
            <p className="mb-2 text-sm font-medium text-slate-700">
              Guidelines <span className="font-normal text-slate-400">(optional)</span>
            </p>

            {guidelines.length ? (
              <div className="max-h-36 space-y-2 overflow-y-auto rounded-lg border border-slate-200 p-3">
                {guidelines.map((guideline) => (
                  <label
                    key={guideline.id}
                    className="flex cursor-pointer items-start gap-2 text-sm text-slate-600"
                  >
                    <input
                      type="checkbox"
                      className="mt-1 accent-ink-700"
                      checked={selectedGuidelines.includes(guideline.id)}
                      onChange={(event) =>
                        setSelectedGuidelines((current) =>
                          event.target.checked
                            ? [...current, guideline.id]
                            : current.filter((id) => id !== guideline.id)
                        )
                      }
                    />
                    <span>
                      {guideline.name || guideline.title || "Guideline"}
                      <span className="ml-2 text-xs text-slate-400">
                        {guideline.category || ""}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            ) : (
              <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
                {guidelineError
                  ? `Guidelines unavailable: ${guidelineError}`
                  : "No guidelines returned by the API."}
              </p>
            )}
          </div>

          {sources.length > 0 && (
            <div className="mb-4">
              <p className="mb-2 text-sm font-medium text-slate-700">
                Evidence sources{" "}
                <span className="font-normal text-slate-400">(optional)</span>
              </p>

              <div className="max-h-36 space-y-2 overflow-y-auto rounded-lg border border-slate-200 p-3">
                {sources.map((source) => (
                  <label
                    key={source.id}
                    className="flex cursor-pointer items-start gap-2 text-sm text-slate-600"
                  >
                    <input
                      type="checkbox"
                      className="mt-1 accent-ink-700"
                      checked={selectedSources.includes(source.id)}
                      onChange={(event) =>
                        setSelectedSources((current) =>
                          event.target.checked
                            ? [...current, source.id]
                            : current.filter((id) => id !== source.id)
                        )
                      }
                    />
                    <span>
                      {source.name}
                      <span className="ml-2 text-xs text-slate-400">
                        {source.expiry_date
                          ? `expires ${source.expiry_date}`
                          : "no expiry date"}
                      </span>
                    </span>
                  </label>
                ))}
              </div>

              <p className="mt-1.5 text-xs text-slate-400">
                Retrieved excerpts are candidate evidence for a human to verify,
                not automatic proof.
              </p>
            </div>
          )}

          {(externalCheck.llm || externalCheck.embeddings) && (
            <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-950">
              Configured remote analysis services are used only when you opt in
              for an analysis:{" "}
              {externalCheck.llm &&
                "the LLM receives submitted text and guideline context"}
              {externalCheck.llm && externalCheck.embeddings && "; "}
              {externalCheck.embeddings &&
                "the embedding provider receives claim excerpts and selected approved-source chunks"}
              . Review provider data-handling terms and do not submit confidential
              material unless your organization permits it.
            </p>
          )}

          {(externalCheck.llm || externalCheck.embeddings) && (
            <label className="mb-4 flex cursor-pointer items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
              <input
                className="mt-1 h-4 w-4 accent-ink-700"
                type="checkbox"
                checked={allowExternalAiProcessing}
                onChange={(event) =>
                  setAllowExternalAiProcessing(event.target.checked)
                }
              />
              <span>
                <span className="font-semibold">
                  Allow remote AI/embedding processing for this analysis
                </span>
                <span className="mt-1 block text-xs leading-5">
                  {externalCheck.llm &&
                    "Submitted text and guideline context may be sent to the configured LLM. "}
                  {externalCheck.embeddings &&
                    "Detected claim excerpts and selected approved-source chunks may be sent to the embedding provider. "}
                  This is separate from external fact checking and video
                  transcription. Leave unchecked for local deterministic
                  analysis and lexical retrieval.
                </span>
              </span>
            </label>
          )}

          {externalCheck.configured ? (
            <label className="mb-4 flex cursor-pointer items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
              <input
                className="mt-1 h-4 w-4 accent-ink-700"
                type="checkbox"
                checked={useExternalCheck}
                onChange={(event) =>
                  setUseExternalCheck(event.target.checked)
                }
              />
              <span>
                <span className="font-semibold">
                  Check trusted external sources with{" "}
                  {externalCheck.provider === "brave"
                    ? "Brave Search"
                    : externalCheck.provider}
                </span>
                <span className="mt-1 block text-xs leading-5">
                  Only detected claim excerpts (not the full draft or image)
                  are sent to this provider. Claims may still be confidential;
                  opt in only when permitted. Results are limited to{" "}
                  {externalCheck.domains.join(", ")} and remain advisory.
                </span>
              </span>
            </label>
          ) : (
            <p className="mb-4 rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-500">
              External fact checking is not configured. This analysis uses only
              local approved sources; no external fact-checking service will
              receive content.
            </p>
          )}

          <label
            htmlFor="content-text"
            className="mb-1.5 block text-sm font-medium text-slate-700"
          >
            Draft content
            {(videoFile || isDocxFile(file) || isPdfFile(file)) && (
              <span className="font-normal text-slate-400">
                {" "}(optional with uploaded document/video)
              </span>
            )}
          </label>

          <textarea
            id="content-text"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={12}
            className="field resize-y leading-6"
            placeholder="Paste or write your content here..."
          />

          <div className="mt-5">
            <div className="mb-2 text-sm font-medium text-slate-700">
              Content file{" "}
              <span className="font-normal text-slate-400">(optional)</span>
            </div>

            <input
              ref={fileInput}
              type="file"
              accept=".png,.jpg,.jpeg,.webp,.pdf,.docx,.mp4,.mov,.webm,image/png,image/jpeg,image/webp,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,video/mp4,video/quicktime,video/webm"
              className="sr-only"
              onChange={(e) => {
                chooseFile(e.target.files?.[0]);
                e.target.value = "";
              }}
              aria-label="Upload image, PDF, DOCX, or video"
            />

            {file ? (
              <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                {videoFile ? (
                  <Film size={18} className="text-ink-600" />
                ) : (
                  <FileImage size={18} className="text-ink-600" />
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-700">
                    {file.name}
                  </p>
                  <p className="text-xs text-slate-400">
                    {(file.size / 1024 / 1024).toFixed(2)} MB ·{" "}
                    {videoFile
                      ? formatDuration(videoDuration)
                        : isDocxFile(file)
                          ? "DOCX · Ready to extract and submit"
                          : "Ready to submit"}
                  </p>
                </div>
                <button
                  type="button"
                  className="rounded p-1.5 text-slate-400 hover:bg-white hover:text-rose-600"
                  aria-label="Remove visual file"
                  onClick={() => setFile(null)}
                >
                  <X size={17} />
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => fileInput.current?.click()}
                className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 px-4 py-4 text-sm text-slate-500 hover:border-ink-400 hover:bg-ink-50/40"
              >
                <FileImage size={17} />
                Upload visual, document, or video content
                <span className="text-xs text-slate-400">
                  Images/PDF/DOCX up to 10 MB · MP4/MOV/WEBM up to 50 MB
                </span>
              </button>
            )}

            {videoFile && videoPreviewUrl && (
              <div className="mt-3 overflow-hidden rounded-lg border border-slate-200 bg-slate-950">
                <video
                  className="max-h-72 w-full"
                  controls
                  preload="metadata"
                  src={videoPreviewUrl}
                  onLoadedMetadata={(event) =>
                    setVideoDuration(event.currentTarget.duration)
                  }
                  onError={() =>
                    setFileError("The selected video could not be previewed; it may be corrupted or unsupported.")
                  }
                >
                  Your browser cannot preview this video.
                </video>
              </div>
            )}

            {videoFile && videoTranscriptionConfigured && (
              <label className="mt-3 flex cursor-pointer items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
                <input
                  className="mt-1 h-4 w-4 accent-ink-700"
                  type="checkbox"
                  checked={allowExternalTranscription}
                  onChange={(event) =>
                    setAllowExternalTranscription(event.target.checked)
                  }
                />
                <span>
                  <strong>Send extracted audio for transcription</strong>
                  <span className="mt-1 block text-xs leading-5">
                    The audio track will be sent to the workspace-configured
                    speech-to-text service. This is an external disclosure;
                    select only when permitted. Without consent, audio is not
                    sent and transcript-based findings are unavailable.
                  </span>
                </span>
              </label>
            )}

            {videoFile && !videoTranscriptionConfigured && (
              <p className="mt-3 rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-600">
                Speech transcription is not configured. No audio will be sent
                to an external service. Local frame analysis will still run;
                timestamped speech findings require a configured transcription
                service.
              </p>
            )}

            {file && !videoFile && !isDocxFile(file) && file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf") && (
              <div className="mt-3">
                <label
                  className="mb-1.5 block text-sm font-medium text-slate-700"
                  htmlFor="asset-alt-text"
                >
                  Image alternative text{" "}
                  <span className="font-normal text-slate-400">(optional)</span>
                </label>
                <input
                  id="asset-alt-text"
                  className="field"
                  maxLength={1000}
                  value={altText}
                  onChange={(e) => setAltText(e.target.value)}
                  placeholder="Describe the image’s purpose for screen-reader users"
                />
              </div>
            )}

            {fileError && (
              <p className="mt-2 text-sm text-rose-700">{fileError}</p>
            )}

            <p className="mt-2 text-xs leading-5 text-slate-400">
              {videoFile
                ? "Video is processed locally with FFmpeg using bounded frame and duration limits. The private source video is stored with this review for authorized members."
                : isDocxFile(file)
                  ? "DOCX paragraph and table text is extracted locally. The original document is stored privately with this review for authenticated members."
                  : "PDF pages are inspected individually. Scanned-page OCR runs locally only when enabled and Tesseract is installed. Uploaded files are stored privately with this review for authenticated reviewers. PDF page layout and vector artwork are not visually analyzed."}
            </p>
          </div>

          {error && (
            <div className="mt-4">
              <ErrorMessage>{error}</ErrorMessage>
            </div>
          )}

          {success && (
            <div className="mt-4">
              <SuccessMessage>{success}</SuccessMessage>
            </div>
          )}

          <button
            type="submit"
            className="btn-primary mt-5 w-full"
            disabled={loading || Boolean(fileError)}
          >
            {loading ? (
              <>
                <LoaderCircle size={17} className="animate-spin" />
                {file && uploadProgress !== null && uploadProgress < 100
                  ? `Uploading ${uploadProgress}%…`
                  : "Analysing content…"}
              </>
            ) : (
              <>
                <Sparkles size={17} />
                Analyse content
              </>
            )}
          </button>

          {loading && (
            <div className="mt-3 text-center text-xs text-slate-400" role="status">
              <p>
                {uploadProgress !== null && uploadProgress < 100
                  ? `Uploading file: ${uploadProgress}%`
                  : "Waiting for analysis. Video processing may take a few minutes."}
              </p>
              {uploadProgress !== null && (
                <progress className="mt-2 w-full" max="100" value={uploadProgress} />
              )}
            </div>
          )}
        </form>

        <section className="card min-h-[400px]" aria-live="polite">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div>
              <h2 className="font-semibold text-ink-900">
                Analysis findings
              </h2>
              <p className="mt-1 text-xs text-slate-500">
                Review each recommendation before applying
              </p>
            </div>
            {findings.length > 0 && (
              <Badge>{findings.length} findings</Badge>
            )}
          </div>

          {!result ? (
            <EmptyState
              icon={Sparkles}
              title="Your findings will appear here"
              description="Submit your draft to receive guideline-based feedback. Nothing is approved automatically."
            />
          ) : (
            <>
              {result.provider_warnings?.length > 0 && (
                <div
                  className="border-b border-amber-200 bg-amber-50 px-5 py-3 text-sm text-amber-900"
                  role="status"
                >
                  <p className="font-semibold">
                    An optional AI service was unavailable.
                  </p>
                  <ul className="mt-1 list-disc space-y-1 pl-5 text-xs leading-5">
                    {result.provider_warnings.map((warning, index) => (
                      <li key={`${index}-${warning}`}>{warning}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="flex flex-wrap gap-2 border-b border-slate-100 px-5 py-3">
                <select
                  aria-label="Filter by category"
                  className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-600"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                >
                  <option value="all">All categories</option>
                  {categories.map((c) => (
                    <option value={c} key={c}>
                      {c}
                    </option>
                  ))}
                </select>

                <select
                  aria-label="Filter by severity"
                  className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-600"
                  value={severity}
                  onChange={(e) => setSeverity(e.target.value)}
                >
                  <option value="all">All severity</option>
                  {["high", "medium", "low", "critical"].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </div>

              {filtered.length ? (
                <div className="space-y-4 p-4">
                  {filtered.map((item, index) => {
                    const matched = field(
                      item,
                      "matched_text",
                      "matchedText",
                      "text"
                    );

                    const suggestion = field(
                      item,
                      "suggestion",
                      "suggested_correction",
                      "correction"
                    );
                    const brandVoiceFindings = getBrandVoiceFindings(item);

                    return (
                      <article
                        key={item.id || index}
                        className="rounded-lg border border-slate-200 p-4"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs font-semibold text-ink-700">
                            {field(item, "category", "type") || "Finding"}
                          </span>

                          <Badge tone="severity">
                            {item.severity || "medium"}
                          </Badge>

                          <span className="ml-auto">
                            <Badge tone="status">
                              {item.status || "open"}
                            </Badge>
                          </span>
                        </div>

                        <p className="mt-3 text-sm leading-6 text-slate-700">
                          {field(
                            item,
                            "explanation",
                            "description",
                            "message"
                          ) || "Review this item against the applicable guideline."}
                        </p>

                        <VisualPaletteComparison
                          comparison={item.visual_data?.palette_comparison}
                        />

                        {item.verification_status && (
                          <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                                Claim verification
                              </span>

                              <Badge
                                tone={
                                  item.verification_status === "verified"
                                    ? "approved"
                                    : item.verification_status ===
                                      "contradicted"
                                      ? "severity"
                                      : "status"
                                }
                              >
                                {item.verification_status ===
                                  "conflicting_evidence"
                                  ? "conflicting evidence"
                                  : item.verification_status}
                              </Badge>
                            </div>

                            {item.claim && (
                              <p className="mt-2 text-xs leading-5 text-slate-700">
                                <strong>Claim assessed: </strong>
                                {item.claim}
                              </p>
                            )}

                            <p className="mt-2 text-xs leading-5 text-slate-600">
                              {item.verification_explanation ||
                                (item.verification_status === "unverified"
                                  ? "Lack of evidence is not proof that this claim is false."
                                  : "")}
                            </p>
                            {formatVerificationMatchScore(
                              item.verification_confidence
                            ) && (
                              <p className="mt-1 text-xs text-slate-500">
                                {formatVerificationMatchScore(
                                  item.verification_confidence
                                )}
                              </p>
                            )}

                            {item.citations?.map((source, sourceIndex) => (
                              <div
                                key={`${source.source_id || source.id || source.url || source.name}-${sourceIndex}`}
                                className="mt-3 rounded-md border border-slate-200 bg-white p-3"
                              >
                                <div className="flex flex-wrap items-center gap-2">
                                  <p className="text-xs font-semibold text-slate-700">
                                    {source.name || "Evidence source"}
                                  </p>

                                  <Badge tone="status">
                                    {getCitationSourceLabel(source)}
                                  </Badge>
                                </div>

                                <div className="mt-2 grid gap-1 text-xs text-slate-500">
                                  {source.source_id != null && (
                                    <p>Source ID: {source.source_id}</p>
                                  )}

                                  {source.guideline_id != null && (
                                    <p>
                                      Linked guideline ID: {source.guideline_id}
                                    </p>
                                  )}

                                  {source.source_date && (
                                    <p>Source date: {source.source_date}</p>
                                  )}

                                  {source.expiry_date && (
                                    <p>Expiry date: {source.expiry_date}</p>
                                  )}

                                  {source.freshness && (
                                    <p>
                                      Freshness:{" "}
                                      {source.freshness.replaceAll("_", " ")}
                                    </p>
                                  )}
                                </div>

                                {source.excerpt && (
                                  <div className="mt-2 rounded bg-slate-50 p-2">
                                    <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                                      {getEvidenceExcerptLabel(
                                        item.evidence_status ||
                                          item.verification_status
                                      )}
                                    </p>
                                    <p className="text-xs leading-5 text-slate-600">
                                      {source.excerpt}
                                    </p>
                                  </div>
                                )}

                                {source.url && (
                                  <a
                                    className="mt-2 inline-block text-xs font-medium text-ink-700 underline"
                                    href={source.url}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    Open citation
                                  </a>
                                )}
                              </div>
                            ))}
                          </div>
                        )}

                        {matched && (
                          <div className="mt-3 rounded-md bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-800">
                            <span className="font-semibold">
                              Flagged text:{" "}
                            </span>
                            “{matched}”
                          </div>
                        )}

                        {brandVoiceFindings.map((voiceFinding, voiceIndex) => (
                          <section
                            key={`${voiceFinding.finding_type || voiceFinding.brand_voice_category}-${voiceIndex}`}
                            className="mt-3 rounded-md border border-violet-200 bg-violet-50/60 p-3"
                          >
                            <div className="flex flex-wrap items-center gap-2">
                              <strong className="text-xs text-violet-900">
                                Brand voice · {voiceFinding.brand_voice_category || "Configured voice"}
                              </strong>
                              <Badge tone={
                                voiceFinding.assessment === "configured_rule_violation"
                                  ? "severity"
                                  : "status"
                              }>
                                {getBrandVoiceFindingLabel(voiceFinding)}
                              </Badge>
                            </div>
                            {voiceFinding.matched_text && (
                              <p className="mt-2 text-xs leading-5 text-violet-950">
                                <strong>Matched content: </strong>
                                {voiceFinding.matched_text}
                              </p>
                            )}
                            {voiceFinding.configuration_rule && (
                              <p className="mt-2 text-xs leading-5 text-violet-900">
                                <strong>Configured rule: </strong>
                                {voiceFinding.configuration_rule}
                              </p>
                            )}
                            <p className="mt-2 text-xs leading-5 text-violet-900">
                              {voiceFinding.explanation}
                            </p>
                            {voiceFinding.suggestion ? (
                              <p className="mt-2 text-xs leading-5 text-violet-900">
                                <strong>Suggestion: </strong>
                                {voiceFinding.suggestion}
                              </p>
                            ) : voiceFinding.suggestion_status ? (
                              <p className="mt-2 text-xs text-violet-700">
                                {voiceFinding.suggestion_status}
                              </p>
                            ) : null}
                          </section>
                        ))}

                        {suggestion && (
                          <div className="mt-3 rounded-md border border-emerald-100 bg-emerald-50/60 p-3">
                            <p className="text-[11px] font-bold uppercase tracking-wide text-emerald-800">
                              Suggested correction
                            </p>

                            <p className="mt-1 text-sm leading-5 text-emerald-900">
                              {suggestion}
                            </p>

                            <div className="mt-2 flex flex-wrap gap-2">
                              <button
                                className="btn-secondary !px-2.5 !py-1.5 !text-xs"
                                onClick={() => applySuggestion(item)}
                                type="button"
                              >
                                <Check size={13} />
                                Apply to text
                              </button>

                              <button
                                className="btn-secondary !px-2.5 !py-1.5 !text-xs"
                                onClick={() => copySuggestion(item)}
                                type="button"
                              >
                                {copied === item.id ? (
                                  <Check size={13} />
                                ) : (
                                  <Clipboard size={13} />
                                )}
                                {copied === item.id ? "Copied" : "Copy"}
                              </button>
                            </div>
                          </div>
                        )}

                        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
                          <span>
                            Guideline:{" "}
                            {field(item, "guideline", "reference") ||
                              "Not supplied"}
                          </span>
                          {item.source && (
                            <span>Source: {item.source}</span>
                          )}

                          {field(item, "confidence", "confidence_score") !=
                            null && (
                              <span>
                                Confidence:{" "}
                                {Math.round(
                                  Number(
                                    field(
                                      item,
                                      "confidence",
                                      "confidence_score"
                                    )
                                  ) *
                                  (Number(
                                    field(
                                      item,
                                      "confidence",
                                      "confidence_score"
                                    )
                                  ) <= 1
                                    ? 100
                                    : 1)
                                )}
                                %
                              </span>
                            )}
                        </div>
                      </article>
                    );
                  })}
                </div>
              ) : (
                <EmptyState
                  title="No findings match these filters"
                  description="Try a different category or severity."
                />
              )}

              {result.retrieved_evidence?.length > 0 && (
                <div className="border-t border-slate-100 p-4">
                  <h3 className="text-sm font-semibold text-slate-800">
                    Candidate evidence excerpts
                  </h3>

                  <p className="mt-1 text-xs text-slate-500">
                    Approved sources are{" "}
                    {result.evidence_retrieval_method === "embedding_cosine"
                      ? "semantically ranked"
                      : "lexically ranked with BM25"}
                    ; external results come from the configured search
                    provider. A reviewer must verify every match.
                  </p>

                  <div className="mt-3 space-y-3">
                    {result.retrieved_evidence.map((evidence, index) => (
                      <article
                        key={`${evidence.source_type || "approved"}-${evidence.source_id || evidence.id || evidence.url || evidence.name}-${index}`}
                        className="rounded-lg border border-slate-200 p-3"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold text-slate-700">
                            {evidence.name || "Source"}
                          </span>

                          <Badge tone="status">
                            {evidence.source_type ===
                              "external_trusted_source"
                              ? "External candidate · not independently verified"
                              : evidence.approval_status ||
                              (evidence.freshness || "date unknown").replaceAll(
                                "_",
                                " "
                              )}
                          </Badge>

                          {Number.isFinite(evidence.relevance_score) && (
                            <span className="text-xs text-slate-400">
                              Match {Math.round(evidence.relevance_score * 100)}%
                            </span>
                          )}
                        </div>

                        <div className="mt-2 grid gap-1 text-xs text-slate-500">
                          {evidence.source_id != null && (
                            <p>Source ID: {evidence.source_id}</p>
                          )}

                          {evidence.guideline_id != null && (
                            <p>Linked guideline ID: {evidence.guideline_id}</p>
                          )}

                          {evidence.source_date && (
                            <p>Source date: {evidence.source_date}</p>
                          )}

                          {evidence.expiry_date && (
                            <p>Expiry date: {evidence.expiry_date}</p>
                          )}

                          {evidence.retrieval_method && (
                            <p>
                              Retrieval method: {evidence.retrieval_method}
                            </p>
                          )}
                        </div>

                        <p className="mt-2 text-sm leading-6 text-slate-600">
                          {evidence.excerpt}
                        </p>

                        {evidence.url && (
                          <a
                            className="mt-2 inline-block text-xs font-medium text-ink-700 underline"
                            href={evidence.url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Open source
                          </a>
                        )}
                      </article>
                    ))}
                  </div>
                </div>
              )}

              {result.image_analysis && (
                <div className="border-t border-slate-100 p-4">
                  <h3 className="text-sm font-semibold text-slate-800">
                    Visual asset checks
                  </h3>

                  <p className="mt-1 text-xs text-slate-500">
                    {result.image_analysis.format?.toUpperCase()}
                    {result.image_analysis.format === "pdf"
                      ? ` · ${result.image_analysis.page_count} pages inspected`
                      : ` · ${result.image_analysis.width} × ${result.image_analysis.height}px`}
                    {result.image_analysis.ocr_available === undefined
                      ? ""
                      : result.image_analysis.ocr_available
                        ? " · OCR available"
                        : " · OCR unavailable"}
                  </p>

                  {result.image_analysis.pages?.length > 0 && (
                    <div className="mt-3 space-y-2">
                      {result.image_analysis.pages.map((page) => (
                        <div key={page.page_number} className="rounded-lg border border-slate-200 p-3">
                          <p className="text-xs font-semibold text-slate-700">
                            Page {page.page_number} · {page.images?.length || 0} embedded image(s)
                            {page.ocr_used
                              ? ` · OCR extracted ${page.text_characters || 0} text characters`
                              : page.text_layer_detected
                                ? ` · ${page.text_characters || 0} digital text characters`
                                : " · no text layer"}
                          </p>
                          {page.limitations?.map((limitation) => (
                            <p key={limitation} className="mt-1 text-xs text-amber-800">{limitation}</p>
                          ))}
                        </div>
                      ))}
                    </div>
                  )}

                  {result.image_analysis.layout_metrics && (
                    <div className="mt-3 rounded-lg border border-slate-200 p-3">
                      <h4 className="text-xs font-semibold text-slate-700">
                        Layout signals{" "}
                        <span className="font-normal text-slate-400">
                          (descriptive heuristics)
                        </span>
                      </h4>

                      <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-600">
                        <span className="rounded bg-slate-50 px-2 py-1">
                          {result.image_analysis.layout_metrics.orientation} ·{" "}
                          {result.image_analysis.layout_metrics.aspect_ratio}:1
                        </span>

                        <span className="rounded bg-slate-50 px-2 py-1">
                          Edge density{" "}
                          {result.image_analysis.layout_metrics.edge_density_percent}%
                        </span>

                        {result.image_analysis.layout_metrics.has_transparency && (
                          <span className="rounded bg-slate-50 px-2 py-1">
                            Transparent canvas ·{" "}
                            {result.image_analysis.layout_metrics.transparent_bounds
                              ?.content_occupancy_percent ?? "—"}
                            % occupied
                          </span>
                        )}

                        {result.image_analysis.layout_metrics.small_for_large_display && (
                          <span className="rounded bg-amber-50 px-2 py-1 text-amber-800">
                            Under 500px max dimension (inspect for intended use)
                          </span>
                        )}
                      </div>

                      <p className="mt-2 text-[11px] leading-5 text-slate-400">
                        {result.image_analysis.layout_metrics.method}
                      </p>
                    </div>
                  )}

                  {result.image_analysis.brand_asset_similarity?.configured && (
                    <div className="mt-3 rounded-lg border border-slate-200 p-3">
                      <h4 className="text-xs font-semibold text-slate-700">
                        Configured asset references{" "}
                        <span className="font-normal text-slate-400">
                          (coarse image-hash similarity)
                        </span>
                      </h4>

                      <div className="mt-2 space-y-1">
                        {result.image_analysis.brand_asset_similarity.references.map(
                          (reference) => (
                            <p
                              key={reference.name}
                              className="flex justify-between gap-3 text-xs text-slate-600"
                            >
                              <span className="truncate">
                                {reference.name}
                              </span>
                              <span className="shrink-0">
                                {reference.similarity_percent}% similar
                              </span>
                            </p>
                          )
                        )}
                      </div>

                      {result.image_analysis.brand_asset_similarity.potential_mismatch && (
                        <p className="mt-2 text-xs leading-5 text-amber-800">
                          This asset may be a different variant; confirm it
                          against the approved asset library.
                        </p>
                      )}
                    </div>
                  )}

                  {result.image_analysis.extracted_text && (
                    <div className="mt-3 rounded-md bg-slate-50 p-3">
                      <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">
                        Text extracted from image
                      </p>
                      <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">
                        {result.image_analysis.extracted_text}
                      </p>
                    </div>
                  )}

                  {result.image_analysis.text_contrast?.length > 0 && (
                    <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
                      <p className="text-xs font-semibold text-amber-950">Estimated text contrast</p>
                      {result.image_analysis.text_contrast.map((item, index) => (
                        <p key={`${item.text}-${index}`} className="mt-1 text-xs leading-5 text-amber-900">
                          “{item.text}” · {item.contrast_ratio}:1 (estimated AA threshold {item.threshold}:1)
                        </p>
                      ))}
                      <p className="mt-2 text-[11px] leading-5 text-amber-800">OCR and colour clustering can misidentify foreground/background; this is not a complete WCAG audit.</p>
                    </div>
                  )}

                  {result.image_analysis.dominant_colors?.length > 0 && (
                    <div className="mt-3">
                      <p className="mb-2 text-xs font-medium text-slate-500">
                        Dominant image colours
                      </p>

                      <div className="flex flex-wrap gap-2">
                        {result.image_analysis.dominant_colors.map((color) => (
                          <span
                            key={color.hex}
                            className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 px-2 py-1 text-xs text-slate-600"
                          >
                            <span
                              className="h-3 w-3 rounded-full border border-black/10"
                              style={{ backgroundColor: color.hex }}
                            />
                            {color.hex}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {result.image_analysis.palette_comparison && (
                    <>
                      <p
                        className={`mt-3 text-xs font-medium ${result.image_analysis.palette_comparison.potential_mismatch
                            ? "text-amber-700"
                            : "text-emerald-700"
                          }`}
                      >
                        {result.image_analysis.palette_comparison.potential_mismatch
                          ? "Some image colours differ from the configured palette heuristic; check visually."
                          : "Image colours are within the configured palette heuristic."}
                      </p>
                      <VisualPaletteComparison
                        comparison={result.image_analysis.palette_comparison}
                      />
                    </>
                  )}

                  {result.image_analysis.limitations?.length > 0 && (
                    <ul className="mt-3 space-y-1 text-xs leading-5 text-slate-400">
                      {result.image_analysis.limitations.map((limitation) => (
                        <li key={limitation}>• {limitation}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {reviewId && (
                <div className="border-t border-slate-100 p-4">
                  <button
                    type="button"
                    className="btn-secondary w-full"
                    onClick={() => navigate(`/reviews/${reviewId}`)}
                  >
                    Open human review <ArrowRightIcon />
                  </button>
                </div>
              )}
            </>
          )}

          {result?._source === "mock" && (
            <div className="border-t border-amber-200 bg-amber-50 px-5 py-3 text-xs leading-5 text-amber-800">
              Illustrative mock response — not generated by an AI analysis
              engine.
            </div>
          )}
        </section>
      </div>
    </>
  );
}

function ArrowRightIcon() {
  return <span aria-hidden="true">→</span>;
}