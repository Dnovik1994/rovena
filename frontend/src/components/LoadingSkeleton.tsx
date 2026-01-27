import React from "react";

import SkeletonList from "./SkeletonList";

interface LoadingSkeletonProps {
  rows?: number;
  label?: string;
}

const LoadingSkeleton = ({ rows = 4, label = "Загрузка..." }: LoadingSkeletonProps): JSX.Element => {
  return (
    <div className="space-y-3">
      <p className="text-xs uppercase text-slate-500">{label}</p>
      <SkeletonList rows={rows} />
    </div>
  );
};

export default LoadingSkeleton;
