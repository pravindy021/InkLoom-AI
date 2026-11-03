import { useCallback, useEffect, useState } from "react";
import { Download, LoaderCircle } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, errorMessage, unwrapList } from "../services/api";
import {
  Badge,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
} from "../components/common/UI";
import { saveDownload } from "../utils/saveDownload";
import { getGovernanceInsightsState } from "../utils/governanceInsights";

const COLORS = ["#665bb8", "#9188d4", "#b8b3e8", "#d8d6f3", "#b8c7da"];

const toChartRows = (value, keyName) => {
  if (Array.isArray(value)) {
    return value.map((item) => ({
      name:
        item[keyName] ||
        item.category ||
        item.status ||
        item.name ||
        "Other",
      value: item.count ?? item.total ?? item.value ?? 0,
    }));
  }
  if (value && typeof value === "object") {
    return Object.entries(value).map(([name, count]) => ({
      name: name.replaceAll("_", " "),
      value: Number(count) || 0,
    }));
  }
  return [];
};

function dateRangeFor(period, customRange) {
  if (period === "custom") {
    return customRange;
  }
  if (period === "all") return { startDate: "", endDate: "" };
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - Number(period) + 1);
  const toDate = (value) => {
    const localDate = new Date(
      value.getTime() - value.getTimezoneOffset() * 60_000,
    );
    return localDate.toISOString().slice(0, 10);
  };
  return { startDate: toDate(start), endDate: toDate(end) };
}

function ChartCard({ title, description, children }) {
  return (
    <section className="card p-5">
      <h2 className="font-semibold text-ink-900">{title}</h2>
      {description && (
        <p className="mt-1 text-xs text-slate-500">{description}</p>
      )}
      {children}
    </section>
  );
}

function Metric({ label, value, caption }) {
  return (
    <div className="card p-5">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-2 text-3xl font-bold text-ink-900">{value ?? "—"}</p>
      {caption && <p className="mt-1 text-xs text-slate-400">{caption}</p>}
    </div>
  );
}

function ActivityList({ entries }) {
  return entries.length ? (
    <div className="mt-4 space-y-3">
      {entries.map((entry) => (
        <div
          className="flex items-center justify-between gap-3 text-sm"
          key={entry.reviewer}
        >
          <span className="truncate font-medium text-slate-700">
            {entry.reviewer}
          </span>
          <Badge>{`${entry.decisions} decisions`}</Badge>
        </div>
      ))}
    </div>
  ) : (
    <EmptyState
      title="No reviewer activity"
      description="Recorded review decisions will appear here."
    />
  );
}

export default function AnalyticsPage() {
  const [period, setPeriod] = useState("30");
  const [customStartDate, setCustomStartDate] = useState("");
  const [customEndDate, setCustomEndDate] = useState("");
  const [data, setData] = useState(null);
  const [blindSpots, setBlindSpots] = useState([]);
  const [governanceInsights, setGovernanceInsights] = useState(null);
  const [governanceError, setGovernanceError] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [exportError, setExportError] = useState("");
  const [exportNotice, setExportNotice] = useState("");
  const [exporting, setExporting] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    const { startDate, endDate } = dateRangeFor(period, {
      startDate: customStartDate,
      endDate: customEndDate,
    });
    try {
      const [summary, blind] = await Promise.all([
        api.analytics(startDate, endDate),
        api.blindSpots(startDate, endDate),
      ]);
      setData(summary?.data || summary);
      setBlindSpots(unwrapList(blind?.data || blind));
      try {
        const insights = await api.governanceInsights(startDate, endDate);
        setGovernanceInsights(insights?.data || insights);
        setGovernanceError("");
      } catch (insightError) {
        setGovernanceInsights(null);
        setGovernanceError(errorMessage(insightError));
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [period, customStartDate, customEndDate]);

  useEffect(() => {
    load();
  }, [load]);

  const exportReport = async (format) => {
    const { startDate, endDate } = dateRangeFor(period, {
      startDate: customStartDate,
      endDate: customEndDate,
    });
    if (startDate && endDate && startDate > endDate) {
      setExportError("The start date must be on or before the end date.");
      setExportNotice("");
      return;
    }
    setExporting(format);
    setExportError("");
    setExportNotice("");
    try {
      saveDownload(
        await api.downloadAnalyticsReport(format, startDate, endDate),
      );
      setExportNotice(
        format === "csv" ? "Analytics CSV exported." : "Analytics PDF downloaded.",
      );
    } catch (err) {
      setExportError(errorMessage(err));
    } finally {
      setExporting("");
    }
  };

  const severity = toChartRows(data?.issues_by_severity, "severity");
  const categories = toChartRows(
    data?.issues_by_category || data?.issues_by_category_count,
    "category",
  );
  const statuses = toChartRows(
    data?.status_distribution || data?.reviews_by_status,
    "status",
  );
  const claimStatuses = toChartRows(data?.claim_verification_statuses);
  const frequent = unwrapList(
    data?.frequent_guidelines || data?.most_triggered_guidelines,
  );
  const governanceState = getGovernanceInsightsState({
    insights: governanceInsights,
    error: governanceError,
    loading,
  });

  return (
    <>
      <PageHeader
        eyebrow="Insights"
        title="Analytics"
        description="Understand review patterns and identify where your brand standards need clarity."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-sm text-slate-600">
              Date range
              <select
                className="input min-w-36"
                onChange={(event) => setPeriod(event.target.value)}
                value={period}
              >
                <option value="7">Last 7 days</option>
                <option value="30">Last 30 days</option>
                <option value="90">Last 90 days</option>
                <option value="all">All time</option>
                <option value="custom">Custom</option>
              </select>
            </label>
            <button
              className="btn-secondary"
              type="button"
              disabled={Boolean(exporting)}
              onClick={() => exportReport("pdf")}
            >
              {exporting === "pdf" ? (
                <LoaderCircle className="animate-spin" size={16} />
              ) : (
                <Download size={16} />
              )}
              Download PDF Report
            </button>
            <button
              className="btn-secondary"
              type="button"
              disabled={Boolean(exporting)}
              onClick={() => exportReport("csv")}
            >
              {exporting === "csv" ? (
                <LoaderCircle className="animate-spin" size={16} />
              ) : (
                <Download size={16} />
              )}
              Export CSV
            </button>
          </div>
        }
      />
      {period === "custom" && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <label className="text-sm text-slate-600">
            Start date
            <input
              className="input ml-2"
              type="date"
              value={customStartDate}
              onChange={(event) => setCustomStartDate(event.target.value)}
            />
          </label>
          <label className="text-sm text-slate-600">
            End date
            <input
              className="input ml-2"
              type="date"
              value={customEndDate}
              onChange={(event) => setCustomEndDate(event.target.value)}
            />
          </label>
        </div>
      )}
      {exportError && (
        <div className="mb-4">
          <p className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {exportError}
          </p>
        </div>
      )}
      {exportNotice && (
        <p className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {exportNotice}
        </p>
      )}
      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : loading ? (
        <LoadingState label="Loading analytics..." />
      ) : !data ? (
        <EmptyState
          title="Analytics unavailable"
          description="The API did not return summary data."
        />
      ) : (
        <>
          <p className="mb-4 text-xs text-slate-500">
            Reporting period: {data.date_range?.start_date || "all available"} to{" "}
            {data.date_range?.end_date || "latest"} · Reviews are selected by creation date; trends use UTC calendar months.
          </p>
          <div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Metric
              label="Total reviews"
              value={data.total_reviews ?? data.review_count}
            />
            <Metric
              label="Detected issues"
              value={data.total_issues ?? data.issue_count}
            />
            <Metric
              label="Pending approvals"
              value={data.pending_approvals ?? data.pending_count}
            />
            <Metric
              label="Average review time"
              value={
                data.average_review_time_hours == null
                  ? "—"
                  : `${data.average_review_time_hours}h`
              }
              caption={`${data.completed_reviews_with_duration || 0} completed reviews`}
            />
          </div>
          <div className="mb-5 grid gap-5 xl:grid-cols-2">
            <ChartCard
              title="Issues by severity"
              description="Number of findings at each severity level"
            >
              {severity.length ? (
                <div className="mt-4 h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={severity}
                      margin={{ top: 8, right: 8, left: -20, bottom: 0 }}
                    >
                      <CartesianGrid
                        strokeDasharray="3 3"
                        vertical={false}
                        stroke="#eef0f5"
                      />
                      <XAxis
                        dataKey="name"
                        tickLine={false}
                        axisLine={false}
                        tick={{ fontSize: 12, fill: "#788096" }}
                      />
                      <YAxis
                        allowDecimals={false}
                        tickLine={false}
                        axisLine={false}
                        tick={{ fontSize: 11, fill: "#9aa0ae" }}
                      />
                      <Tooltip />
                      <Bar
                        dataKey="value"
                        name="Issues"
                        fill="#665bb8"
                        radius={[5, 5, 0, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <EmptyState
                  title="No severity data"
                  description="Severity totals will appear when findings are recorded."
                />
              )}
            </ChartCard>
            <ChartCard
              title="Issue categories"
              description="What brand standards are being triggered"
            >
              {categories.length ? (
                <div className="mt-4 h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={categories}
                      layout="vertical"
                      margin={{ top: 0, right: 15, left: 25, bottom: 0 }}
                    >
                      <CartesianGrid
                        strokeDasharray="3 3"
                        horizontal={false}
                        stroke="#eef0f5"
                      />
                      <XAxis
                        type="number"
                        allowDecimals={false}
                        tickLine={false}
                        axisLine={false}
                        tick={{ fontSize: 11, fill: "#9aa0ae" }}
                      />
                      <YAxis
                        type="category"
                        dataKey="name"
                        width={115}
                        tickLine={false}
                        axisLine={false}
                        tick={{ fontSize: 11, fill: "#788096" }}
                      />
                      <Tooltip />
                      <Bar
                        dataKey="value"
                        name="Findings"
                        fill="#8b81d0"
                        radius={[0, 5, 5, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <EmptyState
                  title="No category data"
                  description="Category totals have not been supplied."
                />
              )}
            </ChartCard>
            <ChartCard
              title="Review status"
              description="Distribution of human review decisions"
            >
              {statuses.length ? (
                <div className="flex h-64 items-center">
                  <ResponsiveContainer width="60%" height="100%">
                    <PieChart>
                      <Pie
                        data={statuses}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={55}
                        outerRadius={90}
                        paddingAngle={3}
                      >
                        {statuses.map((entry, index) => (
                          <Cell
                            key={entry.name}
                            fill={COLORS[index % COLORS.length]}
                          />
                        ))}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="space-y-3">
                    {statuses.map((entry, index) => (
                      <div
                        className="flex items-center gap-2 text-sm text-slate-600"
                        key={entry.name}
                      >
                        <span
                          className="h-2.5 w-2.5 rounded-full"
                          style={{
                            backgroundColor: COLORS[index % COLORS.length],
                          }}
                        />
                        {entry.name}
                        <strong className="ml-auto text-slate-800">
                          {entry.value}
                        </strong>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <EmptyState
                  title="No status data"
                  description="Review status distribution was not returned."
                />
              )}
            </ChartCard>
            <ChartCard
              title="Claim verification"
              description="Evidence assessments are advisory and do not replace human verification."
            >
              {claimStatuses.length ? (
                <div className="mt-4 space-y-3">
                  {claimStatuses.map((entry) => (
                    <div
                      className="flex items-center justify-between text-sm"
                      key={entry.name}
                    >
                      <span className="capitalize text-slate-600">
                        {entry.name}
                      </span>
                      <strong className="text-slate-800">{entry.value}</strong>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState
                  title="No claim assessments"
                  description="Claim evidence assessments appear after content analysis."
                />
              )}
            </ChartCard>
            <ChartCard
              title="Reviewer activity"
              description="Review decisions recorded in this date range"
            >
              <ActivityList entries={data.reviewer_activity || []} />
            </ChartCard>
            <ChartCard
              title="Frequently triggered guidelines"
              description="Rules that could benefit from clearer examples"
            >
              {frequent.length ? (
                <div className="mt-4 space-y-4">
                  {frequent.map((entry, index) => {
                    const value = entry.count ?? entry.issue_count ?? 0;
                    const max = Math.max(
                      ...frequent.map(
                        (item) => item.count ?? item.issue_count ?? 1,
                      ),
                    );
                    return (
                      <div key={entry.id || entry.name || index}>
                        <div className="mb-2 flex justify-between gap-2 text-sm">
                          <span className="font-medium text-slate-700">
                            {entry.name || entry.guideline || "Guideline"}
                          </span>
                          <span className="text-slate-400">{value}</span>
                        </div>
                        <div className="h-2 rounded-full bg-slate-100">
                          <div
                            className="h-2 rounded-full bg-ink-500"
                            style={{
                              width: `${Math.max(3, (value / max) * 100)}%`,
                            }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <EmptyState
                  title="No guideline trend data"
                  description="Frequently triggered rules will appear when available."
                />
              )}
            </ChartCard>
          </div>
          <div className="mb-5 grid gap-5 xl:grid-cols-2">
            <ChartCard
              title="Recurring issue patterns"
              description="Unique finding records after exact duplicate suppression. Recurrence requires at least two separate reviews."
            >
              {governanceState === "error" ? (
                <p className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800" role="alert">
                  Governance insights could not be loaded: {governanceError}
                </p>
              ) : governanceInsights?.recurring_categories?.length ? (
                <div className="mt-4 space-y-3">
                  {governanceInsights.recurring_categories.map((item) => (
                    <div
                      className="flex items-center justify-between gap-3 text-sm"
                      key={item.category}
                    >
                      <span className="capitalize text-slate-700">
                        {item.category.replaceAll("_", " ")}
                      </span>
                      <span className="shrink-0 text-slate-500">
                        {item.finding_count} findings · {item.review_count} reviews
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState
                  title="Not enough recurrence data"
                  description="A category appears here after it is flagged in at least two distinct reviews."
                />
              )}
              {governanceInsights?.issue_counts && (
                <p className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-500">
                  {governanceInsights.issue_counts.unique_findings} unique findings
                  {governanceInsights.issue_counts.duplicate_finding_records_ignored
                    ? ` · ${governanceInsights.issue_counts.duplicate_finding_records_ignored} exact duplicates ignored`
                    : ""}
                  {" · "}
                  {governanceInsights.issue_counts.resolved} explicitly resolved ·{" "}
                  {governanceInsights.issue_counts.unresolved} open or pending
                  {governanceInsights.issue_counts.status_unknown
                    ? ` · ${governanceInsights.issue_counts.status_unknown} status unknown`
                    : ""}
                </p>
              )}
            </ChartCard>

            <ChartCard
              title="Governance recommendations"
              description="Evidence-based prompts for human follow-up, not automated judgments of guideline quality."
            >
              {governanceState === "error" ? (
                <p className="mt-4 text-sm text-slate-500">
                  Recommendations are unavailable because governance insights failed to load.
                </p>
              ) : governanceInsights?.recommendations?.length ? (
                <ul className="mt-4 space-y-3">
                  {governanceInsights.recommendations.map((item, index) => (
                    <li
                      className="rounded-lg border border-slate-200 bg-slate-50 p-3"
                      key={`${item.type}-${item.evidence?.guideline_id || item.evidence?.category || index}`}
                    >
                      <p className="text-sm font-semibold text-slate-800">
                        {item.title}
                      </p>
                      <p className="mt-1 text-sm leading-5 text-slate-600">
                        {item.message}
                      </p>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState
                  title="No action recommendations yet"
                  description="Recommendations appear when a category or guideline recurs across multiple reviews."
                />
              )}
              {governanceInsights?.review_outcomes && (
                <p className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-500">
                  {governanceInsights.review_outcomes.changes_requested_events} review-level changes-requested events ·{" "}
                  {governanceInsights.review_outcomes.approved_events} approvals. These audit events are not attributable to a particular finding or guideline.
                </p>
              )}
            </ChartCard>

            <ChartCard
              title="Review trend"
              description="Reviews and unique findings by review creation month; months without records are omitted."
            >
              {governanceInsights?.trends_by_month?.length ? (
                <div className="mt-4 h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={governanceInsights.trends_by_month}>
                      <CartesianGrid
                        strokeDasharray="3 3"
                        vertical={false}
                        stroke="#eef0f5"
                      />
                      <XAxis dataKey="month" tickLine={false} axisLine={false} />
                      <YAxis allowDecimals={false} tickLine={false} axisLine={false} />
                      <Tooltip />
                      <Bar
                        dataKey="review_count"
                        name="Reviews"
                        fill="#665bb8"
                        radius={[4, 4, 0, 0]}
                      />
                      <Bar
                        dataKey="unique_findings"
                        name="Unique findings"
                        fill="#b8b3e8"
                        radius={[4, 4, 0, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <EmptyState
                  title="No trend data"
                  description="Monthly trends require persisted review timestamps and findings."
                />
              )}
            </ChartCard>
          </div>
          <ChartCard
            title="Potentially ambiguous guidelines"
            description="Relative recurrence signals include only guidelines found in at least two distinct reviews; they do not prove unclear wording."
          >
            {blindSpots.length ? (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[480px] text-left">
                  <thead className="text-xs uppercase tracking-wide text-slate-400">
                    <tr>
                      <th className="pb-3">Guideline</th>
                      <th className="pb-3">Ambiguity indicator</th>
                      <th className="pb-3">Findings / reviews</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {blindSpots.map((item, index) => (
                      <tr key={item.id || index}>
                        <td className="py-3 text-sm font-medium text-slate-700">
                          {item.guideline || item.name || item.title}
                        </td>
                        <td className="py-3">
                          <Badge tone="severity">
                            {item.ambiguity_score ?? item.score ?? "—"}
                          </Badge>
                        </td>
                        <td className="py-3 text-sm text-slate-500">
                          {item.mentions ?? item.count ?? "—"}
                          {item.review_count != null
                            ? ` / ${item.review_count}`
                            : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState
                title="No ambiguity indicators"
                description="The API has not identified potential guideline blind spots."
              />
            )}
          </ChartCard>
        </>
      )}
    </>
  );
}
