// Mirrors backend/app/models.py — kept hand-written rather than generated so
// the frontend stays free of a codegen toolchain. Update both sides together.

export type Risk = "low" | "medium" | "high";
export type Region = "EU" | "USA" | "Other" | "Unknown";
export type CookieCategory =
  | "necessary"
  | "functional"
  | "analytics"
  | "marketing"
  | "unknown";
export type StorageKind = "local" | "session";
export type Severity = "low" | "medium" | "high";
export type FormPurpose = "collection" | "search" | "authentication" | "unknown";
export type RiskRating = "low" | "medium" | "high" | "critical";
export type RecommendationPriority = "low" | "medium" | "high";

export type PolicyIssueCategory =
  | "missing_section"
  | "unclear_wording"
  | "risky_processing"
  | "third_country_transfer"
  | "missing_user_rights"
  | "missing_legal_basis"
  | "missing_retention"
  | "missing_dpo"
  | "other";

export interface FormField {
  name: string | null;
  type: string | null;
  required: boolean;
}

export interface StorageItem {
  page_url: string;
  kind: StorageKind;
  key: string;
  value_preview: string;
  value_length: number;
}

export interface FormInfo {
  action: string | null;
  method: string;
  fields: FormField[];
  page_url: string;
  text_content: string;
  links: string[];
  has_checkbox: boolean;
}

export interface PageInfo {
  url: string;
  title: string | null;
  status: number | null;
  depth: number;
  scripts: string[];
  links: string[];
  forms: FormInfo[];
  storage: StorageItem[];
  is_privacy_policy: boolean;
}

export interface NetworkRequest {
  url: string;
  domain: string;
  registered_domain: string;
  method: string;
  resource_type: string | null;
  status: number | null;
  initiator_page: string;
  is_third_party: boolean;
}

export interface DataFlowEntry {
  domain: string;
  country: Region;
  request_count: number;
  categories: string[];
  risk: Risk;
}

export interface CrawlResult {
  start_url: string;
  pages: PageInfo[];
  privacy_policy_url: string | null;
}

export interface NetworkResult {
  requests: NetworkRequest[];
  data_flow: DataFlowEntry[];
}

export interface CookieEntry {
  name: string;
  domain: string;
  path: string;
  value_preview: string;
  value_length: number;
  expires: number | null;
  secure: boolean;
  http_only: boolean;
  same_site: string | null;
  is_third_party: boolean;
  is_session: boolean;
  category: CookieCategory;
  vendor: string | null;
  reason: string;
}

export interface StorageEntry {
  page_url: string;
  kind: StorageKind;
  key: string;
  value_preview: string;
  value_length: number;
  category: CookieCategory;
  vendor: string | null;
  reason: string;
}

export interface CookieReport {
  cookies: CookieEntry[];
  storage: StorageEntry[];
  summary: Record<string, number>;
}

export interface PolicyIssue {
  category: PolicyIssueCategory;
  severity: Severity;
  description: string;
  excerpt: string | null;
  suggested_text: string | null;
}

export interface PolicyTopicCoverage {
  legal_basis_stated: boolean;
  data_categories_listed: boolean;
  retention_period_stated: boolean;
  third_party_recipients_listed: boolean;
  third_country_transfers_disclosed: boolean;
  user_rights_enumerated: boolean;
  contact_for_data_protection: boolean;
  cookie_section_present: boolean;
  children_data_addressed: boolean;
}

export interface PrivacyAnalysis {
  provider: string;
  model: string | null;
  policy_url: string | null;
  summary: string;
  issues: PolicyIssue[];
  coverage: PolicyTopicCoverage | null;
  compliance_score: number;
  excerpt_chars_sent: number;
  error: string | null;
}

export interface FormFinding {
  page_url: string;
  form_action: string | null;
  method: string;
  purpose: FormPurpose;
  collected_data: string[];
  field_count: number;
  has_consent_checkbox: boolean;
  has_privacy_link: boolean;
  legal_text_excerpt: string | null;
  issues: string[];
}

export interface FormReport {
  forms: FormFinding[];
  summary: Record<string, number>;
}

export interface SubScore {
  name: string;
  score: number;
  weight: number;
  weighted_contribution: number;
  notes: string[];
}

export interface HardCap {
  code: string;
  description: string;
  cap_value: number;
}

export interface Recommendation {
  priority: RecommendationPriority;
  title: string;
  detail: string;
  related: string[];
}

export interface RiskScore {
  score: number;
  rating: RiskRating;
  weighted_score: number;
  sub_scores: SubScore[];
  applied_caps: HardCap[];
  recommendations: Recommendation[];
}

export interface ConsentDiff {
  new_cookies: CookieEntry[];
  new_storage: StorageEntry[];
  new_data_flow: DataFlowEntry[];
  extra_request_count: number;
  new_marketing_count: number;
  new_analytics_count: number;
}

export interface ConsentSimulation {
  enabled: boolean;
  accept_clicked: boolean;
  cmp_detected: string | null;
  note: string;
  pre_summary: Record<string, number>;
  post_summary: Record<string, number>;
  diff: ConsentDiff | null;
}

export interface ScanResponse {
  target: string;
  risk: RiskScore;
  crawl: CrawlResult;
  network: NetworkResult;
  cookies: CookieReport;
  privacy_analysis: PrivacyAnalysis;
  forms: FormReport;
  consent?: ConsentSimulation | null;
  id?: string | null;
  created_at?: string | null;
}

export interface ScanRequest {
  url: string;
  max_depth?: number;
  max_pages?: number;
  consent_simulation?: boolean;
  privacy_policy_url?: string;
}

// --- Streaming + history ---------------------------------------------------

export type ProgressStage =
  | "started"
  | "crawling"
  | "cookie_analysis"
  | "policy_extraction"
  | "ai_analysis"
  | "form_analysis"
  | "scoring"
  | "done"
  | "error";

export interface ProgressEvent {
  stage: ProgressStage;
  message: string;
  data: Record<string, unknown>;
  ts: number;
}

export interface ScanListItem {
  id: string;
  url: string;
  score: number;
  rating: RiskRating;
  created_at: string;
}
