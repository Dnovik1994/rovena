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
    <div className="error">
      <p className="card__title">{title}</p>
      <p className="hint">{description}</p>
    </div>
  );
};

export default ErrorState;
