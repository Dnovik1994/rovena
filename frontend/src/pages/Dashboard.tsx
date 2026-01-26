import React from "react";
import EmptyState from "../components/EmptyState";

const Dashboard = (): JSX.Element => {
  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Dashboard</h2>
        <p className="text-sm text-slate-400">
          Обзор активности и быстрые действия будут здесь.
        </p>
      </div>
      <EmptyState
        title="Пока нет активности"
        description="Добавьте проект и источники, чтобы увидеть статистику."
      />
    </section>
  );
};

export default Dashboard;
