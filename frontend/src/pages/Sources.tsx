import React, { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import EmptyState from "../components/EmptyState";
import SkeletonList from "../components/SkeletonList";
import { createSource, fetchSources } from "../services/resources";
import { useAuth } from "../stores/auth";
import { Source } from "../types/source";

const schema = z.object({
  project_id: z.coerce.number().int().positive(),
  name: z.string().min(2),
  link: z.string().min(5),
  type: z.enum(["group", "channel"]),
});

type FormValues = z.infer<typeof schema>;

const Sources = (): JSX.Element => {
  const { token } = useAuth();
  const [sources, setSources] = useState<Source[]>([]);
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
      const data = await fetchSources(token);
      setSources(data);
    } catch (err) {
      setError("Не удалось загрузить источники.");
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
      const created = await createSource(token, values);
      setSources((prev) => [created, ...prev]);
      reset({ project_id: values.project_id, name: "", link: "", type: values.type });
      setError(null);
    } catch (err) {
      setError("Не удалось создать источник.");
    }
  };

  return (
    <section className="page">
      <div>
        <h2 className="page__title">Sources</h2>
        <p className="page__subtitle">Источники парсинга для проектов.</p>
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
          {isSubmitting ? "Сохраняем..." : "Добавить источник"}
        </button>
        {error && <p className="hint">{error}</p>}
      </form>

      {loading ? (
        <SkeletonList rows={4} />
      ) : sources.length === 0 ? (
        <EmptyState
          title="Источников нет"
          description="Добавьте источник, чтобы начать парсинг."
        />
      ) : (
        <div className="space-y-3">
          {sources.map((source) => (
            <div
              key={source.id}
              className="card card__body"
            >
              <div className="flex items-center justify-between">
                <h3 className="text-base font-semibold">{source.name}</h3>
                <span className="text-xs text-slate-400">#{source.id}</span>
              </div>
              <p className="mt-2 text-sm text-slate-300">{source.link}</p>
              <p className="text-xs uppercase text-slate-500">{source.type}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
};

export default Sources;
