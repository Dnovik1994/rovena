import React from "react";

interface EmptyStateProps {
  title: string;
  description: string;
  children?: React.ReactNode;
}

const EmptyState = ({ title, description, children }: EmptyStateProps): JSX.Element => {
  return (
    <div className="empty">
      <h2 className="card__title">{title}</h2>
      <p className="page__subtitle">{description}</p>
      {children}
    </div>
  );
};

export default EmptyState;
