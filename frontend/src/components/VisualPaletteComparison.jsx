export default function VisualPaletteComparison({ comparison }) {
  if (!Array.isArray(comparison?.colors) || !comparison.colors.length) {
    return null;
  }

  return (
    <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
      <p className="text-xs font-semibold text-slate-700">
        Dominant-color comparison
        <span className="ml-1 font-normal text-slate-500">
          (advisory RGB heuristic)
        </span>
      </p>
      <div className="mt-2 space-y-2">
        {comparison.colors.map((item, index) => {
          if (!item || typeof item !== "object") return null;
          const detectedColor =
            item.image_color || item.nearest_detected_color;
          const expectedColor = item.expected_brand_color;
          const hasDetectedColor =
            typeof detectedColor === "string" && detectedColor.length > 0;
          const hasExpectedColor =
            typeof expectedColor === "string" && expectedColor.length > 0;
          const hasDistance =
            typeof item.nearest_brand_color_distance === "number" &&
            Number.isFinite(item.nearest_brand_color_distance);

          return (
            <div
              key={`${detectedColor || "detected"}-${expectedColor || "expected"}-${index}`}
              className="flex flex-wrap items-center gap-2 text-xs text-slate-600"
            >
              {hasDetectedColor && (
                <span className="inline-flex items-center gap-1">
                  <span
                    className="h-3 w-3 rounded-full border border-black/10"
                    style={{ backgroundColor: detectedColor }}
                  />
                  Detected {detectedColor}
                </span>
              )}
              {hasDetectedColor && hasExpectedColor && (
                <span aria-hidden="true">→</span>
              )}
              {hasExpectedColor && (
                <span className="inline-flex items-center gap-1">
                  <span
                    className="h-3 w-3 rounded-full border border-black/10"
                    style={{ backgroundColor: expectedColor }}
                  />
                  {item.palette_role || "Expected"} {expectedColor}
                </span>
              )}
              {hasDistance && (
                <span>
                  Distance {item.nearest_brand_color_distance}
                  {typeof item.within_tolerance === "boolean"
                    ? item.within_tolerance
                      ? " · within tolerance"
                      : " · review"
                    : ""}
                </span>
              )}
            </div>
          );
        })}
      </div>
      {comparison.method && (
        <p className="mt-2 text-[11px] leading-5 text-slate-500">
          {comparison.method}
        </p>
      )}
    </div>
  );
}
