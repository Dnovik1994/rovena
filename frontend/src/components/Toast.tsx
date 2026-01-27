import React from "react";

interface ToastProps {
  message: string;
}

const Toast = ({ message }: ToastProps): JSX.Element => {
  return (
    <div className="fixed right-4 top-4 z-50 rounded-xl bg-slate-950/90 px-4 py-2 text-xs text-slate-100 shadow-lg">
      {message}
    </div>
  );
};

export default Toast;
