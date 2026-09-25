// Typed client for the FastAPI backend. Same-origin by default (reverse proxy routes /api);
// set NEXT_PUBLIC_API_BASE_URL at build time when the API lives on another origin.
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");

export type Feasibility = "Feasible" | "Review Required" | "Infeasible";
export type ProcessKey = "CNC_5_Axis" | "CNC_3_Axis" | "Lathe";

export interface CostBreakdown {
  material_cost_eur: number;
  machining_cost_eur: number;
  energy_surcharge_eur: number;
  net_total_eur: number;
  vat_19_eur: number;
  gross_total_eur: number;
}

export interface EngineQuote {
  quote_id: string;
  feasibility: Feasibility;
  feasibility_notes: string;
  selected_process: ProcessKey;
  estimated_production_time_hours: number;
  cost_breakdown: CostBreakdown;
  recommended_lead_time_days: number;
}

export interface TimeBreakdown {
  setup_minutes: number;
  setups: number;
  roughing_minutes_per_part: number;
  finishing_minutes_per_part: number;
  feature_minutes_first_part: number;
  feature_minutes_series_part: number;
  cycle_minutes_first_part: number;
  total_minutes: number;
}

export interface MaterialBreakdown {
  key: string | null;
  name: string;
  density_g_cm3: number | null;
  price_eur_per_kg: number;
  basis: "part" | "stock";
  part_mass_kg: number;
  stock_mass_kg: number;
  stock_dimensions_mm: number[];
  buy_to_fly_ratio: number;
  removal_volume_cm3: number;
}

export interface Diagnostics {
  source_format: "STEP" | "IGES" | "STL" | "manual";
  solid_count: number;
  face_count: number | null;
  is_rotational: boolean | null;
  turning_diameter_mm: number | null;
  turning_length_mm: number | null;
  access_directions: string[];
  min_hole_diameter_mm: number | null;
  max_hole_depth_to_diameter: number | null;
  min_internal_radius_mm: number | null;
  freeform_area_fraction: number | null;
  closed_pockets: number | null;
  open_steps: number | null;
  thread_detection: "tap_drill_heuristic" | "user_override" | "none";
  warnings: string[];
}

export interface Supplier {
  name: string;
  street: string;
  city: string;
  country: string;
  email: string;
  phone: string;
  vat_id: string;
  commercial_register: string;
  managing_director: string;
}

export interface QuoteResponse {
  quote: EngineQuote;
  engine_input: {
    cad_metadata: {
      bounding_box: [number, number, number];
      volume_cm3: number;
      surface_area_cm2: number;
      features: { holes: number; threads: number; pockets: number; complex_curves: number };
      requested_material: string;
      diagnostics: Diagnostics | null;
    };
    factory_status: {
      machine_availability: Record<ProcessKey, boolean>;
      current_backlog_days: number;
    };
    cost_vectors: {
      material_per_kg: number;
      machine_hourly_rate: number;
      energy_surcharge_percent: number;
      target_margin_percent: number;
    };
    order: { quantity: number };
  };
  analysis: {
    engine: "claude" | "rules";
    model: string | null;
    ai_latency_ms: number | null;
    rule_based_process: ProcessKey;
    flags: string[];
    time_breakdown: TimeBreakdown | null;
    material: MaterialBreakdown | null;
    margin_eur: number;
    validation: string[];
  };
  commercial: {
    currency: "EUR";
    quantity: number;
    unit_price_net_eur: number;
    vat_rate_percent: number;
    created_at: string;
    valid_until: string;
    customer_reference: string | null;
    file_name: string | null;
    material_label: string;
    supplier: Supplier;
    terms_de: string[];
    terms_en: string[];
  };
  has_preview: boolean;
}

export interface MaterialOption {
  key: string;
  name_de: string;
  name_en: string;
  werkstoff_nr: string;
  category: string;
  density_g_cm3: number;
}

export interface Capabilities {
  machines: { process: ProcessKey; label_de: string; label_en: string; envelope_mm: number[]; available: boolean }[];
  current_backlog_days: number;
  accepted_extensions: string[];
  max_upload_mb: number;
  max_quantity: number;
  ai_enabled: boolean;
  quote_retention_days: number;
  vat_rate_percent: number;
  supplier: Supplier;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, cache: "no-store" });
  } catch {
    throw new ApiError("Der Kalkulationsdienst ist nicht erreichbar. Prüfen Sie Ihre Verbindung.", 0);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export const getMaterials = () => request<MaterialOption[]>("/api/v1/materials");
export const getCapabilities = () => request<Capabilities>("/api/v1/capabilities");
export const getQuote = (id: string) => request<QuoteResponse>(`/api/v1/quotes/${encodeURIComponent(id)}`);
export const previewUrl = (id: string) => `${API_BASE}/api/v1/quotes/${encodeURIComponent(id)}/preview.stl`;

export function createQuote(form: FormData): Promise<QuoteResponse> {
  return request<QuoteResponse>("/api/v1/quotes", { method: "POST", body: form });
}
