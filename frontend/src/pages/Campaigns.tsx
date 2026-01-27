import React, { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import EmptyState from "../components/EmptyState";
import SkeletonList from "../components/SkeletonList";
import {
  createCampaign,
  fetchCampaigns,
  startCampaign,
  stopCampaign,
} from "../services/resources";
import { connectStatusSocket, StatusMessage } from "../services/websocket";
import { useAuth } from "../stores/auth";
import { Campaign } from "../types/campaign";

const schema = z.object({
  project_id: z.coerce.number().int().positive(),
  name: z.string().min(2),
  source_id: z.coerce.number().int().positive().optional(),
  target_id: z.coerce.number().int().positive().optional(),
  max_invites_per_hour: z.coerce.number().int().min(1),
  max_invites_per_day: z.coerce.number().int().min(1),
});

type FormValues = z.infer<typeof schema>;

const Campaigns = (): JSX.Element => {
  const { token } = useAuth();
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCampaignId, setSelectedCampaignId] = useState<number | null>(null);
  const [dispatchErrors, setDispatchErrors] = useState<
    { campaign_id: number; error: string; account_id?: number | null; contact_id?: number | null }[]
  >([]);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    reset,
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { max_invites_per_hour: 1, max_invites_per_day: 5 },
  });

  const load = async () => {
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const data = await fetchCampaigns(token);
      setCampaigns(data);
    } catch (err) {
      setError("Не удалось загрузить кампании.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [token]);

  useEffect(() => {
    const telegram = (window as unknown as { Telegram?: { WebApp?: { MainButton?: { show: () => void; hide: () => void; setText: (text: string) => void; onClick: (cb: () => void) => void; offClick: (cb: () => void) => void } } } }).Telegram?.WebApp;
    const mainButton = telegram?.MainButton;
    if (!mainButton) {
      return;
    }

    const selected = campaigns.find((item) => item.id === selectedCampaignId);
    if (!selected) {
      mainButton.hide();
      return;
    }

    const handler = () => {
      if (selected.status === "active") {
        void handleStop(selected.id);
      } else {
        void handleStart(selected.id);
      }
    };

    mainButton.setText(selected.status === "active" ? "Pause Campaign" : "Start Campaign");
    mainButton.show();
    mainButton.onClick(handler);
    return () => {
      mainButton.offClick(handler);
    };
  }, [campaigns, selectedCampaignId]);

  useEffect(() => {
    if (!token) {
      return;
    }
    const socket = connectStatusSocket(token, (message: StatusMessage) => {
      if (message.type === "campaign_progress") {
        setCampaigns((prev) =>
          prev.map((item) =>
            item.id === message.campaign_id
              ? { ...item, progress: message.progress }
              : item
          )
        );
      }
      if (message.type === "dispatch_error") {
        setDispatchErrors((prev) =>
          [
            {
              campaign_id: message.campaign_id,
              error: message.error,
              account_id: message.account_id,
              contact_id: message.contact_id,
            },
            ...prev,
          ].slice(0, 10)
        );
      }
    });

    return () => {
      socket.close();
    };
  }, [token]);

  const onSubmit = async (values: FormValues) => {
    if (!token) {
      setError("Нужна авторизация.");
      return;
    }
    try {
      const created = await createCampaign(token, {
        project_id: values.project_id,
        name: values.name,
        source_id: values.source_id || null,
        target_id: values.target_id || null,
        max_invites_per_hour: values.max_invites_per_hour,
        max_invites_per_day: values.max_invites_per_day,
      });
      setCampaigns((prev) => [created, ...prev]);
      reset({
        project_id: values.project_id,
        name: "",
        source_id: undefined,
        target_id: undefined,
        max_invites_per_hour: 1,
        max_invites_per_day: 5,
      });
      setError(null);
    } catch (err) {
      setError("Не удалось создать кампанию.");
    }
  };

  const handleStart = async (id: number) => {
    if (!token) {
      return;
    }
    const updated = await startCampaign(token, id);
    setCampaigns((prev) => prev.map((item) => (item.id === id ? updated : item)));
  };

  const handleStop = async (id: number) => {
    if (!token) {
      return;
    }
    const updated = await stopCampaign(token, id);
    setCampaigns((prev) => prev.map((item) => (item.id === id ? updated : item)));
  };

  const formatProgress = (campaign: Campaign) => {
    const percent = Math.min(100, Math.round(campaign.progress || 0));
    return { percent, label: `${percent}%` };
  };

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Campaigns</h2>
        <p className="text-sm text-slate-400">
          Кампании инвайтинга: запуск и контроль прогресса.
        </p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-3 rounded-2xl bg-slate-900/60 p-4">
        <div>
          <label className="text-xs uppercase text-slate-400">Project ID</label>
          <input
            className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
            type="number"
            {...register("project_id")}
          />
          {errors.project_id && (
            <p className="text-xs text-rose-400">Укажите project_id.</p>
          )}
        </div>
        <div>
          <label className="text-xs uppercase text-slate-400">Название</label>
          <input
            className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
            {...register("name")}
          />
          {errors.name && <p className="text-xs text-rose-400">Минимум 2 символа.</p>}
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <label className="text-xs uppercase text-slate-400">Source ID</label>
            <input
              className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              type="number"
              {...register("source_id")}
            />
          </div>
          <div>
            <label className="text-xs uppercase text-slate-400">Target ID</label>
            <input
              className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              type="number"
              {...register("target_id")}
            />
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <label className="text-xs uppercase text-slate-400">Invites/hour</label>
            <input
              className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              type="number"
              {...register("max_invites_per_hour")}
            />
          </div>
          <div>
            <label className="text-xs uppercase text-slate-400">Invites/day</label>
            <input
              className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              type="number"
              {...register("max_invites_per_day")}
            />
          </div>
        </div>
        <button
          type="submit"
          className="rounded-xl bg-indigo-500 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          disabled={isSubmitting}
        >
          {isSubmitting ? "Сохраняем..." : "Создать кампанию"}
        </button>
        {error && <p className="text-sm text-rose-400">{error}</p>}
      </form>

      {error && !loading && (
        <div className="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
          {error}
        </div>
      )}

      {loading ? (
        <SkeletonList rows={4} />
      ) : campaigns.length === 0 ? (
        <EmptyState
          title="Кампаний пока нет"
          description="Создайте кампанию, чтобы видеть статус и прогресс."
        />
      ) : (
        <div className="space-y-3">
          {campaigns.map((campaign) => {
            const progress = formatProgress(campaign);
            return (
              <div
                key={campaign.id}
                onClick={() => setSelectedCampaignId(campaign.id)}
                className={[
                  "rounded-2xl border bg-slate-900/60 p-4",
                  selectedCampaignId === campaign.id ? "border-indigo-400" : "border-slate-800",
                ].join(" ")}
              >
                <div className="flex items-center justify-between">
                  <h3 className="text-base font-semibold">{campaign.name}</h3>
                  <span className="text-xs text-slate-400">{campaign.status}</span>
                </div>
                <div className="mt-3 space-y-1">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span>Progress</span>
                    <span>{progress.label}</span>
                  </div>
                  <div className="h-2 w-full rounded-full bg-slate-800">
                    <div
                      className="h-2 rounded-full bg-emerald-400/80"
                      style={{ width: `${progress.percent}%` }}
                    />
                  </div>
                </div>
                {dispatchErrors.some((item) => item.campaign_id === campaign.id) && (
                  <div className="mt-3 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
                    <p className="font-semibold">Последние ошибки dispatch</p>
                    <ul className="mt-2 space-y-1">
                      {dispatchErrors
                        .filter((item) => item.campaign_id === campaign.id)
                        .slice(0, 3)
                        .map((item, index) => (
                          <li key={`${item.campaign_id}-${index}`}>
                            {item.error}
                            {item.account_id ? ` · acc ${item.account_id}` : ""}
                            {item.contact_id ? ` · contact ${item.contact_id}` : ""}
                          </li>
                        ))}
                    </ul>
                  </div>
                )}
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    onClick={() => handleStart(campaign.id)}
                    className="rounded-lg bg-emerald-500/80 px-3 py-1 text-xs font-semibold disabled:opacity-60"
                    disabled={campaign.status === "active"}
                  >
                    {campaign.status === "active" ? "Running..." : "Start"}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleStop(campaign.id)}
                    className="rounded-lg bg-amber-500/80 px-3 py-1 text-xs font-semibold disabled:opacity-60"
                    disabled={campaign.status !== "active"}
                  >
                    Pause
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};

export default Campaigns;
