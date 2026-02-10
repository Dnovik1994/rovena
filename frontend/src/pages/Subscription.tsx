import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import SkeletonList from "../components/SkeletonList";
import { createAdminCheckoutSession, fetchAdminTariffs } from "../services/resources";
import { useAuth } from "../stores/auth";
import { AdminTariff } from "../types/admin";

const Subscription = (): JSX.Element => {
  const { token, user } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [loadingCheckout, setLoadingCheckout] = useState<number | null>(null);
  const enabled = useMemo(() => Boolean(token), [token]);

  const tariffsQuery = useQuery<AdminTariff[]>({
    queryKey: ["subscription-tariffs"],
    queryFn: () => fetchAdminTariffs(token ?? ""),
    enabled,
  });

  const handleUpgrade = async (tariffId: number) => {
    if (!token) {
      setError("Нужна авторизация.");
      return;
    }
    try {
      setLoadingCheckout(tariffId);
      const response = await createAdminCheckoutSession(token, { tariff_id: tariffId });
      window.location.href = response.checkout_url;
    } catch (err) {
      setError("Не удалось создать платежную сессию.");
    } finally {
      setLoadingCheckout(null);
    }
  };

  if (!token) {
    return <p className="page__subtitle">Нужна авторизация.</p>;
  }

  return (
    <section className="page">
      <div>
        <h2 className="page__title">Подписка</h2>
        <p className="page__subtitle">Текущий план и доступные тарифы.</p>
      </div>

      <div className="card card__body">
        <p className="label">Текущий тариф</p>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-lg font-semibold">{user?.tariff?.name ?? "Free"}</p>
            <p className="text-xs text-slate-400">
              Лимиты: аккаунты {user?.tariff?.max_accounts ?? 0}, инвайты/день{" "}
              {user?.tariff?.max_invites_day ?? 0}
            </p>
          </div>
          <div className="text-sm text-slate-300">
            {user?.tariff?.price !== null && user?.tariff?.price !== undefined
              ? `$${user.tariff.price} / month`
              : "Бесплатный план"}
          </div>
        </div>
      </div>

      {tariffsQuery.isLoading ? (
        <SkeletonList rows={3} />
      ) : tariffsQuery.isError ? (
        <p className="hint">Не удалось загрузить тарифы.</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {(tariffsQuery.data ?? []).map((tariff) => (
            <div
              key={tariff.id}
              className="card card__body"
            >
              <h3 className="text-lg font-semibold">{tariff.name}</h3>
              <p className="text-xs text-slate-400">
                Accounts: {tariff.max_accounts} · Invites/day: {tariff.max_invites_day}
              </p>
              <p className="mt-2 text-2xl font-semibold">
                {tariff.price !== null ? `$${tariff.price}` : "Free"}
              </p>
              <p className="mt-2 text-xs text-slate-400">
                Лимиты: аккаунты {tariff.max_accounts}, инвайты/день {tariff.max_invites_day}
              </p>
              <button
                type="button"
                className="mt-4 rounded-xl bg-indigo-500 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                onClick={() => handleUpgrade(tariff.id)}
                disabled={loadingCheckout === tariff.id}
              >
                {loadingCheckout === tariff.id ? "Redirecting..." : "Upgrade"}
              </button>
            </div>
          ))}
        </div>
      )}

      {error && <p className="hint">{error}</p>}
    </section>
  );
};

export default Subscription;
