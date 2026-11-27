import { z } from 'zod';
export const note = z.object({ note: z.string().optional() });
export const point = {
  lat: z.coerce.number().min(-90).max(90),
  lng: z.coerce.number().min(-180).max(180),
};
export const credentials = z.object({
  email: z.email(),
  password: z.string().min(8),
});
export const registration = credentials.extend({
  name: z.string().trim().min(1),
});
export const polygon = z
  .object({
    type: z.literal('Polygon'),
    coordinates: z
      .array(
        z.array(
          z.tuple([z.number().min(-180).max(180), z.number().min(-90).max(90)]),
        ),
      )
      .min(1),
  })
  .refine(
    (g) =>
      g.coordinates.every(
        (r) =>
          r.length >= 4 &&
          JSON.stringify(r[0]) === JSON.stringify(r.at(-1)) &&
          new Set(r.slice(0, -1).map((p) => JSON.stringify(p))).size >= 3,
      ),
    'Use a closed polygon with three distinct vertices.',
  );
export const zoneInput = z.object({
  name: z.string().trim().min(1),
  description: z.string().optional(),
  geometry: polygon,
  area_m2: z.number().min(1).max(10_000_000),
  mode: z.enum(['DENSITY', 'COUNT']).optional(),
  warning_density: z.number().positive().optional(),
  critical_density: z.number().positive().optional(),
  warning_count: z.number().positive().nullable().optional(),
  critical_count: z.number().positive().nullable().optional(),
});
export const advisoryInput = z.object({
  title: z.string().trim().min(1),
  body: z.string().trim().min(1),
  severity: z.enum(['INFO', 'WARNING', 'URGENT']),
  zone_id: z.number().int().positive().nullable().optional(),
  expires_at: z.iso.datetime().nullable().optional(),
});
