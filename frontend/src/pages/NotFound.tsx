import React from "react";
import { Link } from "react-router-dom";

const NotFound = (): JSX.Element => {
  return (
    <section className="flex min-h-[50vh] items-center justify-center">
      <div className="rounded-3xl border border-slate-800 bg-slate-900/60 p-8 text-center text-slate-100">
        <p className="text-xs uppercase tracking-[0.3em] text-slate-400">404</p>
        <h2 className="mt-3 text-2xl font-semibold">Страница не найдена</h2>
        <p className="mt-2 text-sm text-slate-300/80">
          Проверьте ссылку или вернитесь на главную.
        </p>
        <Link
          to="/"
          className="mt-6 inline-flex rounded-full border border-slate-600 px-4 py-2 text-xs text-slate-100"
        >
          На главную
        </Link>
      </div>
    </section>
  );
};

export default NotFound;
