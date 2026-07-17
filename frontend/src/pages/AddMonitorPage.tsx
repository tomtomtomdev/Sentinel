import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { MethodChip } from "../components/MonitorCard";
import { Toast, useToast } from "../components/Toast";
import {
  ArrowLeftIcon,
  CheckIcon,
  PenIcon,
  RefreshIcon,
  TerminalIcon,
  UploadIcon,
  XIcon,
} from "../components/icons";
import { api } from "../lib/api";
import {
  createFromDraft,
  importCurl,
  importPostman,
  type MonitorDraft,
} from "../lib/imports";
import {
  ASSERTION_TYPE_OPTIONS,
  buildAssertions,
  INTERVAL_OPTIONS,
  intervalToSeconds,
  type AssertionRow,
  type IntervalValue,
} from "../lib/rules";

const EXAMPLE_CURL = `curl -X POST https://api.acme.io/v1/orders \\
  -H 'Content-Type: application/json' \\
  -H 'X-Api-Key: demo-key' \\
  -d '{"sku":"tee-xl","qty":1}'`;

type Tab = "curl" | "import" | "manual";

const TABS: { id: Tab; label: string; icon: typeof TerminalIcon }[] = [
  { id: "curl", label: "Paste cURL", icon: TerminalIcon },
  { id: "import", label: "Import collection", icon: UploadIcon },
  { id: "manual", label: "Manual setup", icon: PenIcon },
];

interface Rules {
  interval: IntervalValue;
  expectedStatus: string;
  assertions: AssertionRow[];
}

const DEFAULT_RULES: Rules = { interval: "1m", expectedStatus: "200", assertions: [] };

const FIELD =
  "snt-field rounded-[9px] border border-hairline px-3 py-[9px] text-[13.5px]";

function SecondaryButton(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...props}
      className={`flex items-center gap-[6px] rounded-[9px] border border-faint bg-white px-[14px] py-[9px] text-[13px] font-semibold hover:border-muted hover:bg-subtle ${props.className ?? ""}`}
    />
  );
}

function PrimaryButton(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...props}
      className={`rounded-[9px] bg-ink px-[14px] py-[9px] text-[13px] font-semibold text-white shadow-[0_1px_2px_rgba(0,0,0,0.12)] hover:bg-black disabled:opacity-50 ${props.className ?? ""}`}
    />
  );
}

function RemoveButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-[9px] border border-hairline text-muted hover:border-[#fecaca] hover:bg-down-bg hover:text-down"
    >
      <XIcon size={14} />
    </button>
  );
}

function MonitoringRules({
  rules,
  onChange,
  compact = false,
}: {
  rules: Rules;
  onChange: (rules: Rules) => void;
  compact?: boolean;
}) {
  const setRow = (i: number, row: AssertionRow) =>
    onChange({
      ...rules,
      assertions: rules.assertions.map((r, j) => (j === i ? row : r)),
    });
  return (
    <div>
      <h3 className="text-[15px] font-bold">Monitoring rules</h3>
      <div className="mt-3 grid grid-cols-2 gap-[14px]">
        <label className="block">
          <span className="mb-1 block text-[13px] font-semibold">
            Check interval
          </span>
          <select
            value={rules.interval}
            onChange={(e) =>
              onChange({ ...rules, interval: e.target.value as IntervalValue })
            }
            className={`${FIELD} w-full bg-white`}
          >
            {INTERVAL_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-[13px] font-semibold">
            Expected status code
          </span>
          <input
            value={rules.expectedStatus}
            onChange={(e) =>
              onChange({ ...rules, expectedStatus: e.target.value })
            }
            className={`${FIELD} w-full font-mono`}
          />
        </label>
      </div>
      {!compact && (
        <div className="mt-4">
          <span className="mb-1 block text-[13px] font-semibold">
            Response assertions
          </span>
          <div className="flex flex-col gap-2">
            {rules.assertions.map((row, i) => (
              <div key={i} className="flex gap-2">
                <select
                  aria-label="Assertion type"
                  value={row.type}
                  onChange={(e) =>
                    setRow(i, {
                      ...row,
                      type: e.target.value as AssertionRow["type"],
                    })
                  }
                  className={`${FIELD} w-[200px] bg-white`}
                >
                  {ASSERTION_TYPE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                {row.type === "json_path_equals" && (
                  <input
                    aria-label="JSON path"
                    placeholder="$.status"
                    value={row.path ?? ""}
                    onChange={(e) => setRow(i, { ...row, path: e.target.value })}
                    className={`${FIELD} flex-1 font-mono`}
                  />
                )}
                <input
                  aria-label="Expected value"
                  placeholder="Expected value"
                  value={row.value}
                  onChange={(e) => setRow(i, { ...row, value: e.target.value })}
                  className={`${FIELD} flex-1 font-mono`}
                />
                <RemoveButton
                  label="Remove assertion"
                  onClick={() =>
                    onChange({
                      ...rules,
                      assertions: rules.assertions.filter((_, j) => j !== i),
                    })
                  }
                />
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={() =>
              onChange({
                ...rules,
                assertions: [
                  ...rules.assertions,
                  { type: "body_contains", value: "" },
                ],
              })
            }
            className="mt-2 text-[12.5px] font-semibold text-accent hover:underline"
          >
            + Add assertion
          </button>
        </div>
      )}
    </div>
  );
}

/** Derive a fallback monitor name from the URL's last path segments. */
function deriveName(method: string, url: string): string {
  try {
    const path = new URL(url).pathname.split("/").filter(Boolean);
    const tail = path.slice(-2).join("/");
    return tail === "" ? `${method} ${new URL(url).hostname}` : `${method} /${tail}`;
  } catch {
    return `${method} ${url}`;
  }
}

export function AddMonitorPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { message, show } = useToast();
  const [tab, setTab] = useState<Tab>("curl");
  const [rules, setRules] = useState<Rules>(DEFAULT_RULES);

  // Paste cURL
  const [curlText, setCurlText] = useState("");
  const [draft, setDraft] = useState<MonitorDraft | null>(null);

  // Import collection
  const [importDrafts, setImportDrafts] = useState<MonitorDraft[]>([]);
  const [selected, setSelected] = useState<boolean[]>([]);
  const [importSource, setImportSource] = useState("");
  const [dragging, setDragging] = useState(false);

  // Manual setup
  const [manual, setManual] = useState({ name: "", method: "GET", url: "" });
  const [headerRows, setHeaderRows] = useState([{ k: "", v: "" }]);

  const finishCreate = async (created: { id: string }[]) => {
    await queryClient.invalidateQueries({ queryKey: ["monitors"] });
    const toast =
      created.length === 1
        ? "Monitor created — now watching"
        : `${created.length} monitors created — now watching`;
    navigate("/monitors", {
      state: { toast, newIds: created.map((c) => c.id) },
    });
  };

  const parseCurl = async () => {
    try {
      const result = await importCurl(curlText);
      setDraft(result.drafts[0] ?? null);
      if (result.drafts.length === 0) {
        show("Could not detect a request — check the cURL");
      }
    } catch {
      setDraft(null);
      show("Could not detect a request — check the cURL");
    }
  };

  const createFromCurl = async () => {
    if (draft === null) {
      return;
    }
    try {
      const created = await createFromDraft(
        draft,
        intervalToSeconds(rules.interval),
        buildAssertions(rules.expectedStatus, rules.assertions),
      );
      await finishCreate([created]);
    } catch (e) {
      show(e instanceof Error ? e.message : "Could not create the monitor");
    }
  };

  const loadCollection = async (file: File) => {
    try {
      const result = await importPostman(file);
      if (result.drafts.length === 0) {
        show("No endpoints found in that file");
        return;
      }
      setImportDrafts(result.drafts);
      setSelected(result.drafts.map(() => true));
      setImportSource(`${file.name} · ${result.drafts.length} requests`);
    } catch (e) {
      show(e instanceof Error ? e.message : "Could not read that file");
    }
  };

  const createFromImport = async () => {
    const chosen = importDrafts.filter((_, i) => selected[i]);
    try {
      const created = [];
      for (const d of chosen) {
        created.push(
          await createFromDraft(
            d,
            intervalToSeconds(rules.interval),
            buildAssertions(rules.expectedStatus, rules.assertions),
          ),
        );
      }
      await finishCreate(created);
    } catch (e) {
      show(e instanceof Error ? e.message : "Could not create the monitors");
    }
  };

  const createManual = async () => {
    const url = manual.url.trim();
    if (url === "") {
      show("Enter an endpoint URL");
      return;
    }
    const headers = Object.fromEntries(
      headerRows
        .filter((r) => r.k.trim() !== "")
        .map((r) => [r.k.trim(), r.v]),
    );
    try {
      const created = await api.post<{ id: string; name: string }>(
        "/monitors",
        {
          name: manual.name.trim() || deriveName(manual.method, url),
          method: manual.method,
          url,
          headers,
          interval_seconds: intervalToSeconds(rules.interval),
          assertions: buildAssertions(rules.expectedStatus, rules.assertions),
        },
      );
      await finishCreate([created]);
    } catch (e) {
      show(e instanceof Error ? e.message : "Could not create the monitor");
    }
  };

  const selectedCount = selected.filter(Boolean).length;

  return (
    <div className="mx-auto max-w-[740px] px-9 pb-20 pt-[30px]">
      <Link
        to="/monitors"
        className="flex w-fit items-center gap-[6px] text-[13px] font-medium text-dim hover:text-ink"
      >
        <ArrowLeftIcon size={15} />
        Back to monitors
      </Link>
      <h1 className="mt-4 text-2xl font-bold tracking-[-0.02em]">
        Add a monitor
      </h1>
      <p className="mt-2 text-sm text-dim">
        Import an existing request or set one up by hand. Sentinel starts
        watching it immediately.
      </p>

      <div
        role="tablist"
        className="mb-6 mt-6 flex gap-1 rounded-[11px] border border-edge bg-fill p-1"
      >
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={`flex flex-1 items-center justify-center gap-2 rounded-[8px] px-3 py-[9px] text-[13px] font-semibold ${
              tab === id
                ? "border border-[#e7e7ea] bg-white text-ink shadow-[0_1px_2px_rgba(0,0,0,0.05)]"
                : "text-dim"
            }`}
          >
            <Icon size={15} />
            {label}
          </button>
        ))}
      </div>

      {tab === "curl" && (
        <div>
          <div className="mb-1 flex items-center justify-between">
            <span className="text-[13px] font-semibold">cURL command</span>
            <button
              type="button"
              onClick={() => setCurlText(EXAMPLE_CURL)}
              className="text-[12.5px] font-semibold text-accent hover:underline"
            >
              Use example
            </button>
          </div>
          <textarea
            value={curlText}
            onChange={(e) => setCurlText(e.target.value)}
            placeholder="curl -X POST https://api.acme.io/v1/orders -H 'Content-Type: application/json' -d '{&quot;sku&quot;:&quot;tee-xl&quot;}'"
            className="snt-field min-h-[140px] w-full resize-y rounded-[11px] border border-hairline bg-subtle px-4 py-[14px] font-mono text-[12.5px] leading-relaxed"
          />
          <div className="mt-3">
            <SecondaryButton onClick={() => void parseCurl()}>
              <RefreshIcon size={14} />
              Parse request
            </SecondaryButton>
          </div>

          {draft !== null && (
            <section className="snt-in mt-6 rounded-xl border border-edge">
              <div className="flex items-center gap-2 rounded-t-xl bg-subtle px-4 py-2 text-[11.5px] uppercase tracking-wide text-muted">
                <CheckIcon size={13} className="text-up" />
                Detected request
              </div>
              <div className="flex flex-col gap-4 p-4">
                <div className="flex items-center gap-2">
                  <MethodChip method={draft.method} />
                  <span className="break-all font-mono text-xs text-body">
                    {draft.url}
                  </span>
                </div>
                {Object.keys(draft.headers).length > 0 && (
                  <div>
                    <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">
                      Headers
                    </div>
                    {Object.entries(draft.headers).map(([k, v]) => (
                      <div key={k} className="font-mono text-xs">
                        <span className="text-[#7c3aed]">{k}:</span>{" "}
                        <span className="text-body">{v}</span>
                      </div>
                    ))}
                  </div>
                )}
                {draft.body !== null && draft.body !== "" && (
                  <div>
                    <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">
                      Body
                    </div>
                    <pre className="whitespace-pre-wrap rounded-[8px] border border-line bg-subtle p-3 font-mono text-xs">
                      {draft.body}
                    </pre>
                  </div>
                )}
                <MonitoringRules rules={rules} onChange={setRules} />
                <div className="flex justify-end gap-2 border-t border-fill pt-4">
                  <SecondaryButton onClick={() => setDraft(null)}>
                    Cancel
                  </SecondaryButton>
                  <PrimaryButton onClick={() => void createFromCurl()}>
                    Create monitor
                  </PrimaryButton>
                </div>
              </div>
            </section>
          )}
        </div>
      )}

      {tab === "import" && (
        <div>
          {importDrafts.length === 0 ? (
            <label
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                const file = e.dataTransfer.files[0];
                if (file) {
                  void loadCollection(file);
                }
              }}
              className={`flex cursor-pointer flex-col items-center rounded-[13px] border-[1.5px] border-dashed px-6 py-9 text-center ${
                dragging
                  ? "border-accent bg-accent-wash"
                  : "border-faint bg-subtle"
              }`}
            >
              <span className="flex h-[46px] w-[46px] items-center justify-center rounded-xl bg-accent-tint text-accent">
                <UploadIcon size={20} />
              </span>
              <span className="mt-3 text-sm font-semibold">
                Drop a Postman collection here
              </span>
              <span className="mt-1 text-[12.5px] text-dim">
                or <span className="font-semibold text-accent">browse your computer</span>{" "}
                · Postman v2.1 JSON
              </span>
              <input
                data-testid="import-file-input"
                type="file"
                accept=".json,application/json"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) {
                    void loadCollection(file);
                  }
                  e.target.value = "";
                }}
              />
            </label>
          ) : (
            <div className="snt-in">
              <div className="mb-2 flex items-center justify-between">
                <span className="flex items-center gap-2 text-[13px] font-semibold">
                  <CheckIcon size={14} className="text-up" />
                  {importSource}
                </span>
                <button
                  type="button"
                  onClick={() =>
                    setSelected(selected.map(() => selectedCount === 0))
                  }
                  className="text-[12.5px] font-semibold text-accent hover:underline"
                >
                  {selectedCount === 0 ? "Select all" : "Deselect all"}
                </button>
              </div>
              <div className="max-h-[300px] overflow-y-auto rounded-xl border border-edge">
                {importDrafts.map((d, i) => (
                  <label
                    key={`${d.method} ${d.url} ${i}`}
                    className="flex cursor-pointer items-center gap-[11px] border-b border-fill px-4 py-[11px] last:border-b-0 hover:bg-subtle"
                  >
                    <input
                      type="checkbox"
                      checked={selected[i] ?? false}
                      onChange={() =>
                        setSelected(selected.map((s, j) => (j === i ? !s : s)))
                      }
                      className="h-4 w-4 accent-accent"
                    />
                    <span className="w-[52px] text-center">
                      <MethodChip method={d.method} />
                    </span>
                    <span className="max-w-[180px] truncate text-[13px] font-semibold">
                      {d.name}
                    </span>
                    <span className="min-w-0 truncate font-mono text-xs text-muted">
                      {d.url}
                    </span>
                  </label>
                ))}
              </div>
              <div className="mt-5 flex flex-col gap-4">
                <MonitoringRules rules={rules} onChange={setRules} compact />
                <div className="flex justify-end gap-2">
                  <SecondaryButton
                    onClick={() => {
                      setImportDrafts([]);
                      setSelected([]);
                    }}
                  >
                    Cancel
                  </SecondaryButton>
                  <PrimaryButton
                    disabled={selectedCount === 0}
                    onClick={() => void createFromImport()}
                  >
                    Create {selectedCount} monitor{selectedCount === 1 ? "" : "s"}
                  </PrimaryButton>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "manual" && (
        <div className="flex flex-col gap-4">
          <label className="block">
            <span className="mb-1 block text-[13px] font-semibold">
              Monitor name
            </span>
            <input
              value={manual.name}
              onChange={(e) => setManual({ ...manual, name: e.target.value })}
              placeholder="e.g. Checkout API"
              className={`${FIELD} w-full`}
            />
          </label>
          <div>
            <span className="mb-1 block text-[13px] font-semibold">Endpoint</span>
            <div className="flex gap-2">
              <select
                aria-label="Method"
                value={manual.method}
                onChange={(e) =>
                  setManual({ ...manual, method: e.target.value })
                }
                className={`${FIELD} w-[110px] bg-white font-mono font-semibold`}
              >
                {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
              <input
                value={manual.url}
                onChange={(e) => setManual({ ...manual, url: e.target.value })}
                placeholder="https://api.acme.io/v1/health"
                className={`${FIELD} min-w-0 flex-1 font-mono`}
              />
            </div>
          </div>
          <div>
            <span className="mb-1 block text-[13px] font-semibold">Headers</span>
            <div className="flex flex-col gap-2">
              {headerRows.map((row, i) => (
                <div key={i} className="flex gap-2">
                  <input
                    value={row.k}
                    onChange={(e) =>
                      setHeaderRows(
                        headerRows.map((r, j) =>
                          j === i ? { ...r, k: e.target.value } : r,
                        ),
                      )
                    }
                    placeholder="Header name"
                    className={`${FIELD} flex-1 font-mono`}
                  />
                  <input
                    value={row.v}
                    onChange={(e) =>
                      setHeaderRows(
                        headerRows.map((r, j) =>
                          j === i ? { ...r, v: e.target.value } : r,
                        ),
                      )
                    }
                    placeholder="Value"
                    className={`${FIELD} flex-[1.4] font-mono`}
                  />
                  <RemoveButton
                    label="Remove header"
                    onClick={() =>
                      setHeaderRows(
                        headerRows.length === 1
                          ? [{ k: "", v: "" }]
                          : headerRows.filter((_, j) => j !== i),
                      )
                    }
                  />
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setHeaderRows([...headerRows, { k: "", v: "" }])}
              className="mt-2 text-[12.5px] font-semibold text-accent hover:underline"
            >
              + Add header
            </button>
          </div>
          <MonitoringRules rules={rules} onChange={setRules} />
          <div className="flex justify-end gap-2 border-t border-fill pt-4">
            <SecondaryButton onClick={() => navigate("/monitors")}>
              Cancel
            </SecondaryButton>
            <PrimaryButton onClick={() => void createManual()}>
              Create monitor
            </PrimaryButton>
          </div>
        </div>
      )}

      <Toast message={message} />
    </div>
  );
}
