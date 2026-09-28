export {}

declare global {
  interface Window {
    pywebview: any;
    addLog: (msg: string) => void;
    updateProgress: (id: string, desc: string, n: number, total: number) => void;
  }
}
