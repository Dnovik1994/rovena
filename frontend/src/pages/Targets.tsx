import React, { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import EmptyState from "../components/EmptyState";
import SkeletonList from "../components/SkeletonList";
import { createTarget, fetchTargets } from "../services/resources";
import { useAuth } from "../stores/auth";
import { Target } from "../types/target";

const schema = z.object({
  project_id: z.coerce.number().int().positive(),
  name: z.string().min(2),
  link: z.string().min(5),
  type: z.enum(["group", "channel"]),
});

type FormValues = z.infer<typeof schema>;

const Targets = (): JSX.Element => {
  const { token } = useAuth();
  const [targets, setTargets] = useState<Target[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    reset,
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { type: "group" },
  });

  const load = async () => {
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const data = await fetchTargets(token);
      setTargets(data);
    } catch (err) {
      setError("Не удалось загрузить цели.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [token]);

  const onSubmit = async (values: FormValues) => {
    if (!token) {
      setError("Нужна авторизация.");
      return;
    }
    try {
      const created = await createTarget(token, values);
      setTargets((prev) => [created, ...prev]);
      reset({ project_id: values.project_id, name: "", link: "", type: values.type });
      setError(null);
    } catch (err) {
      setError("Не удалось создать цель.");
    }
  };

  return (
    <section className="page">
      <div>
        <h2 className="page__title">Targets</h2>
        <p className="page__subtitle">Целевые группы и каналы.</p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-3 rounded-2xl bg-slate-900/60 p-4">
        <div>
          <label className="label">Project ID</label>
          <input
            className="input"
            type="number"
            {...register("project_id")}
          />
          {errors.project_id && (
            <p className="text-xs text-rose-400">Укажите project_id.</p>
          )}
        </div>
        <div>
          <label className="label">Название</label>
          <input
            className="input"
            {...register("name")}
          />
          {errors.name && <p className="text-xs text-rose-400">Минимум 2 символа.</p>}
        </div>
        <div>
          <label className="label">Ссылка</label>
          <input
            className="input"
            {...register("link")}
            placeholder="https://t.me/group"
          />
          {errors.link && <p className="text-xs text-rose-400">Укажите ссылку.</p>}
        </div>
        <div>
          <label className="label">Тип</label>
          <select
            className="input"
            {...register("type")}
          >
            <option value="group">Group</option>
            <option value="channel">Channel</option>
          </select>
        </div>
        <button
          type="submit"
          className="btn btn--primary"
          disabled={isSubmitting}
        >
          {isSubmitting ? "Сохраняем..." : "Добавить цель"}
        </button>
        {error && <p className="hint">{error}</p>}
      </form>

      {loading ? (
        <SkeletonList rows={4} />
      ) : targets.length === 0 ? (
        <EmptyState
          title="Целей нет"
          description="Добавьте целевую группу, чтобы запускать кампании."
        />
      ) : (
        <div className="space-y-3">
          {targets.map((target) => (
            <div
              key={target.id}
              className="card card__body"
            >
              <div className="flex items-center justify-between">
                <h3 className="text-base font-semibold">{target.name}</h3>
                <span className="text-xs text-slate-400">#{target.id}</span>
              </div>
              <p className="mt-2 text-sm text-slate-300">{target.link}</p>
              <p className="text-xs uppercase text-slate-500">{target.type}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
};

export default Targets;
