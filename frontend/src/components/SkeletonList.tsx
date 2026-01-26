import React from "react";

interface SkeletonListProps {
  rows?: number;
}

const SkeletonList = ({ rows = 3 }: SkeletonListProps): JSX.Element => {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={`skeleton-${index}`}
          className="h-16 w-full animate-pulse rounded-xl bg-slate-900"
        />
      ))}
    </div>
  );
};

export default SkeletonList;
