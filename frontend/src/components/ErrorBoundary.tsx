import React from "react";

interface ErrorBoundaryProps {
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error?: Error;
}

/**
 * Global React Error Boundary.
 *
 * Catches render-time errors in the component tree and displays
 * a neutral fallback UI instead of a white screen.
 */
class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    console.error("[ErrorBoundary] Uncaught render error:", error, errorInfo);

    // If Sentry is loaded globally (e.g. via <script> tag), report the error.
    const sentry = (window as unknown as { Sentry?: { captureException?: (err: Error, ctx?: unknown) => void } }).Sentry;
    if (sentry?.captureException) {
      sentry.captureException(error, {
        extra: { componentStack: errorInfo.componentStack },
      });
    }
  }

  private handleReload = () => {
    window.location.reload();
  };

  private handleGoHome = () => {
    this.setState({ hasError: false, error: undefined });
    window.location.assign("/");
  };

  render(): React.ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 p-6">
        <div className="w-full max-w-md rounded-2xl border border-slate-700/60 bg-slate-900/80 p-8 text-center shadow-xl">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-rose-500/20 text-2xl text-rose-400">
            !
          </div>

          <h1 className="mb-2 text-lg font-semibold text-slate-100">
            Произошла ошибка
          </h1>

          <p className="mb-6 text-sm text-slate-400">
            Приложение столкнулось с непредвиденной ошибкой. Попробуйте перезагрузить
            страницу или вернуться на главную.
          </p>

          {this.state.error && (
            <pre className="mb-6 max-h-24 overflow-auto rounded-lg bg-slate-800/60 p-3 text-left text-xs text-slate-500">
              {this.state.error.message}
            </pre>
          )}

          <div className="flex flex-col gap-3 sm:flex-row sm:justify-center">
            <button
              type="button"
              onClick={this.handleReload}
              className="rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-500"
            >
              Перезагрузить
            </button>
            <button
              type="button"
              onClick={this.handleGoHome}
              className="rounded-xl border border-slate-600 px-5 py-2.5 text-sm font-medium text-slate-300 transition hover:bg-slate-800"
            >
              На главную
            </button>
          </div>
        </div>
      </div>
    );
  }
}

export default ErrorBoundary;
