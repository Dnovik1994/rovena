import React from "react";

interface EmptyStateProps {
  title: string;
  description: string;
}

const EmptyState = ({ title, description }: EmptyStateProps): JSX.Element => {
  return (
    <div className="rounded-2xl border border-dashed border-slate-800 bg-slate-900/40 p-6 text-center">
      <h2 className="text-lg font-semibold text-slate-100">{title}</h2>
      <p className="mt-2 text-sm text-slate-400">{description}</p>
    </div>
  );
};

export default EmptyState;
