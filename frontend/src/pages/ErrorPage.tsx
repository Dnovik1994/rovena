import React from "react";
import { useParams } from "react-router-dom";

const errorCopy: Record<string, { title: string; description: string }> = {
  "403": {
    title: "Access denied",
    description: "У вас нет прав для доступа к этой странице.",
  },
  "429": {
    title: "Too many requests",
    description: "Лимит запросов превышен. Попробуйте позже.",
  },
  "500": {
    title: "Something went wrong",
    description: "Сервис временно недоступен. Мы уже разбираемся.",
  },
};

const ErrorPage = (): JSX.Element => {
  const { code } = useParams();
  const error = errorCopy[code ?? "500"] ?? errorCopy["500"];

  return (
    <section className="flex min-h-[50vh] items-center justify-center">
      <div className="rounded-3xl border border-rose-500/40 bg-rose-500/10 p-8 text-center text-rose-100">
        <p className="text-xs uppercase tracking-[0.3em] text-rose-200">Error {code}</p>
        <h2 className="mt-3 text-2xl font-semibold">{error.title}</h2>
        <p className="mt-2 text-sm text-rose-200/80">{error.description}</p>
        <p className="mt-6 text-xs text-rose-200/70">Если ошибка повторяется, обратитесь к администратору.</p>
      </div>
    </section>
  );
};

export default ErrorPage;
