import React from "react";

interface EmptyStateProps {
  title: string;
  description: string;
}

const EmptyState = ({ title, description }: EmptyStateProps): JSX.Element => {
  return (
    <div className="empty">
      <h2 className="card__title">{title}</h2>
      <p className="page__subtitle">{description}</p>
    </div>
  );
};

export default EmptyState;
