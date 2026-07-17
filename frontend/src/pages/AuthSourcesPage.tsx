import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Toast, useToast } from "../components/Toast";
import { PlusIcon, RefreshIcon } from "../components/icons";
import { api } from "../lib/api";
import {
  createAuthSource,
  refreshAuthSource,
  useAuthSources,
  type AuthSource,
  type TokenStatus,
} from "../lib/authSources";

const TOKEN_PILL: Record<TokenStatus, { label: string; classes: string }> = {
  valid: { label: "valid", classes: "text-up-text bg-up-bg" },
  expired: { label: "expired", classes: "text-degraded-text bg-degraded-bg" },
  error: { label: "error", classes: "text-down-text bg-down-bg" },
  none: { label: "no token", classes: "text-body bg-fill" },
};

const FIELD =
  "snt-field rounded-[9px] border border-hairline px-3 py-[9px] text-[13.5px]";

const EMPTY_FORM = {
  name: "",
  method: "POST",
  url: "",
  body: "",
  tokenPath: "$.access_token",
  expiresInPath: "",
  headerName: "Authorization",
};

function TokenPill({ status }: { status: TokenStatus }) {
  const pill = TOKEN_PILL[status];
  return (
    <span
      className={`rounded-[20px] px-[9px] py-[3px] text-[11px] font-semibold ${pill.classes}`}
    >
      {pill.label}
    </span>
  );
}

function SourceRow({
  source,
  onToast,
}: {
  source: AuthSource;
  onToast: (msg: string) => void;
}) {
  const queryClient = useQueryClient();
  const state = source.token_state;
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["auth-sources"] });

  const refresh = async () => {
    try {
      const result = await refreshAuthSource(source.id);
      await invalidate();
      onToast(
        result.status === "valid"
          ? "Token refreshed"
          : `Refresh failed — token is ${result.status}`,
      );
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Refresh failed");
    }
  };

  const toggle = async () => {
    try {
      await api.patch(`/auth-sources/${source.id}`, {
        enabled: !source.enabled,
      });
      await invalidate();
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Could not update the source");
    }
  };

  const remove = async () => {
    try {
      await api.delete(`/auth-sources/${source.id}`);
      await invalidate();
      onToast("Auth source deleted");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Could not delete the source");
    }
  };

  return (
    <li className="flex flex-wrap items-center gap-3 border-b border-fill px-4 py-3 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[13.5px] font-semibold">
            {source.name}
          </span>
          <span className="rounded-[5px] bg-fill px-[6px] py-[2px] font-mono text-[10.5px] font-semibold text-body">
            {source.mode}
          </span>
          {!source.enabled && (
            <span className="text-[11px] text-muted">disabled</span>
          )}
        </div>
        <div className="mt-1 flex items-center gap-2 text-xs text-dim">
          <TokenPill status={state?.status ?? "none"} />
          {state?.expires_at && (
            <span>
              expires{" "}
              {new Date(state.expires_at).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          )}
          {state?.last_refresh_error && (
            <span className="text-down-text">{state.last_refresh_error}</span>
          )}
        </div>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => void refresh()}
          className="flex items-center gap-[6px] rounded-[9px] border border-faint bg-white px-3 py-2 text-xs font-semibold hover:bg-subtle"
        >
          <RefreshIcon size={13} />
          Refresh
        </button>
        <button
          type="button"
          onClick={() => void toggle()}
          className="rounded-[9px] border border-faint bg-white px-3 py-2 text-xs font-semibold hover:bg-subtle"
        >
          {source.enabled ? "Disable" : "Enable"}
        </button>
        <button
          type="button"
          onClick={() => void remove()}
          className="rounded-[9px] border border-[#fecaca] bg-white px-3 py-2 text-xs font-semibold text-down-text hover:bg-down-bg"
        >
          Delete
        </button>
      </div>
    </li>
  );
}

export function AuthSourcesPage() {
  const queryClient = useQueryClient();
  const { message, show } = useToast();
  const { data: sources, isPending, isError, error } = useAuthSources();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);

  const set = (key: keyof typeof EMPTY_FORM) => (value: string) =>
    setForm((f) => ({ ...f, [key]: value }));

  const create = async () => {
    if (form.url.trim() === "") {
      show("Enter the login URL");
      return;
    }
    const body = form.body.trim();
    const headers: Record<string, string> = {};
    if (body.startsWith("{") || body.startsWith("[")) {
      headers["Content-Type"] = "application/json";
    }
    try {
      await createAuthSource({
        name: form.name.trim() || form.url.trim(),
        mode: "custom",
        request: {
          method: form.method,
          url: form.url.trim(),
          headers,
          body: body === "" ? null : body,
        },
        extractor: { kind: "json_path", expr: form.tokenPath.trim() },
        expiry:
          form.expiresInPath.trim() === ""
            ? null
            : { kind: "json_path_seconds", value: form.expiresInPath.trim() },
        injection: {
          target: "header",
          name: form.headerName.trim() || "Authorization",
          value_template: "{token_type} {token}",
        },
      });
      await queryClient.invalidateQueries({ queryKey: ["auth-sources"] });
      setForm(EMPTY_FORM);
      setShowForm(false);
      show("Auth source created");
    } catch (e) {
      show(e instanceof Error ? e.message : "Could not create the auth source");
    }
  };

  return (
    <div className="mx-auto max-w-[840px] px-9 pb-16 pt-[30px]">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-[-0.02em]">Auth sources</h1>
          <p className="mt-2 text-sm text-dim">
            A login request Sentinel replays to fetch a token, inject it into
            linked monitors, and refresh it before it expires. Credentials are
            encrypted at rest and never shown again.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="flex shrink-0 items-center gap-[6px] rounded-[9px] bg-ink px-[14px] py-[9px] text-[13px] font-semibold text-white shadow-[0_1px_2px_rgba(0,0,0,0.12)] hover:bg-black"
        >
          <PlusIcon size={15} />
          New auth source
        </button>
      </div>

      {showForm && (
        <div className="snt-in mt-6 flex flex-col gap-4 rounded-[14px] border border-edge px-[18px] py-4">
          <label className="block">
            <span className="mb-1 block text-[13px] font-semibold">Name</span>
            <input
              value={form.name}
              onChange={(e) => set("name")(e.target.value)}
              placeholder="e.g. Staging login"
              className={`${FIELD} w-full`}
            />
          </label>
          <div>
            <span className="mb-1 block text-[13px] font-semibold">
              Login request
            </span>
            <div className="flex gap-2">
              <label className="block">
                <span className="sr-only">Method</span>
                <select
                  value={form.method}
                  onChange={(e) => set("method")(e.target.value)}
                  className={`${FIELD} w-[110px] bg-white font-mono font-semibold`}
                >
                  {["GET", "POST", "PUT", "PATCH"].map((m) => (
                    <option key={m}>{m}</option>
                  ))}
                </select>
              </label>
              <label className="block min-w-0 flex-1">
                <span className="sr-only">Login URL</span>
                <input
                  value={form.url}
                  onChange={(e) => set("url")(e.target.value)}
                  placeholder="https://api.acme.io/auth/login"
                  className={`${FIELD} w-full font-mono`}
                />
              </label>
            </div>
          </div>
          <label className="block">
            <span className="mb-1 block text-[13px] font-semibold">
              Request body
            </span>
            <textarea
              value={form.body}
              onChange={(e) => set("body")(e.target.value)}
              placeholder='{"user":"svc","pass":"…"}'
              className={`${FIELD} min-h-[80px] w-full resize-y bg-subtle font-mono text-[12.5px]`}
            />
          </label>
          <div className="grid grid-cols-2 gap-[14px]">
            <label className="block">
              <span className="mb-1 block text-[13px] font-semibold">
                Token path
              </span>
              <input
                value={form.tokenPath}
                onChange={(e) => set("tokenPath")(e.target.value)}
                className={`${FIELD} w-full font-mono`}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-[13px] font-semibold">
                Expires-in path (optional)
              </span>
              <input
                value={form.expiresInPath}
                onChange={(e) => set("expiresInPath")(e.target.value)}
                placeholder="$.expires_in"
                className={`${FIELD} w-full font-mono`}
              />
            </label>
          </div>
          <label className="block max-w-[360px]">
            <span className="mb-1 block text-[13px] font-semibold">
              Inject into header
            </span>
            <input
              value={form.headerName}
              onChange={(e) => set("headerName")(e.target.value)}
              className={`${FIELD} w-full font-mono`}
            />
          </label>
          <div className="flex justify-end gap-2 border-t border-fill pt-4">
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="rounded-[9px] border border-faint bg-white px-[14px] py-[9px] text-[13px] font-semibold hover:bg-subtle"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void create()}
              className="rounded-[9px] bg-ink px-[14px] py-[9px] text-[13px] font-semibold text-white hover:bg-black"
            >
              Create auth source
            </button>
          </div>
        </div>
      )}

      {isPending ? (
        <div className="mt-6 text-[13px] text-dim">Loading auth sources…</div>
      ) : isError ? (
        <div className="mt-6 rounded-[14px] border border-[#fecaca] bg-down-bg px-[18px] py-10 text-center text-[13px] text-down-text">
          Could not load auth sources — {error.message}
        </div>
      ) : (sources ?? []).length === 0 ? (
        <div className="mt-6 rounded-[14px] border border-edge px-[18px] py-10 text-center text-[13px] text-dim">
          No auth sources yet. Create one to monitor endpoints that need a
          login token.
        </div>
      ) : (
        <ul className="mt-6 rounded-[14px] border border-edge">
          {(sources ?? []).map((s) => (
            <SourceRow key={s.id} source={s} onToast={show} />
          ))}
        </ul>
      )}
      <Toast message={message} />
    </div>
  );
}
