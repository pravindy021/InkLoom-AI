const wait = (value) => new Promise((resolve) => setTimeout(() => resolve(value), 350));

const reviews = [
  {
    id: "rv-1048",
    title: "Autumn collection launch",
    content_type: "Campaign",
    status: "in_review",
    submitted_at: "2026-10-25T10:30:00Z",
    issue_count: 3,
    reviewer: "Maya Chen",
    content: "Meet the ultimate autumn collection. Our new pieces are guaranteed to transform your everyday wardrobe.",
    findings: [
      { id: "f1", category: "Claims", severity: "high", explanation: "Absolute performance language needs substantiation.", matched_text: "guaranteed to transform", suggestion: "designed to refresh", guideline: "Substantiated claims", confidence: 0.94, status: "open" },
      { id: "f2", category: "Tone of voice", severity: "medium", explanation: "“Ultimate” is more superlative than the approved brand voice.", matched_text: "ultimate", suggestion: "considered", guideline: "Confident, never boastful", confidence: 0.89, status: "open" },
      { id: "f3", category: "Terminology", severity: "low", explanation: "Use the preferred product term in campaign copy.", matched_text: "pieces", suggestion: "essentials", guideline: "Product vocabulary", confidence: 0.83, status: "open" },
    ],
    revisions: [],
    comments: [],
  },
  { id: "rv-1047", title: "Welcome email refresh", content_type: "Email", status: "approved", submitted_at: "2026-10-24T14:05:00Z", issue_count: 1, reviewer: "Eli Morgan", content: "A warmer welcome to your new routine.", findings: [], revisions: [], comments: [] },
  { id: "rv-1046", title: "Product page: Cloud Knit", content_type: "Product page", status: "changes_requested", submitted_at: "2026-10-23T09:20:00Z", issue_count: 4, reviewer: "Jordan Lee", content: "Soft, sustainable comfort for every day.", findings: [], revisions: [], comments: [] },
];

const guidelines = [
  { id: "g1", name: "Confident, never boastful", category: "Tone of voice", severity: "medium", description: "Use clear, assured language. Avoid superlatives and absolute promises.", status: "approved" },
  { id: "g2", name: "Substantiated claims", category: "Claims", severity: "high", description: "Promotional or performance claims must have current supporting evidence.", status: "approved" },
  { id: "g3", name: "Product vocabulary", category: "Terminology", severity: "low", description: "Use approved product names and preferred customer-facing terms.", status: "approved" },
];
const sources = [];

export const mockApi = {
  health: () => wait({ status: "ok", mode: "mock" }),
  guidelines: () => wait(guidelines),
  createGuideline: async (data) => {
    const item = { ...data, id: `g${Date.now()}`, status: "approved" };
    guidelines.unshift(item);
    return wait(item);
  },
  deleteGuideline: async (id) => {
    const index = guidelines.findIndex((item) => String(item.id) === String(id));
    if (index >= 0) guidelines.splice(index, 1);
    return wait({ success: true });
  },
  sources: () => wait(sources),
  createSource: async (data) => {
    const source = { ...data, id: `source-${Date.now()}`, created_at: new Date().toISOString() };
    sources.unshift(source);
    return wait(source);
  },
  uploadSource: async ({ file, ...data }) => {
    if (!file || !/\.(txt|md)$/i.test(file.name)) {
      throw new Error("Mock mode supports TXT and Markdown source uploads only.");
    }
    const source = { ...data, name: data.name || file.name, content: await file.text(), id: `source-${Date.now()}`, created_at: new Date().toISOString() };
    sources.unshift(source);
    return wait(source);
  },
  deleteSource: async (id) => {
    const index = sources.findIndex((item) => String(item.id) === String(id));
    if (index >= 0) sources.splice(index, 1);
    return wait({ success: true });
  },
  analyze: async ({ title, content, content_type }) => {
    const review = {
      id: `rv-${Date.now()}`,
      title,
      content,
      content_type,
      status: "pending",
      submitted_at: new Date().toISOString(),
      issue_count: 1,
      findings: [{
        id: `finding-${Date.now()}`,
        category: "Tone of voice",
        severity: "medium",
        explanation: "This illustrative mock finding flags a phrase for review. It is not an AI analysis.",
        matched_text: content.match(/\b(ultimate|guaranteed|best)\b/i)?.[0] || content.split(/\s+/).slice(0, 3).join(" "),
        suggestion: "Review this phrase against your approved brand voice.",
        guideline: "Confident, never boastful",
        confidence: 0.78,
        status: "open",
      }],
      revisions: [],
      comments: [],
      _source: "mock",
    };
    reviews.unshift(review);
    return wait(review);
  },
  reviews: () => wait(reviews),
  review: (id) => wait(reviews.find((item) => String(item.id) === String(id)) || null),
  updateStatus: async (id, status) => {
    const item = reviews.find((review) => String(review.id) === String(id));
    if (item) item.status = status;
    return wait(item);
  },
  addComment: async (id, comment) => {
    const item = reviews.find((review) => String(review.id) === String(id));
    if (!item) throw new Error("Review not found");
    const entry = { id: `c-${Date.now()}`, comment, created_at: new Date().toISOString(), author: "You" };
    item.comments = [...(item.comments || []), entry];
    return wait(entry);
  },
  addRevision: async (id, revision) => {
    const item = reviews.find((review) => String(review.id) === String(id));
    if (!item) throw new Error("Review not found");
    const entry = { id: `rev-${Date.now()}`, ...revision, created_at: new Date().toISOString() };
    item.revisions = [...(item.revisions || []), entry];
    if (revision.content) item.content = revision.content;
    return wait(entry);
  },
  reviewActivity: () => wait([]),
  analytics: () => wait({
    total_reviews: 24,
    total_issues: 63,
    pending_approvals: 5,
    issues_by_severity: { high: 12, medium: 31, low: 20 },
    issues_by_category: [{ category: "Tone of voice", count: 24 }, { category: "Claims", count: 18 }, { category: "Terminology", count: 13 }, { category: "Accessibility", count: 8 }],
    status_distribution: [{ status: "approved", count: 15 }, { status: "in_review", count: 5 }, { status: "changes_requested", count: 4 }],
    frequent_guidelines: [{ name: "Confident, never boastful", count: 16 }, { name: "Substantiated claims", count: 12 }, { name: "Product vocabulary", count: 9 }],
  }),
  blindSpots: () => wait([{ guideline: "Inclusive language", ambiguity_score: 0.72, mentions: 8 }, { guideline: "Sustainability claims", ambiguity_score: 0.58, mentions: 5 }]),
};
