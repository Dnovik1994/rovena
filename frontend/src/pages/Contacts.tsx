import React, { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import EmptyState from "../components/EmptyState";
import SkeletonList from "../components/SkeletonList";
import { createContact, fetchContacts } from "../services/resources";
import { useAuth } from "../stores/auth";
import { Contact } from "../types/contact";

const schema = z.object({
  project_id: z.coerce.number().int().positive(),
  telegram_id: z.coerce.number().int().positive(),
  first_name: z.string().min(1),
  last_name: z.string().optional(),
  username: z.string().optional(),
  phone: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

const Contacts = (): JSX.Element => {
  const { token } = useAuth();
  const [contacts, setContacts] = useState<Contact[]>([]);
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

  const load = async () => {
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const data = await fetchContacts(token);
      setContacts(data);
    } catch (err) {
      setError("Не удалось загрузить контакты.");
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
      const created = await createContact(token, values);
      setContacts((prev) => [created, ...prev]);
      reset({ project_id: values.project_id, telegram_id: values.telegram_id, first_name: "", last_name: "", username: "", phone: "" });
      setError(null);
    } catch (err) {
      setError("Не удалось создать контакт.");
    }
  };

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Contacts</h2>
        <p className="text-sm text-slate-400">Контакты аудитории и метки.</p>
      </div>

      <form
        onSubmit={handleSubmit(onSubmit)}
        className="space-y-3 rounded-2xl bg-[var(--tg-theme-secondary-bg)] p-4"
      >
        <div>
          <label className="text-xs uppercase text-slate-400">Project ID</label>
          <input
            className="mt-1 w-full rounded-xl border border-slate-800 bg-[var(--tg-theme-bg)] px-3 py-2 text-sm"
            type="number"
            {...register("project_id")}
          />
          {errors.project_id && (
            <p className="text-xs text-rose-400">Укажите project_id.</p>
          )}
        </div>
        <div>
          <label className="text-xs uppercase text-slate-400">Telegram ID</label>
          <input
            className="mt-1 w-full rounded-xl border border-slate-800 bg-[var(--tg-theme-bg)] px-3 py-2 text-sm"
            type="number"
            {...register("telegram_id")}
          />
          {errors.telegram_id && (
            <p className="text-xs text-rose-400">Укажите Telegram ID.</p>
          )}
        </div>
        <div>
          <label className="text-xs uppercase text-slate-400">Имя</label>
          <input
            className="mt-1 w-full rounded-xl border border-slate-800 bg-[var(--tg-theme-bg)] px-3 py-2 text-sm"
            {...register("first_name")}
          />
          {errors.first_name && (
            <p className="text-xs text-rose-400">Укажите имя.</p>
          )}
        </div>
        <div>
          <label className="text-xs uppercase text-slate-400">Фамилия</label>
          <input
            className="mt-1 w-full rounded-xl border border-slate-800 bg-[var(--tg-theme-bg)] px-3 py-2 text-sm"
            {...register("last_name")}
          />
        </div>
        <div>
          <label className="text-xs uppercase text-slate-400">Username</label>
          <input
            className="mt-1 w-full rounded-xl border border-slate-800 bg-[var(--tg-theme-bg)] px-3 py-2 text-sm"
            {...register("username")}
          />
        </div>
        <div>
          <label className="text-xs uppercase text-slate-400">Phone</label>
          <input
            className="mt-1 w-full rounded-xl border border-slate-800 bg-[var(--tg-theme-bg)] px-3 py-2 text-sm"
            {...register("phone")}
          />
        </div>
        <button
          type="submit"
          className="rounded-xl bg-indigo-500 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          disabled={isSubmitting}
        >
          {isSubmitting ? "Сохраняем..." : "Добавить контакт"}
        </button>
        {error && <p className="text-sm text-rose-400">{error}</p>}
      </form>

      {loading ? (
        <SkeletonList rows={4} />
      ) : contacts.length === 0 ? (
        <EmptyState
          title="Контактов нет"
          description="Контакты появятся после парсинга источников."
        />
      ) : (
        <div className="space-y-3">
          {contacts.map((contact) => {
            const isBlocked = contact.blocked;
            const tooltip = contact.blocked_reason || "Blocked";

            return (
              <div
                key={contact.id}
                title={isBlocked ? tooltip : undefined}
                className={[
                  "rounded-2xl border p-4",
                  isBlocked
                    ? "border-rose-500/70 bg-rose-500/10"
                    : "border-slate-800 bg-[var(--tg-theme-secondary-bg)]",
                ].join(" ")}
              >
                <div className="flex items-center justify-between">
                  <h3 className={["text-base font-semibold", isBlocked ? "text-rose-200" : ""].join(" ")}>
                    {contact.first_name}
                  </h3>
                  <span className={["text-xs", isBlocked ? "text-rose-300" : "text-slate-400"].join(" ")}>
                    #{contact.telegram_id}
                  </span>
                </div>
                <p className={["text-xs", isBlocked ? "text-rose-300/80" : "text-slate-500"].join(" ")}>
                  {contact.username || "no username"}
                </p>
                {isBlocked && (
                  <p className="mt-2 text-xs text-rose-300">
                    Blocked: {tooltip}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};

export default Contacts;
