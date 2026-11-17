export type Atom = {
  id: string;
  kind: string;
  patch: string;
  old_start: number;
  new_start: number;
};
export type FileRecord = {
  old_text?: string | null;
  new_text?: string | null;
  id: string;
  repo: string;
  path: string;
  old_path: string | null;
  status: string;
  old_oid: string | null;
  new_oid: string | null;
  old_mode: string | null;
  new_mode: string | null;
  atoms: Atom[];
};
export type Repo = {
  alias: string;
  path: string;
  base: string;
  target: string;
  include_untracked: boolean;
};
export type Side = { repo: string; path: string };
export type Contract = {
  id: string;
  title: string;
  producer: Side;
  consumer: Side;
  expectation: string;
};
export type Config = {
  required_checks?: string[];
  required_passes?: string[];
  title: string;
  objective: string;
  repos: Repo[];
  contracts: Contract[];
  criteria: string[];
};
export type Finding = {
  id: string;
  title: string;
  detail: string;
  blocking: boolean;
  evidence: string[];
  dismissed?: boolean;
  disposition?:
    | string
    | {
        action: string;
        reason?: string;
        time?: string;
        capture?: string;
        evidence?: string[];
      }
    | null;
};
export type Unit = {
  sides?: Record<string, {available: boolean; file_ids: string[]; contexts: {path: string; oid: string; text: string | null}[]}>;
  id: string;
  title: string;
  summary: string;
  risk: "high" | "medium" | "low";
  status: string;
  reason: string;
  atom_ids: string[];
  file_ids: string[];
  repos: string[];
  contract_id: string | null;
  findings: Finding[];
};
export type Event = {
  time: string;
  action: string;
  unit_id: string | null;
  reason: string;
  capture: string;
  finding_id?: string;
};
export type Check = {
  id?: string;
  name?: string;
  repo?: string;
  capture?: string;
  exit_code?: number;
  [key: string]: unknown;
};
export type View = {
  suggested_contracts?: (Contract & { basis?: string; evidence?: unknown[] })[];
  checks?: Check[];
  id: string;
  title: string;
  objective: string;
  config: Config;
  version: number;
  capture: string;
  created_at: string;
  repositories: {
    alias: string;
    base_sha: string;
    target_id: string;
    files: FileRecord[];
  }[];
  units: Unit[];
  counts: { files: number; atoms: number; approved: number; units: number };
  events: Event[];
};
export type Summary = { id: string; title: string; updated_at: string };
export type Verification = {
  ready: boolean;
  blockers: string[];
  capture: string;
  counts: View["counts"];
};
