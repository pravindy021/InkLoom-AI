export const VISUAL_BRAND_GROUPS = ["primary", "secondary", "accent"];
export const MAX_COLORS_PER_GROUP = 10;
export const MAX_PALETTE_COLORS = 20;

export function normalizeHexColor(color) {
  if (typeof color !== "string" || !/^#[0-9A-Fa-f]{6}$/.test(color)) {
    return null;
  }
  return color.toUpperCase();
}

export function validateVisualBrandPalette(palette) {
  const errors = {};
  const colors = [];

  for (const group of VISUAL_BRAND_GROUPS) {
    const values = palette?.[group];
    if (!Array.isArray(values)) {
      errors[group] = "Enter a list of HEX colors.";
      continue;
    }
    if (values.length > MAX_COLORS_PER_GROUP) {
      errors[group] = `Use no more than ${MAX_COLORS_PER_GROUP} colors in this group.`;
      continue;
    }
    for (const value of values) {
      if (!normalizeHexColor(value)) {
        errors[group] = "Use six-digit HEX colors such as #123ABC.";
        break;
      }
      colors.push(normalizeHexColor(value));
    }
  }

  if (colors.length > MAX_PALETTE_COLORS) {
    errors.total = `Use no more than ${MAX_PALETTE_COLORS} colors across the palette.`;
  }
  if (new Set(colors).size !== colors.length) {
    errors.duplicates = "A color can only appear once across all groups.";
  }

  return { valid: Object.keys(errors).length === 0, errors };
}

export function normalizeVisualBrandPalette(palette) {
  return Object.fromEntries(
    VISUAL_BRAND_GROUPS.map((group) => [
      group,
      (palette?.[group] || []).map(normalizeHexColor),
    ]),
  );
}

export function canManageVisualBrandPalette(role) {
  return role === "admin";
}

export async function loadVisualBrandData(apiClient) {
  const [palette, versions] = await Promise.all([
    apiClient.visualBrandPalette(),
    apiClient.visualBrandPaletteVersions(),
  ]);
  return {
    palette: normalizeVisualBrandPalette(palette),
    metadata: palette,
    versions: Array.isArray(versions)
      ? [...versions].sort(
        (left, right) => right.version_number - left.version_number,
      )
      : [],
  };
}
