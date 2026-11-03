import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, Palette, Plus, Save, Trash2 } from "lucide-react";

import {
  ErrorMessage,
  LoadingState,
  PageHeader,
  SuccessMessage,
} from "../components/common/UI";
import { useAuth } from "../contexts/AuthContext";
import { api, errorMessage, MOCK_MODE } from "../services/api";
import {
  canManageVisualBrandPalette,
  loadVisualBrandData,
  normalizeHexColor,
  validateVisualBrandPalette,
  VISUAL_BRAND_GROUPS,
} from "../utils/visualBrandPalette";

const EMPTY_PALETTE = {
  primary: [],
  secondary: [],
  accent: [],
};

const GROUP_LABELS = {
  primary: "Primary",
  secondary: "Secondary",
  accent: "Accent",
};

export default function VisualBrandPalettePage() {
  const { user } = useAuth();
  const isAdmin = canManageVisualBrandPalette(user?.role);
  const [palette, setPalette] = useState(EMPTY_PALETTE);
  const [savedPalette, setSavedPalette] = useState(EMPTY_PALETTE);
  const [metadata, setMetadata] = useState(null);
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await loadVisualBrandData(api);
      setPalette(result.palette);
      setSavedPalette(result.palette);
      setMetadata(result.metadata);
      setVersions(result.versions);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const updateColor = (group, index, value) => {
    setPalette((current) => ({
      ...current,
      [group]: current[group].map((color, colorIndex) =>
        colorIndex === index ? value : color,
      ),
    }));
    setNotice("");
  };

  const addColor = (group) => {
    setPalette((current) => ({
      ...current,
      [group]: [...current[group], "#000000"],
    }));
    setNotice("");
  };

  const removeColor = (group, index) => {
    setPalette((current) => ({
      ...current,
      [group]: current[group].filter((_color, colorIndex) => colorIndex !== index),
    }));
    setNotice("");
  };

  const save = async (event) => {
    event.preventDefault();
    const validation = validateVisualBrandPalette(palette);
    if (!validation.valid) {
      setError(Object.values(validation.errors).join(" "));
      setNotice("");
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const normalized = Object.fromEntries(
        VISUAL_BRAND_GROUPS.map((group) => [
          group,
          palette[group].map(normalizeHexColor),
        ]),
      );
      const updated = await api.updateVisualBrandPalette(normalized);
      const result = await loadVisualBrandData(api);
      setPalette(result.palette);
      setSavedPalette(result.palette);
      setMetadata(updated);
      setVersions(result.versions);
      setNotice("Visual brand palette saved.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const hasChanges = JSON.stringify(palette) !== JSON.stringify(savedPalette);
  const paletteErrors = validateVisualBrandPalette(palette);

  return (
    <>
      <PageHeader
        eyebrow="Brand resources"
        title="Visual brand palette"
        description="Manage approved primary, secondary, and accent colors used by advisory visual checks."
      />
      {MOCK_MODE && (
        <p className="mb-5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          Demo mode: palette changes are stored only in this browser session.
        </p>
      )}
      {error && <div className="mb-4"><ErrorMessage>{error}</ErrorMessage></div>}
      {notice && <div className="mb-4"><SuccessMessage>{notice}</SuccessMessage></div>}

      {loading ? (
        <div className="card"><LoadingState label="Loading visual brand palette..." /></div>
      ) : error && !metadata ? (
        <div className="space-y-4">
          <button type="button" className="btn-secondary" onClick={load}>
            Try again
          </button>
        </div>
      ) : (
        <>
          <form onSubmit={save} className="card p-5 sm:p-6">
            <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="rounded-lg bg-ink-50 p-2 text-ink-700">
                  <Palette size={19} />
                </span>
                <div>
                  <h2 className="font-semibold text-ink-900">Approved color groups</h2>
                  <p className="mt-1 text-xs text-slate-500">
                    Six-digit HEX · maximum 10 colors per group and 20 total
                  </p>
                </div>
              </div>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
                Version {metadata?.version_number ?? 0}
              </span>
            </div>

            <p className="mb-5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
              Color comparison uses dominant image colors and approximate RGB distance. It is advisory and does not prove brand compliance or identify logo elements.
            </p>

            <div className="grid gap-4 lg:grid-cols-3">
              {VISUAL_BRAND_GROUPS.map((group) => (
                <section key={group} className="rounded-xl border border-slate-200 p-4">
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold text-slate-800">
                      {GROUP_LABELS[group]}
                    </h3>
                    <button
                      type="button"
                      className="btn-secondary !px-2.5 !py-1.5 !text-xs"
                      onClick={() => addColor(group)}
                      disabled={!isAdmin || palette[group].length >= 10}
                    >
                      <Plus size={14} /> Add color
                    </button>
                  </div>
                  {palette[group].length ? (
                    <div className="space-y-3">
                      {palette[group].map((color, index) => {
                        const normalized = normalizeHexColor(color);
                        return (
                          <div key={`${group}-${index}`} className="flex items-center gap-2">
                            <input
                              aria-label={`${GROUP_LABELS[group]} color preview ${index + 1}`}
                              type="color"
                              className="h-10 w-12 cursor-pointer rounded border border-slate-200 bg-white p-1"
                              value={normalized || "#000000"}
                              onChange={(event) =>
                                updateColor(group, index, event.target.value.toUpperCase())
                              }
                              disabled={!isAdmin}
                            />
                            <input
                              aria-label={`${GROUP_LABELS[group]} HEX color ${index + 1}`}
                              className="field min-w-0"
                              value={color}
                              maxLength={7}
                              onChange={(event) => updateColor(group, index, event.target.value)}
                              placeholder="#123ABC"
                              disabled={!isAdmin}
                            />
                            {isAdmin && (
                              <button
                                type="button"
                                className="rounded-lg p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-700"
                                aria-label={`Remove ${GROUP_LABELS[group]} color ${index + 1}`}
                                onClick={() => removeColor(group, index)}
                              >
                                <Trash2 size={16} />
                              </button>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="rounded-lg bg-slate-50 p-3 text-xs text-slate-500">
                      No {group} colors configured.
                    </p>
                  )}
                  {paletteErrors.errors[group] && (
                    <p className="mt-2 text-xs text-rose-700" role="alert">
                      {paletteErrors.errors[group]}
                    </p>
                  )}
                </section>
              ))}
            </div>

            {paletteErrors.errors.duplicates && (
              <p className="mt-3 text-sm text-rose-700" role="alert">
                {paletteErrors.errors.duplicates}
              </p>
            )}
            {paletteErrors.errors.total && (
              <p className="mt-3 text-sm text-rose-700" role="alert">
                {paletteErrors.errors.total}
              </p>
            )}

            {isAdmin && (
              <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4">
                <button
                  type="submit"
                  className="btn-primary"
                  disabled={saving || !hasChanges || !paletteErrors.valid}
                >
                  {saving ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}
                  {saving ? "Saving..." : "Save palette"}
                </button>
                <span className="text-xs text-slate-500" aria-live="polite">
                  {metadata?.updated_by
                    ? `Last updated by ${metadata.updated_by}`
                    : "No palette has been saved yet"}
                  {metadata?.updated_at
                    ? ` · ${new Date(metadata.updated_at).toLocaleString()}`
                    : ""}
                </span>
              </div>
            )}
          </form>

          <section className="card mt-5 p-5">
            <div className="mb-4">
              <h2 className="font-semibold text-ink-900">Palette version history</h2>
              <p className="mt-1 text-xs text-slate-500">
                Previous saved palettes, newest first.
              </p>
            </div>
            {versions.length ? (
              <ol className="divide-y divide-slate-100">
                {versions.map((version) => (
                  <li
                    key={`${version.version_number}-${version.id}`}
                    className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div>
                      <p className="text-sm font-medium text-slate-800">
                        Version {version.version_number}
                        <span className="font-normal text-slate-500">
                          {" "}· {version.editor || "Former Admin"}
                        </span>
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {version.created_at
                          ? new Date(version.created_at).toLocaleString()
                          : "Date unavailable"}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {VISUAL_BRAND_GROUPS.flatMap((group) =>
                        (version.snapshot?.[group] || []).map((color) => (
                          <span
                            key={`${group}-${color}`}
                            className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 px-2 py-1 text-xs text-slate-600"
                            title={GROUP_LABELS[group]}
                          >
                            <span
                              className="h-3 w-3 rounded-full border border-black/10"
                              style={{ backgroundColor: color }}
                            />
                            {GROUP_LABELS[group]} {color}
                          </span>
                        )),
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">
                No palette versions have been saved yet.
              </p>
            )}
          </section>
        </>
      )}
    </>
  );
}
