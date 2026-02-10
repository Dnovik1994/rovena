import React from "react";

interface ToastProps {
  message: string;
}

const Toast = ({ message }: ToastProps): JSX.Element => {
  return (
    <div className="card" style={{ position: "fixed", right: 16, top: 16, zIndex: 50 }}>
      <div className="card__body" style={{ padding: "10px 12px" }}>{message}</div>
    </div>
  );
};

export default Toast;
