import React from "react";

interface SkeletonListProps {
  rows?: number;
}

const SkeletonList = ({ rows = 3 }: SkeletonListProps): JSX.Element => {
  return (
    <div className="loading" style={{ display: "grid", gap: "12px" }}>
      {Array.from({ length: rows }).map((_, index) => (
        <span key={`skeleton-${index}`} className="skeleton" />
      ))}
    </div>
  );
};

export default SkeletonList;
