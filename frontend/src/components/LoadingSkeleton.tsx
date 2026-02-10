import React from "react";

import SkeletonList from "./SkeletonList";

interface LoadingSkeletonProps {
  rows?: number;
  label?: string;
}

const LoadingSkeleton = ({ rows = 4, label = "Загрузка..." }: LoadingSkeletonProps): JSX.Element => {
  return (
    <div className="loading" style={{ textAlign: "left" }}>
      <p className="label">{label}</p>
      <SkeletonList rows={rows} />
    </div>
  );
};

export default LoadingSkeleton;
