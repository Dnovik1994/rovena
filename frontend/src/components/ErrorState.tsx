import React from "react";

interface ErrorStateProps {
  title?: string;
  description?: string;
}

const ErrorState = ({
  title = "Ошибка",
  description = "Что-то пошло не так. Попробуйте позже.",
}: ErrorStateProps): JSX.Element => {
  return (
    <div className="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
      <p className="font-semibold">{title}</p>
      <p className="mt-1 text-xs text-rose-100/80">{description}</p>
    </div>
  );
};

export default ErrorState;
