import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import LoadingSkeleton from "../LoadingSkeleton";
import { apiFetch } from "../../shared/api/client";

// ─── Types ───────────────────────────────────────────────────────────

interface WarmingChannel {
  id: number;
  username: string;
  type: "channel" | "group";
  language: string;
  is_active: boolean;
}

interface WarmingBio {
  id: number;
  text: string;
  is_active: boolean;
}

interface WarmingPhoto {
  id: number;
  filename: string;
  assigned_account_id: number | null;
  is_active: boolean;
}

interface WarmingUsername {
  id: number;
  template: string;
  is_active: boolean;
}

interface WarmingName {
  id: number;
  first_name: string;
  last_name: string | null;
  is_active: boolean;
}

interface NotificationSetting {
  id: number;
  chat_id: string;
  on_ban: boolean;
  on_flood_wait: boolean;
  on_warming_done: boolean;
  on_error: boolean;
}

type SubTab =
  | "channels"
  | "bios"
  | "photos"
  | "usernames"
  | "names"
  | "notifications";

// ─── Helpers ─────────────────────────────────────────────────────────

const toast = (message: string) => {
  window.dispatchEvent(
    new CustomEvent("app:toast", { detail: { message } }),
  );
};

const BASE = "/admin/warming";

// ─── API helpers ─────────────────────────────────────────────────────

const warmingFetch = <T,>(
  token: string,
  path: string,
  options: RequestInit = {},
): Promise<T> => apiFetch<T>(`${BASE}${path}`, options, token);

// ─── Component ───────────────────────────────────────────────────────

type AdminWarmingTabProps = {
  token: string;
};

const AdminWarmingTab = ({ token }: AdminWarmingTabProps): JSX.Element => {
  const [subTab, setSubTab] = useState<SubTab>("channels");

  const subTabs: { key: SubTab; label: string }[] = [
    { key: "channels", label: "Channels" },
    { key: "bios", label: "Bios" },
    { key: "photos", label: "Photos" },
    { key: "usernames", label: "Usernames" },
    { key: "names", label: "Names" },
    { key: "notifications", label: "Notifications" },
  ];

  return (
    <div className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-sm">
      {/* Sub-tab selector */}
      <div className="flex flex-wrap gap-1">
        {subTabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setSubTab(t.key)}
            className={`rounded-full px-3 py-1 text-xs ${
              subTab === t.key
                ? "bg-indigo-600 text-white"
                : "bg-slate-800 text-slate-300 hover:bg-slate-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Sub-tab content */}
      {subTab === "channels" && <ChannelsSection token={token} />}
      {subTab === "bios" && <BiosSection token={token} />}
      {subTab === "photos" && <PhotosSection token={token} />}
      {subTab === "usernames" && <UsernamesSection token={token} />}
      {subTab === "names" && <NamesSection token={token} />}
      {subTab === "notifications" && <NotificationsSection token={token} />}
    </div>
  );
};

// ─── 1. Channels ─────────────────────────────────────────────────────

const ChannelsSection = ({ token }: { token: string }): JSX.Element => {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [username, setUsername] = useState("");
  const [type, setType] = useState<"channel" | "group">("channel");
  const [language, setLanguage] = useState("en");

  const query = useQuery<WarmingChannel[]>({
    queryKey: ["warming-channels"],
    queryFn: () => warmingFetch<WarmingChannel[]>(token, "/channels"),
  });

  const createMut = useMutation({
    mutationFn: () =>
      warmingFetch<WarmingChannel>(token, "/channels", {
        method: "POST",
        body: JSON.stringify({ username, type, language }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["warming-channels"] });
      setShowForm(false);
      setUsername("");
      toast("Channel added");
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) =>
      warmingFetch<void>(token, `/channels/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["warming-channels"] });
      toast("Channel removed");
    },
  });

  if (query.isLoading) return <LoadingSkeleton rows={3} label="Loading channels" />;
  if (query.isError)
    return (
      <ErrorBlock onRetry={() => query.refetch()} label="channels" />
    );

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Warming Channels</h3>
        <button
          type="button"
          className="rounded-xl bg-indigo-500 px-3 py-1 text-xs font-semibold text-white"
          onClick={() => setShowForm(!showForm)}
        >
          {showForm ? "Cancel" : "Add channel"}
        </button>
      </div>

      {showForm && (
        <form
          className="flex flex-wrap gap-2 items-end"
          onSubmit={(e) => {
            e.preventDefault();
            createMut.mutate();
          }}
        >
          <div className="space-y-1">
            <label className="label text-xs">Username</label>
            <input
              className="w-48 rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <label className="label text-xs">Type</label>
            <select
              className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              value={type}
              onChange={(e) => setType(e.target.value as "channel" | "group")}
            >
              <option value="channel">channel</option>
              <option value="group">group</option>
            </select>
          </div>
          <div className="space-y-1">
            <label className="label text-xs">Language</label>
            <select
              className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
            >
              <option value="uk">uk</option>
              <option value="ru">ru</option>
              <option value="en">en</option>
            </select>
          </div>
          <button
            type="submit"
            disabled={createMut.isPending}
            className="rounded-xl bg-green-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"
          >
            Save
          </button>
        </form>
      )}

      <Table
        cols={["username", "type", "language", "active", ""]}
        rows={(query.data ?? []).map((ch) => [
          ch.username,
          ch.type,
          ch.language,
          ch.is_active ? "Yes" : "No",
          <DeleteBtn
            key={ch.id}
            loading={deleteMut.isPending}
            onClick={() => deleteMut.mutate(ch.id)}
          />,
        ])}
      />
    </div>
  );
};

// ─── 2. Bios ─────────────────────────────────────────────────────────

const BiosSection = ({ token }: { token: string }): JSX.Element => {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [text, setText] = useState("");

  const query = useQuery<WarmingBio[]>({
    queryKey: ["warming-bios"],
    queryFn: () => warmingFetch<WarmingBio[]>(token, "/bios"),
  });

  const createMut = useMutation({
    mutationFn: () =>
      warmingFetch<WarmingBio>(token, "/bios", {
        method: "POST",
        body: JSON.stringify({ text }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["warming-bios"] });
      setShowForm(false);
      setText("");
      toast("Bio added");
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) =>
      warmingFetch<void>(token, `/bios/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["warming-bios"] });
      toast("Bio removed");
    },
  });

  if (query.isLoading) return <LoadingSkeleton rows={3} label="Loading bios" />;
  if (query.isError) return <ErrorBlock onRetry={() => query.refetch()} label="bios" />;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Warming Bios</h3>
        <button
          type="button"
          className="rounded-xl bg-indigo-500 px-3 py-1 text-xs font-semibold text-white"
          onClick={() => setShowForm(!showForm)}
        >
          {showForm ? "Cancel" : "Add bio"}
        </button>
      </div>

      {showForm && (
        <form
          className="flex gap-2 items-end"
          onSubmit={(e) => {
            e.preventDefault();
            createMut.mutate();
          }}
        >
          <div className="flex-1 space-y-1">
            <label className="label text-xs">Text (max 200)</label>
            <input
              className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              value={text}
              maxLength={200}
              onChange={(e) => setText(e.target.value)}
              required
            />
          </div>
          <button
            type="submit"
            disabled={createMut.isPending}
            className="rounded-xl bg-green-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"
          >
            Save
          </button>
        </form>
      )}

      <Table
        cols={["text", "active", ""]}
        rows={(query.data ?? []).map((b) => [
          <span key={b.id} className="max-w-xs truncate block">{b.text}</span>,
          b.is_active ? "Yes" : "No",
          <DeleteBtn
            key={b.id}
            loading={deleteMut.isPending}
            onClick={() => deleteMut.mutate(b.id)}
          />,
        ])}
      />
    </div>
  );
};

// ─── 3. Photos ───────────────────────────────────────────────────────

const PhotosSection = ({ token }: { token: string }): JSX.Element => {
  const qc = useQueryClient();
  const [uploading, setUploading] = useState(false);

  const query = useQuery<WarmingPhoto[]>({
    queryKey: ["warming-photos"],
    queryFn: () => warmingFetch<WarmingPhoto[]>(token, "/photos"),
  });

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      toast("File too large (max 5MB)");
      return;
    }
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const headers = new Headers();
      headers.set("Authorization", `Bearer ${token}`);
      const API_BASE_URL = (await import("../../shared/api/client")).API_BASE_URL;
      await fetch(`${API_BASE_URL}${BASE}/photos`, {
        method: "POST",
        headers,
        body: formData,
      });
      qc.invalidateQueries({ queryKey: ["warming-photos"] });
      toast("Photo uploaded");
    } catch {
      toast("Upload failed");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const deleteMut = useMutation({
    mutationFn: (id: number) =>
      warmingFetch<void>(token, `/photos/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["warming-photos"] });
      toast("Photo removed");
    },
  });

  if (query.isLoading) return <LoadingSkeleton rows={3} label="Loading photos" />;
  if (query.isError) return <ErrorBlock onRetry={() => query.refetch()} label="photos" />;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Warming Photos</h3>
        <label
          className={`rounded-xl bg-indigo-500 px-3 py-1 text-xs font-semibold text-white cursor-pointer ${
            uploading ? "opacity-50 pointer-events-none" : ""
          }`}
        >
          {uploading ? "Uploading..." : "Upload photo"}
          <input
            type="file"
            className="hidden"
            accept=".jpg,.jpeg,.png,.webp"
            onChange={handleUpload}
            disabled={uploading}
          />
        </label>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
        {(query.data ?? []).map((photo) => (
          <div
            key={photo.id}
            className="rounded-xl border border-slate-800 bg-slate-950 p-3 space-y-1"
          >
            <div className="flex h-20 items-center justify-center rounded bg-slate-900 text-xs text-slate-500">
              {photo.filename}
            </div>
            <p className="text-xs text-slate-400 truncate">{photo.filename}</p>
            <p className="text-xs text-slate-500">
              {photo.assigned_account_id
                ? `Account #${photo.assigned_account_id}`
                : "Free"}
            </p>
            <DeleteBtn
              loading={deleteMut.isPending}
              onClick={() => deleteMut.mutate(photo.id)}
            />
          </div>
        ))}
      </div>
    </div>
  );
};

// ─── 4. Usernames ────────────────────────────────────────────────────

const UsernamesSection = ({ token }: { token: string }): JSX.Element => {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [template, setTemplate] = useState("");

  const query = useQuery<WarmingUsername[]>({
    queryKey: ["warming-usernames"],
    queryFn: () => warmingFetch<WarmingUsername[]>(token, "/usernames"),
  });

  const createMut = useMutation({
    mutationFn: () =>
      warmingFetch<WarmingUsername>(token, "/usernames", {
        method: "POST",
        body: JSON.stringify({ template }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["warming-usernames"] });
      setShowForm(false);
      setTemplate("");
      toast("Username template added");
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) =>
      warmingFetch<void>(token, `/usernames/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["warming-usernames"] });
      toast("Username template removed");
    },
  });

  if (query.isLoading) return <LoadingSkeleton rows={3} label="Loading usernames" />;
  if (query.isError) return <ErrorBlock onRetry={() => query.refetch()} label="usernames" />;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Warming Usernames</h3>
        <button
          type="button"
          className="rounded-xl bg-indigo-500 px-3 py-1 text-xs font-semibold text-white"
          onClick={() => setShowForm(!showForm)}
        >
          {showForm ? "Cancel" : "Add template"}
        </button>
      </div>

      {showForm && (
        <form
          className="flex gap-2 items-end"
          onSubmit={(e) => {
            e.preventDefault();
            if (!/^[a-z0-9_]+$/.test(template)) {
              toast("Only a-z, 0-9, _ allowed");
              return;
            }
            createMut.mutate();
          }}
        >
          <div className="flex-1 space-y-1">
            <label className="label text-xs">Template (a-z 0-9 _, max 100)</label>
            <input
              className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              value={template}
              maxLength={100}
              pattern="[a-z0-9_]+"
              onChange={(e) => setTemplate(e.target.value)}
              required
            />
          </div>
          <button
            type="submit"
            disabled={createMut.isPending}
            className="rounded-xl bg-green-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"
          >
            Save
          </button>
        </form>
      )}

      <Table
        cols={["template", "example", "active", ""]}
        rows={(query.data ?? []).map((u) => [
          u.template,
          `${u.template}_1234`,
          u.is_active ? "Yes" : "No",
          <DeleteBtn
            key={u.id}
            loading={deleteMut.isPending}
            onClick={() => deleteMut.mutate(u.id)}
          />,
        ])}
      />
    </div>
  );
};

// ─── 5. Names ────────────────────────────────────────────────────────

const NamesSection = ({ token }: { token: string }): JSX.Element => {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");

  const query = useQuery<WarmingName[]>({
    queryKey: ["warming-names"],
    queryFn: () => warmingFetch<WarmingName[]>(token, "/names"),
  });

  const createMut = useMutation({
    mutationFn: () =>
      warmingFetch<WarmingName>(token, "/names", {
        method: "POST",
        body: JSON.stringify({
          first_name: firstName,
          last_name: lastName || null,
        }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["warming-names"] });
      setShowForm(false);
      setFirstName("");
      setLastName("");
      toast("Name added");
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) =>
      warmingFetch<void>(token, `/names/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["warming-names"] });
      toast("Name removed");
    },
  });

  if (query.isLoading) return <LoadingSkeleton rows={3} label="Loading names" />;
  if (query.isError) return <ErrorBlock onRetry={() => query.refetch()} label="names" />;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Warming Names</h3>
        <button
          type="button"
          className="rounded-xl bg-indigo-500 px-3 py-1 text-xs font-semibold text-white"
          onClick={() => setShowForm(!showForm)}
        >
          {showForm ? "Cancel" : "Add name"}
        </button>
      </div>

      {showForm && (
        <form
          className="flex flex-wrap gap-2 items-end"
          onSubmit={(e) => {
            e.preventDefault();
            createMut.mutate();
          }}
        >
          <div className="space-y-1">
            <label className="label text-xs">First name *</label>
            <input
              className="w-40 rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <label className="label text-xs">Last name</label>
            <input
              className="w-40 rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
            />
          </div>
          <button
            type="submit"
            disabled={createMut.isPending}
            className="rounded-xl bg-green-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"
          >
            Save
          </button>
        </form>
      )}

      <Table
        cols={["first_name", "last_name", "active", ""]}
        rows={(query.data ?? []).map((n) => [
          n.first_name,
          n.last_name ?? "—",
          n.is_active ? "Yes" : "No",
          <DeleteBtn
            key={n.id}
            loading={deleteMut.isPending}
            onClick={() => deleteMut.mutate(n.id)}
          />,
        ])}
      />
    </div>
  );
};

// ─── 6. Notifications ────────────────────────────────────────────────

const EVENT_KEYS = ["on_ban", "on_flood_wait", "on_warming_done", "on_error"] as const;

const NotificationsSection = ({ token }: { token: string }): JSX.Element => {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [chatId, setChatId] = useState("");
  const [events, setEvents] = useState<Record<string, boolean>>({
    on_ban: true,
    on_flood_wait: true,
    on_warming_done: true,
    on_error: true,
  });

  const query = useQuery<NotificationSetting[]>({
    queryKey: ["warming-notifications"],
    queryFn: () =>
      warmingFetch<NotificationSetting[]>(token, "/notifications"),
  });

  const createMut = useMutation({
    mutationFn: () =>
      warmingFetch<NotificationSetting>(token, "/notifications", {
        method: "POST",
        body: JSON.stringify({ chat_id: chatId, ...events }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["warming-notifications"] });
      setShowForm(false);
      setChatId("");
      toast("Notification setting added");
    },
  });

  const patchMut = useMutation({
    mutationFn: (payload: { id: number; data: Record<string, boolean> }) =>
      warmingFetch<NotificationSetting>(token, `/notifications/${payload.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload.data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["warming-notifications"] });
      toast("Updated");
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) =>
      warmingFetch<void>(token, `/notifications/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["warming-notifications"] });
      toast("Notification setting removed");
    },
  });

  if (query.isLoading)
    return <LoadingSkeleton rows={3} label="Loading notifications" />;
  if (query.isError)
    return <ErrorBlock onRetry={() => query.refetch()} label="notifications" />;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Notification Settings</h3>
        <button
          type="button"
          className="rounded-xl bg-indigo-500 px-3 py-1 text-xs font-semibold text-white"
          onClick={() => setShowForm(!showForm)}
        >
          {showForm ? "Cancel" : "Add setting"}
        </button>
      </div>

      {showForm && (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            createMut.mutate();
          }}
        >
          <div className="space-y-1">
            <label className="label text-xs">Chat ID</label>
            <input
              className="w-60 rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              value={chatId}
              onChange={(e) => setChatId(e.target.value)}
              required
            />
          </div>
          <div className="flex flex-wrap gap-3">
            {EVENT_KEYS.map((key) => (
              <label key={key} className="flex items-center gap-1 text-xs text-slate-300">
                <input
                  type="checkbox"
                  checked={events[key] ?? false}
                  onChange={(e) =>
                    setEvents((prev) => ({ ...prev, [key]: e.target.checked }))
                  }
                />
                {key}
              </label>
            ))}
          </div>
          <button
            type="submit"
            disabled={createMut.isPending}
            className="rounded-xl bg-green-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"
          >
            Save
          </button>
        </form>
      )}

      <div className="space-y-2">
        {(query.data ?? []).map((ns) => (
          <div
            key={ns.id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-950 px-3 py-2"
          >
            <div>
              <p className="font-semibold text-xs">Chat: {ns.chat_id}</p>
              <div className="flex flex-wrap gap-3 mt-1">
                {EVENT_KEYS.map((key) => (
                  <label
                    key={key}
                    className="flex items-center gap-1 text-xs text-slate-400"
                  >
                    <input
                      type="checkbox"
                      checked={ns[key]}
                      onChange={(e) =>
                        patchMut.mutate({
                          id: ns.id,
                          data: { [key]: e.target.checked },
                        })
                      }
                    />
                    {key}
                  </label>
                ))}
              </div>
            </div>
            <DeleteBtn
              loading={deleteMut.isPending}
              onClick={() => deleteMut.mutate(ns.id)}
            />
          </div>
        ))}
      </div>
    </div>
  );
};

// ─── Shared small components ─────────────────────────────────────────

const DeleteBtn = ({
  onClick,
  loading,
}: {
  onClick: () => void;
  loading: boolean;
}): JSX.Element => (
  <button
    type="button"
    disabled={loading}
    className="rounded-full border border-rose-400 px-3 py-1 text-xs text-rose-200 disabled:opacity-50"
    onClick={() => {
      if (window.confirm("Delete this item?")) onClick();
    }}
  >
    Delete
  </button>
);

const ErrorBlock = ({
  onRetry,
  label,
}: {
  onRetry: () => void;
  label: string;
}): JSX.Element => (
  <div className="text-red-500 p-4 text-center">
    Error loading {label}.{" "}
    <button type="button" onClick={onRetry} className="underline">
      Retry
    </button>
  </div>
);

const Table = ({
  cols,
  rows,
}: {
  cols: string[];
  rows: React.ReactNode[][];
}): JSX.Element => (
  <div className="overflow-x-auto">
    <table className="w-full text-xs text-left">
      <thead>
        <tr className="border-b border-slate-800 text-slate-400">
          {cols.map((c) => (
            <th key={c} className="px-2 py-1 font-medium">
              {c}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={cols.length} className="px-2 py-3 text-center text-slate-500">
              No items
            </td>
          </tr>
        ) : (
          rows.map((row, i) => (
            <tr key={i} className="border-b border-slate-800/50">
              {row.map((cell, j) => (
                <td key={j} className="px-2 py-1.5">
                  {cell}
                </td>
              ))}
            </tr>
          ))
        )}
      </tbody>
    </table>
  </div>
);

export default AdminWarmingTab;
