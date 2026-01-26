import React, { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import EmptyState from "../components/EmptyState";
import SkeletonList from "../components/SkeletonList";
import { createProject, fetchProjects } from "../services/resources";
import { useAuth } from "../stores/auth";
import { Project } from "../types/project";

const schema = z.object({
  name: z.string().min(2),
  description: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

const Projects = (): JSX.Element => {
  const { token } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    reset,
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
  });

  const fetchData = async (): Promise<void> => {
    if (!token) {
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      const data = await fetchProjects(token);
      setProjects(data);
      setError(null);
    } catch (err) {
      setError("Не удалось загрузить проекты.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [token]);

  const onSubmit = async (values: FormValues) => {
    if (!token) {
      setError("Нужна авторизация.");
      return;
    }

    try {
      const newProject = await createProject(token, {
        name: values.name,
        description: values.description || null,
      });
      setProjects((prev) => [newProject, ...prev]);
      reset();
      setError(null);
    } catch (err) {
      setError("Не удалось создать проект.");
    }
  };

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Projects</h2>
        <p className="text-sm text-slate-400">
          Добавляйте проекты и назначайте источники аудитории.
        </p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-3 rounded-2xl bg-slate-900/60 p-4">
        <div>
          <label className="text-xs uppercase text-slate-400">Название проекта</label>
          <input
            className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
            {...register("name")}
            placeholder="Например, Crypto Community"
          />
          {errors.name && <p className="text-xs text-rose-400">Минимум 2 символа.</p>}
        </div>
        <div>
          <label className="text-xs uppercase text-slate-400">Описание</label>
          <textarea
            className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
            rows={3}
            {...register("description")}
            placeholder="Кратко о проекте"
          />
        </div>
        <button
          type="submit"
          className="rounded-xl bg-indigo-500 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          disabled={isSubmitting}
        >
          {isSubmitting ? "Сохраняем..." : "Создать проект"}
        </button>
        {error && <p className="text-sm text-rose-400">{error}</p>}
      </form>

      {loading ? (
        <SkeletonList rows={4} />
      ) : projects.length === 0 ? (
        <EmptyState
          title="Проектов пока нет"
          description="Создайте первый проект, чтобы перейти к источникам и кампаниям."
        />
      ) : (
        <div className="space-y-3">
          {projects.map((project) => (
            <div
              key={project.id}
              className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4"
            >
              <div className="flex items-center justify-between">
                <h3 className="text-base font-semibold">{project.name}</h3>
                <span className="text-xs text-slate-400">#{project.id}</span>
              </div>
              {project.description && (
                <p className="mt-2 text-sm text-slate-300">{project.description}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
};

export default Projects;
