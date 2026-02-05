import React, { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { updateOnboarding } from "../services/resources";
import { useAuth } from "../stores/auth";

const steps = [
  {
    title: "Добавьте первый прокси",
    description: "Перейдите в Admin → Proxies и добавьте резидентский прокси.",
    link: "/admin",
    linkLabel: "Открыть Admin",
  },
  {
    title: "Добавьте первый аккаунт",
    description: "Создайте аккаунт Telegram и назначьте прокси.",
    link: "/accounts",
    linkLabel: "Добавить аккаунт",
  },
  {
    title: "Создайте кампанию",
    description: "Настройте источник/цель и лимиты, затем запустите кампанию.",
    link: "/campaigns",
    linkLabel: "Запустить кампанию",
  },
];

const Onboarding = (): JSX.Element => {
  const { token, setOnboardingNeeded } = useAuth();
  const navigate = useNavigate();
  const [stepIndex, setStepIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const currentStep = useMemo(() => steps[stepIndex], [stepIndex]);

  const handleNext = async () => {
    if (stepIndex < steps.length - 1) {
      setStepIndex((prev) => prev + 1);
      return;
    }
    if (!token) {
      return;
    }
    setLoading(true);
    try {
      await updateOnboarding(token, true);
      setOnboardingNeeded(false);
      navigate("/", { replace: true });
    } finally {
      setLoading(false);
    }
  };

  const handleBack = () => {
    setStepIndex((prev) => Math.max(prev - 1, 0));
  };

  return (
    <section className="mx-auto flex min-h-[70vh] max-w-xl flex-col justify-center gap-6">
      <div>
        <p className="text-xs uppercase text-slate-400">Onboarding</p>
        <h2 className="text-2xl font-semibold">{currentStep.title}</h2>
        <p className="mt-2 text-sm text-slate-400">{currentStep.description}</p>
        <Link
          className="mt-4 inline-flex items-center rounded-xl border border-slate-700 px-3 py-2 text-sm"
          to={currentStep.link}
        >
          {currentStep.linkLabel}
        </Link>
      </div>
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
        <p className="text-xs text-slate-400">
          Шаг {stepIndex + 1} из {steps.length}
        </p>
        <div className="mt-3 h-2 w-full rounded-full bg-slate-800">
          <div
            className="h-2 rounded-full bg-indigo-500"
            style={{ width: `${Math.round(((stepIndex + 1) / steps.length) * 100)}%` }}
          />
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="rounded-xl border border-slate-700 px-4 py-2 text-sm"
          onClick={handleBack}
          disabled={stepIndex === 0}
        >
          Назад
        </button>
        <button
          type="button"
          className="rounded-xl bg-indigo-500 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          onClick={handleNext}
          disabled={loading}
        >
          {stepIndex === steps.length - 1 ? (loading ? "Сохраняем..." : "Завершить") : "Далее"}
        </button>
      </div>
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-300">
        <p className="font-semibold">Что дальше?</p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-slate-400">
          <li>Проверьте лимиты тарифа и при необходимости обновите подписку.</li>
          <li>Настройте источники и цели, чтобы собирать релевантные контакты.</li>
          <li>Следите за статусом аккаунтов на странице Accounts.</li>
        </ul>
      </div>
    </section>
  );
};

export default Onboarding;
